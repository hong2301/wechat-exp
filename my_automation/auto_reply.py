# -*- coding: utf-8 -*-
"""
auto_reply — 自动回复（监控 + AI + 发送 组合任务）
====================================================
流程：monitor 每秒解析数据库发现新消息 → 提取“对方”的文本消息 →
      AI（GLM）生成回复 → 打开联系人聊天发送回复。

方法：
    auto_reply(interval=2, only_contact=None, window_mode=True,
               cooldown=60, system_prompt=..., run_seconds=None,
               stop_event=None, dry_run=False)

参数：
    only_contact   只对包含此关键字的发送者回复（None=回复所有对方消息）
    cooldown       同一发送者的回复冷却秒数（默认 60，防刷屏）
    dry_run        True 只打印 AI 回复不实际发送（测试用）
"""
import os
import sys
import time

_SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
_AI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai')


def _load_ai():
    """用 spec 文件加载 ai 包（脚本模式下 sys.path 对 'ai' 解析不可靠，此方案已验证）。

    首次执行后模块缓存进 sys.modules，后续普通 import 直接命中。
    """
    import importlib.util
    init = os.path.join(_AI_DIR, '__init__.py')
    if os.path.exists(init) and 'ai' not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            'ai', init, submodule_search_locations=[_AI_DIR])
        mod = importlib.util.module_from_spec(spec)
        sys.modules['ai'] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop('ai', None)
            raise
    return sys.modules.get('ai')


_load_ai()

from monitor import MessageMonitor, _is_wxid   # noqa: E402
import tasks                                 # noqa: E402

DEFAULT_SYSTEM = ("你是一个微信聊天助手。对方发来的消息用自然的中文简短回复，"
                  "语气友好，一般 1~2 句话即可，不要自称是AI助手。")


_CONTACT_CACHE = {'map': None}

# 已回复消息状态（唯一 msg_id → 回复时间），跨重启防重复回复
_REPLIED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'auto_reply_state.json')
_REPLIED = None   # 惰性加载 {msg_id: ts}


def _load_replied() -> dict:
    global _REPLIED
    if _REPLIED is None:
        try:
            import json as _json
            with open(_REPLIED_FILE, 'r', encoding='utf-8') as f:
                _REPLIED = _json.load(f)
        except (OSError, ValueError):
            _REPLIED = {}
    return _REPLIED


def _mark_replied(msg_id):
    """记录某条消息已回复，并立即持久化。"""
    replied = _load_replied()
    replied[str(msg_id)] = time.time()
    try:
        import json as _json
        with open(_REPLIED_FILE, 'w', encoding='utf-8') as f:
            _json.dump(replied, f, ensure_ascii=False)
    except OSError:
        pass


def _load_contact_display():
    """解密 contact.db，构建 {wxid: {alias 微信号, remark, nick}} 缓存（每进程一次）。"""
    if _CONTACT_CACHE['map'] is not None:
        return _CONTACT_CACHE['map']
    import tempfile
    import sqlite3 as _sq
    from engine.config_file import get_db_keys
    from backup.decryptor import resolve_key_for
    from engine.decrypt import decrypt_database
    import wechat_status as ws

    m = {}
    active = ws.get_active_data_dir()
    if not active:
        _CONTACT_CACHE['map'] = m
        return m
    src = os.path.join(active, 'contact', 'contact.db')
    if not os.path.isfile(src):
        _CONTACT_CACHE['map'] = m
        return m
    key = resolve_key_for(src, get_db_keys())
    tmp = tempfile.mktemp(suffix='.db')
    try:
        try:
            decrypt_database(src, tmp, key)
        except Exception:
            _CONTACT_CACHE['map'] = m
            return m
        conn = _sq.connect(tmp)
        try:
            for r in conn.execute(
                    'SELECT username, remark, nick_name, alias FROM contact'):
                uname = str(r[0] or '').strip()
                if not uname:
                    continue
                m[uname] = {'alias': str(r[3] or '').strip(),
                            'remark': str(r[1] or '').strip(),
                            'nick': str(r[2] or '').strip()}
        finally:
            conn.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    _CONTACT_CACHE['map'] = m
    return m


def resolve_open_target(wxid):
    """把发送者 wxid 反查为“微信搜索可打开且唯一”的身份。

    优先返回【微信号 alias】（微信中唯一、搜索精确命中，无同名问题）；
    无微信号时才用备注/昵称，并做唯一性校验（同名多人 → None 跳过，防误发）。
    """
    wxid = str(wxid or '').strip()
    if not wxid:
        return None
    m = _load_contact_display()
    rec = m.get(wxid)
    if rec is None:
        # 兼容带账号后缀：wxid_e33uf5ospsh819_ccb3 vs base
        for k, v in m.items():
            if k.startswith(wxid) or wxid.startswith(k):
                rec = v
                break
    if not rec:
        return None   # 陌生人/未加好友

    # 1) 微信号 alias 唯一且可搜 → 直接用它（最精确）
    if rec['alias']:
        return rec['alias']

    # 2) 备选显示名（备注>昵称），同名则跳过
    display = rec['remark'] or rec['nick']
    if not display:
        return None
    hits = sum(1 for v in m.values()
               if (v['remark'] or v['nick']) == display)
    if hits > 1:
        return None
    return display


