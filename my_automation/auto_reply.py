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
if _AI_DIR not in sys.path:
    sys.path.insert(0, _AI_DIR)

from monitor import MessageMonitor           # noqa: E402
import tasks                                 # noqa: E402

DEFAULT_SYSTEM = ("你是一个微信聊天助手。对方发来的消息用自然的中文简短回复，"
                  "语气友好，一般 1~2 句话即可，不要自称是AI助手。")


def _generate_reply(content: str, system_prompt: str) -> str:
    """调用 GLM 生成回复；失败返回空串。"""
    from ai import ask
    r = ask(content, provider='glm', system=system_prompt,
            thinking=False, timeout=30)
    if r.get('status') != 'success':
        print(f"    [AI失败] {r.get('message')}")
        return ''
    return str((r.get('data') or {}).get('content') or '').strip()


def auto_reply(interval=2.0, only_contact=None, window_mode=True,
               cooldown=60, system_prompt=DEFAULT_SYSTEM,
               run_seconds=None, stop_event=None, dry_run=False) -> dict:
    """启动自动回复监控。"""
    mon = MessageMonitor()
    if not mon.src:
        print("初始化失败：未找到微信数据库/密钥")
        return {"ok": False, "code": "ERR_INIT"}

    last_reply_at = {}     # sender_id -> time
    stats = {"seen": 0, "replied": 0, "skipped": 0}

    def on_message(m):
        if m.get('side') != '对方':
            return
        if m.get('type') != 1:          # 仅文本消息
            stats["skipped"] += 1
            return
        if only_contact and only_contact not in (m.get('sender_id') or ''):
            stats["skipped"] += 1
            return

        sender = m.get('sender_id') or 'unknown'
        now = time.time()
        if now - last_reply_at.get(sender, 0) < cooldown:
            stats["skipped"] += 1       # 冷却中
            return

        content = (m.get('content') or '').strip()
        print(f"[收到] {m['time']} {sender}: {content[:80]}")
        if not content:
            return

        reply = _generate_reply(content, system_prompt)
        if not reply:
            return
        print(f"[AI] {reply[:120]}")

        if dry_run:
            stats["replied"] += 1
            last_reply_at[sender] = now
            return

        # 发送回复给发送者（用 wxid 搜索打开聊天）
        r = tasks.open_contact_chat(sender, window_mode=window_mode)
        if not r.get('ok'):
            print(f"    [发送失败] 打开{ sender }聊天失败: {r.get('message')}")
            return
        if window_mode:
            rr = __import__('sender').send_text_window(reply)
        else:
            rr = __import__('sender').send_message(reply)
        if rr.get('ok'):
            stats["replied"] += 1
            last_reply_at[sender] = now
            print(f"    [已回复] {sender}")
        else:
            print(f"    [发送失败] {rr.get('message')}")

    mon.watch(interval=interval, on_message=on_message,
              run_seconds=run_seconds, stop_event=stop_event)
    print(f"自动回复结束 | 看到 {stats['seen']} | 回复 {stats['replied']} | 跳过 {stats['skipped']}")
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
    ap.add_argument("--interval", type=float, default=2.0, help="轮询秒数")
    args = ap.parse_args()
    auto_reply(interval=args.interval, only_contact=args.only,
               window_mode=not args.no_window, run_seconds=args.seconds,
               dry_run=args.dry_run)


if __name__ == "__main__":
    main()