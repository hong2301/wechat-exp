# -*- coding: utf-8 -*-
"""wx_send — 发消息（文字/文件）到联系人（skill 薄壳）。
用法:
    python wx_send.py --contact 张三 --text "你好"
    python wx_send.py --contact 张三 --file C:/path/a.csv --file C:/path/b.xlsx"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "my_automation"))
sys.path.insert(0, os.path.join(REPO, "src"))

import tasks
import sender

if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="wx_send")
    ap.add_argument("--contact", required=True, help="联系人名称/关键词")
    ap.add_argument("--text", help="要发的文字")
    ap.add_argument("--file", action="append", default=[], help="要发的文件(可多个)")
    ap.add_argument("--no-enter", action="store_true", help="只粘贴不发送")
    ap.add_argument("--window", action="store_true",
                    help="窗口级模式(PostMessage直达,不依赖系统焦点,适合Deskflow)")
    a = ap.parse_args()

    if not a.text and not a.file:
        print(json.dumps({"ok": False, "code": "ERR_EMPTY",
                          "message": "请用 --text 或 --file 提供内容"}, ensure_ascii=False))
        sys.exit(1)

    r = tasks.open_contact_chat(a.contact, window_mode=a.window)
    if r.get("ok"):
        if a.text:
            if a.window:
                if a.no_enter:
                    # 窗口级只输入不发送：先清空输入框再输入
                    sender._focus_and_clear_input(window_mode=True)
                    r = __import__("wechat_input").post_text(a.text)
                else:
                    r = sender.send_text_window(a.text)
            else:
                r = sender.send_message(a.text, send=not a.no_enter)
        else:
            if a.window:
                # 窗口级文件发送：文件按钮 → 对话框 → 全窗口消息（不碰剪贴板）
                files = a.file if isinstance(a.file, list) else [a.file]
                for f in files:
                    r = sender.send_file_via_picker(f)
                    if not r.get('ok'):
                        break
            else:
                r = sender.send_message(a.file, send=not a.no_enter)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)