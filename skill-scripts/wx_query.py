# -*- coding: utf-8 -*-
"""wx_query — 查询联系人聊天数据（skill 薄壳，透传 my_tools/query.py）。
用法: 同 my_tools/query.py，见 skill-refs/INDEX.md 2.2 节"""
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
target = os.path.join(REPO, "my_tools", "query.py")

if __name__ == "__main__":
    args = list(sys.argv[1:])
    sys.exit(subprocess.call([sys.executable, "-X", "utf8", target] + args))