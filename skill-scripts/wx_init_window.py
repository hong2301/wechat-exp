# -*- coding: utf-8 -*-
"""wx_init_window — 微信窗口初始化（skill 薄壳）。
自动：关闭嵌入搜一搜页(点位4) → 唯一主窗口前置 → 左半屏 → 校验。
用法: python wx_init_window.py"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "my_automation"))
sys.path.insert(0, os.path.join(REPO, "src"))

import wechat_status as ws

if __name__ == "__main__":
    r = ws.init_wechat_window()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)