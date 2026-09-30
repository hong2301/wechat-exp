# -*- coding: utf-8 -*-
"""wx_extract — 微信数据库提取（skill 薄壳，透传 my_tools/extract.py）。
用法: 同 my_tools/extract.py，见 skill-refs/INDEX.md 2.1 节"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
target = os.path.join(REPO, "my_tools", "extract.py")

if __name__ == "__main__":
    args = list(sys.argv[1:])
    sys.exit(subprocess.call([sys.executable, target] + args))