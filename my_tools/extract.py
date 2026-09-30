# -*- coding: utf-8 -*-
"""
功能一：微信数据库 → 本地数据库
================================
输入：
    - 微信本地数据库路径（db_storage 或账号根目录，不填则自动检测）
    - 时间范围（可选，YYYY-MM-DD 起止）
输出：
    - 解密后的完整数据库 + 消息摘要索引库 chats.db

用法：
    python my_tools/extract.py [--db-dir 微信数据库路径]
                               [--wxid 账号wxid]
                               [--date-from 2024-01-01] [--date-to 2024-12-31]
                               [-o 输出目录]
    # 不传 --db-dir 时自动检测本机正在运行的微信数据目录

失败时返回预设错误码（见 config.EC），便于人工检查。
"""
import argparse
import os
import sys
import traceback

from config import EC, result, ensure_sys_path, PROJECT_ROOT, DEFAULT_OUTPUT_DIR

ensure_sys_path()

from checker import check_db_dir, check_date_range          # noqa: E402
from engine.config_file import set_backup_data_dir          # noqa: E402


# ---------------------------------------------------------------------------
def _find_wechat_dirs():
    """自动检测本机微信数据目录。"""
    from engine.utils import find_all_wechat_data_dirs
    return find_all_wechat_data_dirs()


def run_extract(db_dir: str = None, wxid: str = None,
                date_from: str = None, date_to: str = None,
                output_dir: str = None) -> dict:
    """功能一主流程。返回统一结果结构。"""
    ensure_sys_path()
    try:
        # ---- 1. 数据库路径检测 ----
        if db_dir:
            r = check_db_dir(db_dir)
            if not r['ok']:
                return r
            db_path = r['data']['db_path']
        else:
            try:
                dirs = _find_wechat_dirs()
                # 上游对同一 wxid 可能返回多个路径，按 wxid 去重保留消息库最多的
                _by_wxid = {}
                for d in dirs:
                    w = d.get('wxid') or d.get('db_path')
                    if w not in _by_wxid or d.get('db_count', 0) > _by_wxid[w].get('db_count', 0):
                        _by_wxid[w] = d
                dirs = list(_by_wxid.values())
            except Exception as e:
                return result(False, EC.ERR_NO_WECHAT_DATA,
                              f'自动检测微信数据目录失败: {e}')
            if not dirs:
                return result(False, EC.ERR_NO_WECHAT_DATA,
                              '未检测到微信数据目录。请用 --db-dir 显式指定'
                              '（如 D:\\xwechat_files\\wxid_xxx\\db_storage）')
            if wxid:
                match = [d for d in dirs if d['wxid'] == wxid]
                if not match:
                    return result(False, EC.ERR_NO_CONTACT,
                                  f'未找到账号 {wxid}，可用: {[d["wxid"] for d in dirs]}')
                db_path, wxid = match[0]['db_path'], match[0]['wxid']
            elif len(dirs) == 1:
                db_path, wxid = dirs[0]['db_path'], dirs[0]['wxid']
            else:
                return result(False, EC.ERR_AMBIGUOUS_CONTACT,
                              f'检测到 {len(dirs)} 个微信账号，请用 --wxid 指定: '
                              f'{[d["wxid"] for d in dirs]}')
        print(f'[1/4] 数据库目录: {db_path}' + (f'  (账号 {wxid})' if wxid else ''))

        # ---- 2. 时间范围检测 ----
        r = check_date_range(date_from, date_to)
        if not r['ok']:
            return r
        print(f'[2/4] 时间范围: {date_from or "不限"} ~ {date_to or "不限"}')

        # ---- 3. 执行备份管线（扫描→解密→媒体→索引） ----
        from backup.pipeline import run_backup
        out_dir = output_dir or os.path.join(DEFAULT_OUTPUT_DIR, 'backup')
        print(f'[3/4] 输出目录: {out_dir}')

        def _progress(stage, detail, pct):
            pct_i = int(pct * 100)
            sys.stdout.write(f'\r      {stage:<8s} {pct_i:>3d}%  {detail:<40s}')
            sys.stdout.flush()

        try:
            res = run_backup(
                db_path,
                out_dir,
                start_date=date_from,
                end_date=date_to,
                on_progress=_progress,
            )
        except Exception as e:
            print(f'\n解密管线异常: {e}')
            traceback.print_exc()
            return result(False, EC.ERR_BACKUP, f'备份管线异常: {e}')
        print()

        # ---- 4. 产出校验 ----
        errors = res.get('errors') or []
        if errors:
            print('备份管线报告以下问题:')
            for err in errors:
                print('   -', err)
        if not res.get('success'):
            return result(False, EC.ERR_BACKUP,
                          f'备份未完成: {"; ".join(errors[:3])}', res)

        chats_db = res.get('stats', {}).get('indexed')
        if not chats_db or not os.path.isfile(chats_db):
            return result(False, EC.ERR_OUTPUT_NOT_FOUND,
                          f'索引库 chats.db 未生成: {chats_db}')

        print(f'[4/4] 完成。索引库: {chats_db}')
        stats = res.get('stats', {})
        print(f'      解密库: {stats.get("decrypted", 0)} 个 | '
              f'媒体: {stats.get("migrated", {})} | '
              f'V2密钥: {stats.get("v2_keys_harvested", 0)} 个')
        return result(True, EC.OK, '备份成功', {'output_dir': out_dir, 'stats': stats})

    except KeyboardInterrupt:
        return result(False, 'ERR_ABORTED', '用户中断')
    except Exception as e:
        traceback.print_exc()
        return result(False, EC.ERR_INTERNAL, f'{type(e).__name__}: {e}')


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        prog='my_tools.extract',
        description='功能一：输入微信本地数据库 + 时间范围 → 形成本地数据库')
    ap.add_argument('--db-dir', help='微信数据库路径（db_storage 或账号根目录），默认自动检测')
    ap.add_argument('--wxid', help='指定微信账号 wxid（多账号时必选）')
    ap.add_argument('--date-from', help='起始日期 YYYY-MM-DD')
    ap.add_argument('--date-to', help='截止日期 YYYY-MM-DD')
    ap.add_argument('-o', '--output', help='输出目录（默认 my_output/backup）')
    args = ap.parse_args()

    r = run_extract(args.db_dir, args.wxid, args.date_from, args.date_to, args.output)
    print()
    print('=' * 56)
    print(f'结果: {"成功" if r["ok"] else "失败"}  [错误码: {r["code"]} - {EC.label(r["code"])}]')
    print(f'说明: {r["message"]}')
    sys.exit(0 if r['ok'] else 1)


if __name__ == '__main__':
    main()