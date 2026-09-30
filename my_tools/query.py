# -*- coding: utf-8 -*-
"""
功能二：按联系人 + 时间段 提取完整聊天数据
========================================
输入：
    - 联系人（显示名/备注/微信号，支持模糊匹配）
    - 时间范围（可选，YYYY-MM-DD 起止）
    - 已解密数据目录（默认自动定位最近一次备份）
输出：
    - 结构化 JSON 文件（完整消息：时间、发送者、类型、内容、原始字段）
    - 可选 TXT / HTML 导出（复用上游 export_chat）

用法：
    python my_tools/query.py --contact 张三 [--date-from 2024-01-01] [--date-to 2024-12-31]
                             [--decrypted-dir 解密目录] [--format json|txt|html] [-o 输出目录]

失败时返回预设错误码（见 config.EC），便于人工检查。
"""
import argparse
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime

from config import EC, result, ensure_sys_path, DEFAULT_OUTPUT_DIR

ensure_sys_path()

from checker import (                                        # noqa: E402
    check_decrypted_dir, check_date_range, find_contact,
)
from engine.constants import TZ, MSG_TYPES_CN                # noqa: E402
from engine.services.message.decode import decompress_content # noqa: E402
from engine.services.sender_model import (                    # noqa: E402
    ShardSenderModel, load_name2id,
)
from chat_export import (                                    # noqa: E402
    _extract_own_wxid, _build_sender_map, _resolve_sender_any,
    _format_content, export_chat,
)


# ---------------------------------------------------------------------------
def _resolve_decrypted_dir():
    """自动定位最近一次备份的解密目录。"""
    from engine.config_file import get_backup_data_dir, get_latest_backup_dir
    d = get_backup_data_dir()
    if d and os.path.isdir(d):
        return d
    backup_root = os.path.join(PROJECT_ROOT := os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), 'backup')
    d = get_latest_backup_dir(backup_root)
    return d or None


def _load_messages_json(chat_info, start_ts, end_ts, decrypted_dir):
    """读取单个会话的完整消息，返回结构化列表。

    参照 chat_export.export_chat 的实现（相同的时间过滤、
    发送者归属 Name2Id 权威逻辑、内容格式化）。
    """
    uname = chat_info['username']
    is_group = uname.endswith('@chatroom')
    tables = chat_info['tables']

    # 1) 按时间过滤加载原始行
    all_rows = []
    for t in tables:
        conn = None
        try:
            conn = sqlite3.connect(t['db_path'])
            where, params = [], []
            if start_ts:
                where.append('create_time >= ?'); params.append(start_ts)
            if end_ts:
                where.append('create_time <= ?'); params.append(end_ts)
            query = ('SELECT local_id, local_type, real_sender_id, create_time, '
                     'status, message_content, origin_source '
                     f"FROM [{t['table_name']}] WHERE create_time > 1000000000")
            if where:
                query += ' AND ' + ' AND '.join(where)
            query += ' ORDER BY create_time ASC'
            for r in conn.execute(query, params):
                all_rows.append((t['db_path'], r))
        except (sqlite3.Error, OSError):
            continue
        finally:
            if conn:
                conn.close()
    if not all_rows:
        return []
    all_rows.sort(key=lambda r: r[1][3] or 0)

    # 2) 发送者/联系人显示名映射（与上游一致）
    sender_map = {}
    contact_db_path = None
    for t in tables:
        d = os.path.dirname(t['db_path'])
        candidate = os.path.join(os.path.dirname(d), 'contact', 'contact.db')
        if os.path.exists(candidate):
            contact_db_path = candidate
            break
    if contact_db_path:
        try:
            conn = sqlite3.connect(contact_db_path)
            for r in conn.execute(
                    'SELECT id, remark, nick_name, alias, username FROM contact'):
                wxid = (r[4] or '').strip()
                if wxid:
                    remark_v, nick_v, alias_v = (r[1] or '').strip(), (r[2] or '').strip(), (r[3] or '').strip()
                    display = remark_v if (remark_v and remark_v != wxid) else (
                        nick_v if (nick_v and nick_v != wxid) else (
                            alias_v if (alias_v and alias_v != wxid) else wxid))
                    if display:
                        sender_map[wxid] = display
            conn.close()
        except (sqlite3.Error, OSError):
            pass

    own_wxid = _extract_own_wxid(tables)
    db_sender_maps, db_name2id = {}, {}
    for t in tables:
        try:
            conn = sqlite3.connect(t['db_path'])
            db_sender_maps[t['db_path']] = _build_sender_map(
                conn, t['table_name'], own_wxid=own_wxid, chat_id=uname)
            db_name2id[t['db_path']] = load_name2id(conn)
            conn.close()
        except (sqlite3.Error, OSError):
            db_sender_maps[t['db_path']] = {}
            db_name2id[t['db_path']] = {}
    db_models = {t['db_path']: ShardSenderModel(db_name2id.get(t['db_path']) or {},
                                                uname, own_wxid)
                 for t in tables}

    # 3) 逐条解析
    messages = []
    for db_path, row in all_rows:
        local_id, ltype_raw, sender_id, create_time, status, content, origin = row
        base_type = (ltype_raw & 0xFFFF) if isinstance(ltype_raw, int) else ltype_raw

        if isinstance(content, bytes):
            content = decompress_content(content)
        if isinstance(content, bytes):
            try:
                content = content.decode('utf-8', errors='replace')
            except Exception:
                content = ''

        _model = db_models.get(db_path)
        if _model is not None:
            _side, _src, _member = _model.classify(
                sender_id, origin, content, local_type=base_type)
        else:
            _side, _member = ('me' if origin == 1 else 'unknown'), None

        if _side == 'me':
            sender = '我'
        elif _side == 'system':
            sender = '系统消息'
        elif _side == 'unknown':
            sender = '归属未定'
        else:
            _who = _member or ('' if is_group else uname)
            if _who:
                sender = sender_map.get(_who, _who)
                if sender == _who:
                    sender = _resolve_sender_any(_who, contact_db_path) or _who
            else:
                sender = f'ID:{sender_id}' if sender_id else ''

        text = _format_content(content, base_type, is_group)
        ts_s = int(create_time or 0)
        messages.append({
            'local_id': local_id,
            'time': datetime.fromtimestamp(ts_s, tz=TZ).strftime('%Y-%m-%d %H:%M:%S') if ts_s else None,
            'timestamp': ts_s,
            'sender': sender,
            'side': _side,
            'type': base_type,
            'type_name': MSG_TYPES_CN.get(base_type, f'未知类型({base_type})'),
            'content': text,
            'status': status,
        })
    return messages


