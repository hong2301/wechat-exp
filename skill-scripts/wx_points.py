# -*- coding: utf-8 -*-
"""wx_points — 点位管理（skill 薄壳，透传 points.py）。
用法:
    python wx_points.py show
    python wx_points.py capture [--point NAME]
    python wx_points.py clear"""
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
target = os.path.join(REPO, "my_automation", "points.py")

if __name__ == "__main__":
    args = list(sys.argv[1:]) if len(sys.argv) > 1 else ["show"]
    sys.exit(subprocess.call([sys.executable, "-X", "utf8", target] + args))