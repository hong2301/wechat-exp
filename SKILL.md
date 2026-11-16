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
│   └── pitfalls.md         # 24 条防坑记录
├── skill-scripts/          # 命令行入口
├── my_automation/          # 微信客户端自动化（发消息 / 监控 / 自动回复）
├── my_tools/               # 本地数据库读写
├── ai/                     # GLM 调用（自动回复用）
├── src/                    # 解密与数据服务
└── .wechat_exp_config.json # 本机数据库密钥
```

脚本用绝对路径调用：

```bash
python "<SKILL_DIR>/skill-scripts/wx_status.py"
```

## 环境依赖

第三方包（缺失时不会报错，而是**静默返回空数据**，极易误判）：

| 包 | 用途 | 缺失后果 |
|---|---|---|
| `pycryptodome` | SQLCipher 解密（AES-256-CBC） | 数据库完全无法解密 |
| `zstandard` | 解压微信 4.x 的 zstd 消息内容 | **消息内容全为空**，会造成“消息没发出去”的误判 |
| `openpyxl` | 导出 xlsx / html | 仅导出类功能失败 |
| `jieba` | 词云分词 | 仅词云失败 |
| `flask` | Web 查看器 | 仅 Web 失败 |

窗口自动化走 `ctypes` 直接调 Win32 API，**不需要 pywin32**。

```bash
pip install -r "<SKILL_DIR>/requirements.txt"

# 自检（跑任何脚本前建议先执行）
python -c "import Crypto, zstandard; print('核心依赖 OK')"
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

# 打开联系人聊天（搜索 → 输入 → **回车**；回车后焦点已在输入框）
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
import monitor                      # 新消息监控（只读轮询本地库）
import auto_reply                   # 监控 + GLM 上下文 + 自动发送
from my_tools.extract import run_extract
from my_tools.query import run_query
```

## 组合方法（核心）

| 方法 | 做了什么 | 返回 |
|---|---|---|
| `tasks.open_contact_chat(contact)` | 检测登录→初始化窗口→清空并输入搜索→点第一联系人→校验(宽度/嵌入页/独立窗口)→点聊天输入框 | `{ok, code, message}` |
| `tasks.send_and_verify(contact, content)` | 打开聊天→粘贴+回车→轮询本地库验证（最多12次每秒1次，微信 checkpoint 约8~10s） | `{ok, code, message}` |
| `wechat_status.init_wechat_window()` | 若内嵌搜一搜页先点点位4关闭→关闭多余窗口/AppEx→前置→左半屏→校验(降级不阻塞) | `{ok, code, message}` |

## 监控与自动回复（可选）

```python
import monitor
mon = monitor.MessageMonitor()        # 缺省挂当前登录账号的库
mon.poll_once()                       # 本轮新消息
mon.load_history_for(sender_id, 10)   # 某人的最近历史（AI 上下文）

import auto_reply
auto_reply.auto_reply(only_contact="张三", dry_run=True, run_seconds=60)
```

只回复**对方发的文本消息**；发送者必须能解析成真实 wxid 且能在会话表里找到可搜索身份，
否则直接跳过（防误发给同名的人）。`one_shot=True` 时同一人回一条即停。

```bash
python "<SKILL_DIR>/my_automation/monitor.py" --seconds 60
python "<SKILL_DIR>/my_automation/auto_reply.py" --dry-run --seconds 60
```

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

## 微信 4.x 关键行为（必读，踩过的坑）

这五条决定了整套窗口级自动化能不能跑通，改代码前先看：

1. **PostMessage 的 Enter 不触发发送**。窗口级 `PostMessage(WM_KEYDOWN)` 投递的回车，
   微信 4.x 要么忽略（文字留在输入框变成「草稿」），要么在搜索框里变成「搜一搜」。
   必须用 **同步 `SendMessage`** 的击键流 —— 已封装成 `wechat_input.post_enter()`，
   发送和「回车打开联系人」都走它。`post_key()` 只用于方向键 / Esc。
2. **搜索结果是独立的 Qt 弹层窗口**（类名含 `QWindowToolSaveBits`，标题 `Weixin`）。
   它不属于主窗口，**发往主窗口的点击它收不到**。需要点击时把 `hwnd` 传给
   `wechat_input.post_click(x, y, hwnd=panel)`；判断它是否存在用
   `wechat_status.get_search_panel()`。
3. **回车打开联系人后，焦点自动落在聊天输入框**，所以发消息前**不需要**再点输入框，
   点位 `chat_input` 是可选项（只在“未经 open_contact_chat 直接发送”时作容错）。
4. **不要前置 / 不要动真实鼠标**。全部用 `PostMessage` / `SendMessage`，
   `init_wechat_window()` 用 `SW_SHOWNOACTIVATE` 唤出窗口，不抢焦点。
   这样 Deskflow 切到别的机器时也能稳定发送。
5. **找不到联系人的判据**：回车后如果出现**新的微信可见窗口**
   （搜一搜 / 添加朋友），就是这个查询词没匹配到联系人 → `ERR_CONTACT_NOT_FOUND`。
   搜索弹层自己收起**不算**新窗口。

### 标准发送流程（窗口级）

```
init_wechat_window()           # 左半屏、不前置
→ 点 search_box + 清空
→ post_text(联系人名)          # SendMessage 击键，支持中文
→ post_enter()                 # 回车打开第一项联系人，焦点落到输入框
→ 校验：有无新窗口（有=没找到人）
→ post_text(消息内容)
→ post_enter()                 # 发送
→ 读库验证（send_and_verify）  # 约 8~10s 后 checkpoint 落库
```

### 点位清单

| 点位 | 必需 | 用途 |
|---|---|---|
| `search_box` | ✅ | 点搜索框并清空 |
| `search_split_button` | ✅ | 内嵌搜一搜页时点它分离/关闭 |
| `file_button` | ✅ | 发文件时点「文件夹」图标 |
| `chat_input` | 可选 | 回车后焦点已在输入框，一般不需要 |

点位是**屏幕绝对坐标**，采集时的窗口布局必须和运行时的布局一致：
运行时会 `init_wechat_window()` 把窗口摆成左半屏（工作区一半宽），所以**采点前先初始化一次窗口**。

## 详细参考

| 文件 | 内容 | 何时读 |
|---|---|---|
| `references/api.md` | 模块地图、方法签名、AI 自动回复、窗口模式 | 需要调库或看参数细节 |
| `references/error-codes.md` | 错误码全表 | 遇到 `ERR_*` |
| `references/pitfalls.md` | 24 条防坑记录 | 遇到点击 / 发送 / 窗口异常时必读；第 20 条 Deskflow 铁律、第 21~24 条微信 4.x 行为 |

## 使用约定

1. 优先调用 `skill-scripts/`、`my_tools/`、`my_automation/` 的现成能力，不要动源码
2. 多账号环境：先 `wx_status` 查 wxid，需定位具体账号时用 `--wxid` 指定
3. 发消息前先确认联系人名称，对不确定的名字先 `wx_query` 核对后再发
4. `points.json`（点位坐标）与 `.wechat_exp_config.json`（解密密钥）是本机敏感配置，不外传、不写入任何输出
5. **发送验证失败先查密钥**：`ERR_SEND_UNVERIFIED` 里夹着「无密钥，无法解密」时，
   不是没发出去，而是密钥过期了（微信升级/切账号会变）。按上文「密钥失效」重新提取，
   并用 `wx_send_verify` 再发一条确认真能落库。
6. 回复用户时不要重建自己的确认步骤：技能返回 `ok=false` 时把 `message` 原样报出来，
   不要笼统说“发送失败”。