def run_query(contact: str,
              date_from: str = None, date_to: str = None,
              decrypted_dir: str = None, fmt: str = 'json',
              out_dir: str = None) -> dict:
    """功能二主流程。返回统一结果结构。"""
    ensure_sys_path()
    try:
        # 1) 解密目录
        decrypted = decrypted_dir or _resolve_decrypted_dir()
        r = check_decrypted_dir(decrypted)
        if not r['ok']:
            return r
        print(f'[1/4] 解密目录: {decrypted}')

        # 2) 时间范围
        r = check_date_range(date_from, date_to)
        if not r['ok']:
            return r
        start_ts, end_ts = r['data']
        print(f'[2/4] 时间范围: {date_from or "不限"} ~ {date_to or "不限"}')

        # 3) 联系人匹配
        r = find_contact(decrypted, contact)
        if not r['ok']:
            return r
        matches = r['data']
        print(f'[3/4] 匹配会话 {len(matches)} 个: '
              + ', '.join(f'{c["display_name"]}({c["msg_count"]}条)' for c in matches))

        # 4) 读取完整消息
        out_root = out_dir or os.path.join(DEFAULT_OUTPUT_DIR, 'query')
        os.makedirs(out_root, exist_ok=True)
        results = []
        for chat in matches:
            msgs = _load_messages_json(chat, start_ts, end_ts, decrypted)
            safe = ''.join(c if c not in '<>:"/\\|?*' else '_' for c in chat['display_name'])[:40]
            payload = {
                'contact': chat['display_name'],
                'username': chat['username'],
                'is_group': chat['is_group'],
                'date_from': date_from,
                'date_to': date_to,
                'message_count': len(msgs),
                'messages': msgs,
            }
            results.append(payload)

            if fmt == 'json':
                out_path = os.path.join(out_root, f'{safe}.json')
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            else:
                # txt / html 复用上游 export_chat
                count, out_path = export_chat(
                    chat, out_root, start_ts=start_ts, end_ts=end_ts,
                    fmt=fmt, display_name=chat['display_name'])
                payload['message_count'] = count
            print(f'      -> {chat["display_name"]}: {payload["message_count"]} 条消息 '
                  f'=> {out_path}')

        total = sum(p['message_count'] for p in results)
        if total == 0:
            return result(False, EC.ERR_NO_MESSAGES,
                          f'联系人 {contact} 在 {date_from or "不限"} ~ '
                          f'{date_to or "不限"} 范围内没有消息')
        print(f'[4/4] 完成，共 {total} 条消息，输出目录: {out_root}')
        return result(True, EC.OK, '查询成功',
                      {'output_dir': out_root, 'results': results})

    except KeyboardInterrupt:
        return result(False, 'ERR_ABORTED', '用户中断')
    except Exception as e:
        traceback.print_exc()
        return result(False, EC.ERR_INTERNAL, f'{type(e).__name__}: {e}')


def main():
    ap = argparse.ArgumentParser(
        prog='my_tools.query',
        description='功能二：按联系人 + 时间段提取完整聊天数据')
    ap.add_argument('--contact', required=True, help='联系人（显示名/备注/微信号）')
    ap.add_argument('--date-from', help='起始日期 YYYY-MM-DD')
    ap.add_argument('--date-to', help='截止日期 YYYY-MM-DD')
    ap.add_argument('--decrypted-dir', help='已解密数据目录（默认自动定位最近备份）')
    ap.add_argument('--format', choices=['json', 'txt', 'html'], default='json',
                    help='输出格式（默认 json，结构化完整数据）')
    ap.add_argument('-o', '--output', help='输出目录（默认 my_output/query）')
    args = ap.parse_args()

    r = run_query(args.contact, args.date_from, args.date_to,
                  args.decrypted_dir, args.format, args.output)
    print()
    print('=' * 56)
    print(f'结果: {"成功" if r["ok"] else "失败"}  [错误码: {r["code"]} - {EC.label(r["code"])}]')
    print(f'说明: {r["message"]}')
    sys.exit(0 if r['ok'] else 1)


if __name__ == '__main__':
    main()