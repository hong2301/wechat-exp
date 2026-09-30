# -*- coding: utf-8 -*-
"""wx_send — 发消息（文字/文件）到联系人（skill 薄壳）。
用法:
    python wx_send.py --contact 张三 --text "你好"
    python wx_send.py --contact 张三 --file C:/path/a.csv --file C:/path/b.xlsx"""
import argparse
import json
import os
import sys

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
    a = ap.parse_args()

    if not a.text and not a.file:
        print(json.dumps({"ok": False, "code": "ERR_EMPTY",
                          "message": "请用 --text 或 --file 提供内容"}, ensure_ascii=False))
        sys.exit(1)

    r = tasks.open_contact_chat(a.contact)
    if r.get("ok"):
        if a.text:
            r = sender.send_message(a.text, send=not a.no_enter)
        else:
            r = sender.send_message(a.file, send=not a.no_enter)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)