def _clip(msg, max_chars):
    """截断字符串到 max_chars。"""
    msg = str(msg or '').strip()
    return msg if len(msg) <= max_chars else msg[:max_chars] + '…'


def _budget_trim(messages, max_total, reserve):
    """从中间裁剪，保证总字符 ≤ max_total（保留首 system 与末尾待回复）。"""
    total = sum(len(str(m.get('content') or '')) for m in messages)
    if total <= max_total:
        return messages
    # 逐条丢弃最早的历史（保留 system[0] 与末尾 user）
    while len(messages) > 2 and total > max_total:
        dropped = messages.pop(1)
        total -= len(str(dropped.get('content') or ''))
    return messages


def _build_context(mon, sender_id, content, system_prompt,
                   history_limit=10, extra_contacts=None,
                   max_msg_chars=300, max_context_chars=4000,
                   search_keywords=None):
    """构建多轮上下文 messages（对方=user，我方=assistant）。

    限制（防超 token）：
        history_limit      当前联系人历史条数
        max_msg_chars      单条消息最大字符数（截断）
        max_context_chars  上下文总字符预算（超出裁剪最早历史）
    extra_contacts：持续附加指定联系人的近期消息（system 注注入来源）
    search_keywords：当前消息命中关键词时，检索其他联系人相关消息加入
    """
    messages = [{'role': 'system', 'content': system_prompt}]

    # 当前联系人历史
    hist = mon.load_history_for(sender_id, limit=history_limit)
    for m in hist:
        role = 'user' if m.get('side') == '对方' else 'assistant'
        msg = _clip(m.get('content'), max_msg_chars)
        if msg:
            messages.append({'role': role, 'content': msg})

    # 主动附加的其他联系人近期消息（带条数与长度限制）
    for cid in (extra_contacts or []):
        if not cid or cid == sender_id:
            continue
        hist = mon.load_history_for(cid, limit=3)
        if not hist:
            continue
        lines = [f"{m['time']} {'我' if m.get('side') == '我' else cid}:"
                 f" {_clip(m.get('content'), max_msg_chars)}" for m in hist]
        messages.append({'role': 'system',
                         'content': f"（其他联系人 {cid} 的近期消息参考）\n"
                                    + "\n".join(lines)})

    # 关键词检索其他联系人消息（当前消息命中词时触发）
    for kw in (search_keywords or []):
        if str(kw) in content:
            hits = mon.search_messages(kw, limit=3)
            if hits:
                lines = [f"{m['time']} {m.get('sender_id')}:"
                         f" {_clip(m.get('content'), max_msg_chars)}"
                         for m in hits]
                messages.append({'role': 'system',
                                 'content': f"（检索到与「{kw}」相关的消息）\n"
                                            + "\n".join(lines)})

    # 当前待回复消息
    messages.append({'role': 'user',
                     'content': _clip(content, max_msg_chars)})
    # 总预算裁剪
    return _budget_trim(messages, max_context_chars, 0)


def _generate_reply_ctx(mon, sender_id, content, system_prompt,
                        history_limit=10, extra_contacts=None,
                        max_msg_chars=300, max_context_chars=4000,
                        search_keywords=None) -> str:
    """带上下文的 AI 回复生成（含长度限制）；失败返回空串。"""
    from ai import chat
    messages = _build_context(mon, sender_id, content, system_prompt,
                              history_limit=history_limit,
                              extra_contacts=extra_contacts,
                              max_msg_chars=max_msg_chars,
                              max_context_chars=max_context_chars,
                              search_keywords=search_keywords)
    r = chat(messages, provider='glm', thinking=False, timeout=30)
    if r.get('status') != 'success':
        print(f"    [AI失败] {r.get('message')}")
        return ''
    return str((r.get('data') or {}).get('content') or '').strip()


