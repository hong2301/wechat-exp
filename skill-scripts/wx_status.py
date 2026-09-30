# -*- coding: utf-8 -*-
"""wx_status — 微信状态检查（skill 薄壳）。用法: python wx_status.py"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "my_automation"))
sys.path.insert(0, os.path.join(REPO, "src"))

import wechat_status as ws

if __name__ == "__main__":
    print(json.dumps(ws.get_status(), ensure_ascii=False, indent=2))