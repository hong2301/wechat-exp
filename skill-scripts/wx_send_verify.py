# -*- coding: utf-8 -*-
"""wx_send_verify — 发送并验证是否写入本地库（skill 薄壳）。
流程：打开聊天 → 粘贴+回车 → 轮询解密 message_0.db 验证（最多12次每秒1次）。
用法: python wx_send_verify.py --contact 张三 --content "内容" [--wait 0.8]"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "my_automation"))
sys.path.insert(0, os.path.join(REPO, "src"))

import tasks

if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="wx_send_verify")
    ap.add_argument("--contact", required=True, help="联系人")
    ap.add_argument("--content", required=True, help="发送内容")
    ap.add_argument("--wait", type=float, default=0.8, help="搜索等待秒数")
    a = ap.parse_args()
    r = tasks.send_and_verify(a.contact, a.content, wait_search=a.wait)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)