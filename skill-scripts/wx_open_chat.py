# -*- coding: utf-8 -*-
"""wx_open_chat — 打开联系人聊天窗口（skill 薄壳）。
用法: python wx_open_chat.py --contact 张三 [--paste] [--wait 0.8]"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "my_automation"))
sys.path.insert(0, os.path.join(REPO, "src"))

import tasks

if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="wx_open_chat")
    ap.add_argument("--contact", required=True, help="联系人名称/关键词")
    ap.add_argument("--paste", action="store_true", help="用剪贴板粘贴输入")
    ap.add_argument("--wait", type=float, default=0.8, help="搜索等待秒数")
    ap.add_argument("--window", action="store_true",
                    help="窗口级模式(PostMessage直达,不依赖系统焦点,适合Deskflow)")
    a = ap.parse_args()
    r = tasks.open_contact_chat(a.contact, use_paste=a.paste, wait_search=a.wait,
                                window_mode=a.window)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)