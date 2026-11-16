#!/usr/bin/env bash
# deploy.sh — 一键把开发仓库同步到 pi 技能目录
#
# 用法：
#   ./deploy.sh                     # 同步到默认位置 ~/.pi/agent/skills/wechat-data
#   ./deploy.sh /path/to/skill-dir  # 同步到指定技能目录
#   WECHAT_SKILL_DIR=... ./deploy.sh
#
# 约定（见 开发文档/开发习惯.md）：
#   - 只在开发仓库改代码，技能目录永远被动接收
#   - 技能目录自己的 .wechat_exp_config.json、my_automation/points.json 不被覆盖
#   - 不复制运行产物：my_output/、__pycache__/、*.log、auto_reply_state.json、config.json
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SK="${1:-${WECHAT_SKILL_DIR:-}}"
if [ -z "$SK" ]; then
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) SK="${USERPROFILE:-$HOME}/.pi/agent/skills/wechat-data" ;;
        *)                    SK="${HOME}/.pi/agent/skills/wechat-data" ;;
    esac
fi

if [ ! -d "$SK" ]; then
    echo "✗ 技能目录不存在: $SK" >&2
    echo "  先创建，或显式传入路径：./deploy.sh <技能目录>" >&2
    exit 1
fi

cd "$SRC"   # 后面所有相对路径都以仓库根为基准

echo "源（开发仓库）: $SRC"
echo "目标（技能目录）: $SK"

EXCL=(--exclude='__pycache__' --exclude='*.pyc' --exclude='*.log' --exclude='my_output')

sync_tree() {  # sync_tree <相对路径...>  以仓库根为基准复制到技能根
    tar -C "$SRC" -cf - "${EXCL[@]}" "$@" | tar -C "$SK" -xf -
}

# 1) 入口文档与依赖清单
cp "$SRC/SKILL.md" "$SK/SKILL.md"
[ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$SK/README.md"
[ -f "$SRC/requirements.txt" ] && cp "$SRC/requirements.txt" "$SK/requirements.txt"

# 2) 参考文档（整体替换，避免旧文件残留）
rm -rf "$SK/references"
sync_tree references

# 3) 运行代码
sync_tree skill-scripts/*.py
sync_tree my_tools
sync_tree ai
tar -C "$SRC" -cf - "${EXCL[@]}" \
    --exclude='points.json' --exclude='auto_reply_state.json' \
    my_automation | tar -C "$SK" -xf -

# 4) src 只带运行时需要的部分（web/ 6.3M 不要）
mkdir -p "$SK/src"
( cd "$SRC/src" && tar -cf - "${EXCL[@]}" engine backup *.py ) | tar -C "$SK/src" -xf -

# 5) 清掉可能被带过去的缓存
find "$SK" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

# 6) 自检
echo
echo "[自检] python wx_status.py"
if (cd "$SK/skill-scripts" && python wx_status.py 2>&1 | head -8); then
    echo
    echo "✓ 部署完成 → $SK"
else
    echo
    echo "✗ 部署后自检失败，先查依赖：pip install -r $SRC/requirements.txt" >&2
    exit 1
fi

echo
echo "提示：自动回复需要在技能目录放 config.json（GLM keys），该文件敏感、不入库、不随部署复制。"