def auto_reply(interval=1.0, only_contact=None, window_mode=True,
               cooldown=60, system_prompt=DEFAULT_SYSTEM,
               run_seconds=None, stop_event=None, dry_run=False,
               history_limit=10, extra_contacts=None,
               max_msg_chars=300, max_context_chars=4000,
               search_keywords=None, one_shot=True) -> dict:
    """启动自动回复监控。"""
    mon = MessageMonitor()
    if not mon.src:
        print("初始化失败：未找到微信数据库/密钥")
        return {"ok": False, "code": "ERR_INIT"}

    last_reply_at = {}     # sender_id -> time
    stats = {"seen": 0, "replied": 0, "skipped": 0}

    def on_message(m):
        if m.get('side') != '对方':
            return False
        if m.get('type') != 1:          # 仅文本消息
            stats["skipped"] += 1
            return False
        if only_contact and only_contact not in (m.get('sender_id') or ''):
            stats["skipped"] += 1
            return False

        sender = m.get('sender_id') or 'unknown'
        now = time.time()
        # 安全阀：sender 必须是解析出的真实 wxid；并解析出可搜索身份
        if not _is_wxid(str(sender)):
            print(f"    [跳过] 未能解析发送者 wxid（sender_id={sender}），不回复")
            stats["skipped"] += 1
            return False
        open_target = resolve_open_target(str(sender))
        if not open_target:
            print(f"    [跳过] 发送者 {sender} 未在好友/会话表中找到可搜索身份，"
                  f"为避免误发跳过")
            stats["skipped"] += 1
            return False
        if now - last_reply_at.get(sender, 0) < cooldown:
            stats["skipped"] += 1       # 冷却中
            return False

        content = (m.get('content') or '').strip()
        mid = str(m.get('msg_id') or m.get('local_id') or '')
        if mid and mid in _load_replied():
            print(f"    [跳过] 消息 {mid} 已回复过")
            stats["skipped"] += 1
            return False
        print(f"[收到] {m['time']} {sender}: {content[:80]}")
        if not content:
            return False

        # 带上下文的 AI 回复（历史 + 其他联系人参考 + 关键词检索，均限长）
        reply = _generate_reply_ctx(
            mon, sender, content, system_prompt,
            history_limit=history_limit, extra_contacts=extra_contacts,
            max_msg_chars=max_msg_chars,
            max_context_chars=max_context_chars,
            search_keywords=search_keywords)
        if not reply:
            return False
        print(f"[AI] {reply[:120]}")

        if dry_run:
            stats["replied"] += 1
            last_reply_at[sender] = now
            return True

        # 发送回复（用可搜索身份打开聊天）
        print(f"    [目标] wxid={sender} → 搜索词={open_target}")
        r = tasks.open_contact_chat(open_target, window_mode=window_mode)
        if not r.get('ok'):
            print(f"    [发送失败] 打开{ sender }聊天失败: {r.get('message')}")
            return False
        if window_mode:
            rr = __import__('sender').send_text_window(reply)
        else:
            rr = __import__('sender').send_message(reply)
        if rr.get('ok'):
            stats["replied"] += 1
            last_reply_at[sender] = now
            if mid:
                _mark_replied(mid)
            print(f"    [已回复] {sender} (msg={mid})")
            return True
        else:
            print(f"    [发送失败] {rr.get('message')}")
            return False

    # 自循环：取代 mon.watch，支持“回复成功即退出”（one_shot）
    mon.baseline()
    try:
        mon.poll_once()          # 预热：窗口内历史标记已见
    except Exception:
        pass
    print(f"监控已启动 | 扫描窗口: 最近 {mon.window_seconds}s | 轮询 {interval}s | "
          f"模式: {'单发即停' if one_shot else '持续'}")
    t0 = time.time()
    try:
        while True:
            wc, wsz = mon.wal_changed()
            if wc and wsz:
                print(f"    [WAL] 检测到新消息写入（WAL {wsz//1024}KB），等待微信 checkpoint 落库...")
            msgs = mon.poll_once()
            for m in msgs:
                try:
                    done = on_message(m)   # 返回 True 表示成功回复
                except Exception as e:
                    print(f"    [异常] {e}")
                    done = False
                if done and one_shot:
                    print("✅ 已回复，单发模式退出")
                    return {"ok": True, "stats": stats}
            if stop_event is not None and stop_event.is_set():
                break
            if run_seconds is not None and time.time() - t0 >= run_seconds:
                break
            if one_shot and stats.get("replied"):
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    print(f"自动回复结束 | 回复 {stats['replied']} | 跳过 {stats['skipped']}")
    return {"ok": True, "stats": stats}


# ---------------------------------------------------------------------------
# CLI：python my_automation/auto_reply.py [--seconds N] [--dry-run]
#                                    [--only 关键词] [--no-window]
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(prog="my_automation.auto_reply",
                                 description="微信自动回复（监控+AI+发送）")
    ap.add_argument("--seconds", type=int, default=None, help="运行秒数")
    ap.add_argument("--only", default=None, help="只回复包含此关键字的发送者")
    ap.add_argument("--dry-run", action="store_true", help="只生成不发送(测试)")
    ap.add_argument("--no-window", action="store_true", help="用系统级模式(默认窗口级)")
    ap.add_argument("--interval", type=float, default=1.0, help="轮询秒数(默认每秒)")
    ap.add_argument("--history", type=int, default=10, help="上下文历史条数")
    ap.add_argument("--extra", action="append", default=[],
                    help="附加其他联系人到上下文(可多个, 用wxid)")
    ap.add_argument("--search-kw", action="append", default=[],
                    help="关键词检索其他联系人消息加入上下文(消息含词时触发)")
    ap.add_argument("--max-ctx", type=int, default=4000, help="上下文总字符预算")
    ap.add_argument("--watch", action="store_true", help="持续监控模式(默认回复一条即退出)")
    args = ap.parse_args()
    auto_reply(interval=args.interval, only_contact=args.only,
               window_mode=not args.no_window, run_seconds=args.seconds,
               dry_run=args.dry_run, history_limit=args.history,
               extra_contacts=args.extra, max_context_chars=args.max_ctx,
               search_keywords=args.search_kw, one_shot=not args.watch)


if __name__ == "__main__":
    main()