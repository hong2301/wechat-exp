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
    ap.add_argument("--system", action="store_true",
                    help="文件发送用系统级剪贴板粘贴（默认窗口级文件按钮）")
    ap.add_argument("--window", action="store_true",
                    help="窗口级模式(PostMessage直达,不依赖系统焦点,适合Deskflow)")
    a = ap.parse_args()

    if not a.text and not a.file:
        print(json.dumps({"ok": False, "code": "ERR_EMPTY",
                          "message": "请用 --text 或 --file 提供内容"}, ensure_ascii=False))
        sys.exit(1)

    r = tasks.open_contact_chat(a.contact, window_mode=not getattr(a, "system", False))
    if r.get("ok"):
        if a.text:
            # 文本默认窗口级（WM_CHAR，不碰剪贴板）；--system 才走剪贴板粘贴
            if a.system:
                r = sender.send_message(a.text, send=not a.no_enter)
            elif a.no_enter:
                sender._focus_and_clear_input(window_mode=True)
                r = __import__("wechat_input").post_text(a.text)
            else:
                r = sender.send_text_window(a.text)
        else:
            # 文件发送默认走窗口级（文件按钮+对话框，纯模拟输入，不碰剪贴板）；
            # 仅当显式 --system 时才用系统级剪贴板粘贴
            if getattr(a, 'system', False):
                r = sender.send_message(a.file, send=not a.no_enter)
            else:
                files = a.file if isinstance(a.file, list) else [a.file]
                for f in files:
                    r = sender.send_file_via_picker(f)
                    if not r.get('ok'):
                        break
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)