---
name: wechat-data
description: 微信数据技能。处理本机微信的业务：读取/导出本地聊天数据库（按联系人、时间段查询），自动化操作微信客户端（登录检测、窗口初始化、点位管理、打开联系人聊天、发送文字/文件、发送后入数据库验证）。处理微信聊天记录读写时使用。
license: proprietary
metadata:
  repo: https://github.com/hong2301/wechat-exp
---

# 微信数据（WeChat Data）

本技能封装两个能力域：

- **读** `my_tools/`：微信本地数据库提取与查询
- **写** `my_automation/`：微信客户端自动化（检测登录 / 窗口初始化 / 点位 / 打开聊天 / 发消息 / 发送验证）

## 技能结构

```
<SKILL_DIR>/
├── SKILL.md                # 入口（本文件）
├── references/             # 详细参考，按需查阅
│   ├── api.md              # 模块地图 / 方法签名 / AI 自动回复
│   ├── error-codes.md      # 错误码全表
│   └── pitfalls.md         # 20 条防坑记录
├── skill-scripts/          # 命令行入口
├── my_automation/          # 微信客户端自动化
├── my_tools/               # 本地数据库读写
├── src/                    # 解密与数据服务
└── .wechat_exp_config.json # 本机数据库密钥
```

脚本用绝对路径调用：

```bash
python "<SKILL_DIR>/skill-scripts/wx_status.py"
```

## 快速开始（脚本方式）

```bash
cd <SKILL_DIR>

# 微信状态（运行 / 登录 / 占用账号 / 窗口）
python skill-scripts/wx_status.py

# 窗口初始化：自动关闭嵌入搜一搜页 → 唯一主窗口前置 → 左半屏
python skill-scripts/wx_init_window.py

# 点位：查看 / 交互采集（单击预览 / 双击确认 / 右键取消）
python skill-scripts/wx_points.py show
python skill-scripts/wx_points.py capture
python skill-scripts/wx_points.py capture --point search_box

# 打开联系人聊天（自动完成：检测登录→初始化窗口→搜索→点联系人→点输入框）
python skill-scripts/wx_open_chat.py --contact 张三

# 发消息（文字或文件，自动打开聊天窗口）
python skill-scripts/wx_send.py --contact 张三 --text "你好"
python skill-scripts/wx_send.py --contact 张三 --file "C:/path/file.csv"

# 发送 + 数据库验证（发送后轮询本地库确认消息已入库）
python skill-scripts/wx_send_verify.py --contact 张三 --content "验证内容"

# 本地数据库提取 / 查询
python skill-scripts/wx_extract.py --wxid wxid_xxx --date-from 2025-01-01 --date-to 2025-12-31
python skill-scripts/wx_query.py --contact 张三 --date-from 2025-01-01 --date-to 2025-12-31
```

**窗口模式**（`--window`）：Deskflow / 键鼠切到别的机器时也稳定，消息直达微信窗口，不依赖系统焦点。
`wx_open_chat` / `wx_send` / `wx_send_verify` 默认已是窗口级，系统级需显式 `--system`。

## 模块直达（库调用方式）

```python
import sys, os
REPO = r"<SKILL_DIR>"
for p in (f"{REPO}/my_automation", f"{REPO}/my_tools", f"{REPO}/src"):
    sys.path.insert(0, p)

import wechat_status as ws          # 状态 / 窗口 / 主窗口识别 / 嵌入页检测
import points                       # 点位存取 + 交互采集
import wechat_input as wi           # 点击 / 打字 / 粘贴 / 清空
import sender                       # 粘贴式发送（文本/文件）+ 回车
import tasks                        # 组合任务：打开聊天 / 发送与验证
from my_tools.extract import run_extract
from my_tools.query import run_query
```

## 组合方法（核心）

| 方法 | 做了什么 | 返回 |
|---|---|---|
| `tasks.open_contact_chat(contact)` | 检测登录→初始化窗口→清空并输入搜索→点第一联系人→校验(宽度/嵌入页/独立窗口)→点聊天输入框 | `{ok, code, message}` |
| `tasks.send_and_verify(contact, content)` | 打开聊天→粘贴+回车→轮询本地库验证（最多12次每秒1次，微信 checkpoint 约8~10s） | `{ok, code, message}` |
| `wechat_status.init_wechat_window()` | 若内嵌搜一搜页先点点位4关闭→关闭多余窗口/AppEx→前置→左半屏→校验(降级不阻塞) | `{ok, code, message}` |

完整参数签名见 `references/api.md`。

## 失败处理约定

所有方法返回 `{"ok": bool, "code": str, "message": str}`。**失败时不得静默**，必须把 `message` 原样上报。

错误码全表见 `references/error-codes.md`。

特别注意 `ERR_SEND_UNVERIFIED`：它表示**读库验证失败**，不等于消息没发出去（可能已发送但密钥失效/未 checkpoint）。此时如实报告，不要重发。

## 密钥失效时重新获取（`ERR_NO_KEYS` / `ERR_SEND_UNVERIFIED`）

**症状**：`无密钥，无法解密 <xxx.db>`；`resolve_key_for()` 返回 `None`。

**原因**：`.wechat_exp_config.json` 里的 `db_keys` / `db_keys_by_salt` 与当前库的 salt 对不上（微信升级、切账号、库重建都会变）。

**前提**：微信必须运行且已登录（密钥缓存在进程内存），不需要管理员权限。

```bash
# 1. 确认当前 db_storage 路径（取 data_dirs[].db_path）
python "<SKILL_DIR>/skill-scripts/wx_status.py"

# 2. 重新提取（自动四级降级：配置加载 → MMKV → API Hook → 内存扫描）
python "<SKILL_DIR>/src/main.py" export --mode keys --db-dir "D:\xwechat_files\wxid_xxx_ccb3\db_storage"

# 3. 验证（返回 64 位 hex = 成功，None = 失败）
python -c "import sys; sys.path.insert(0,'<SKILL_DIR>/src'); from backup.decryptor import resolve_key_for; print(resolve_key_for(r'D:\xwechat_files\wxid_xxx_ccb3\db_storage\message\message_0.db'))"
```

写入是 **merge 语义**（`engine/config_file.set_db_keys`），旧密钥不会丢。

常见失败：打不开进程（微信未运行/权限不足）、多个 `MISSING`（冷分片未加载，先点开对应聊天）、多账号需分别执行。

## 详细参考

| 文件 | 内容 | 何时读 |
|---|---|---|
| `references/api.md` | 模块地图、方法签名、AI 自动回复、窗口模式 | 需要调库或看参数细节 |
| `references/error-codes.md` | 错误码全表 | 遇到 `ERR_*` |
| `references/pitfalls.md` | 20 条防坑记录 | 遇到点击 / 发送 / 窗口异常时必读，尤其第 20 条 Deskflow 铁律 |

## 使用约定

1. 优先调用 `skill-scripts/`、`my_tools/`、`my_automation/` 的现成能力，不要动源码
2. 多账号环境：先 `wx_status` 查 wxid，需定位具体账号时用 `--wxid` 指定
3. 发消息前先确认联系人名称，对不确定的名字先 `wx_query` 核对后再发
4. `points.json`（点位坐标）与 `.wechat_exp_config.json`（解密密钥）是本机敏感配置，不外传、不写入任何输出
