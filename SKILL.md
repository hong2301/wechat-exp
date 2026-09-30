---
name: wechat-data
description: 微信数据技能。处理本机微信的业务：读取/导出本地聊天数据库（按联系人、时间段查询），自动化操作微信客户端（登录检测、窗口初始化、点位管理、打开联系人聊天、发送文字/文件、发送后入数据库验证）。处理微信聊天记录读写时使用。
license: proprietary
metadata:
  repo: https://github.com/hong2301/wechat-exp
  base: C:/Users/86150/Desktop/微信数据/wechat-exp
---

# 微信数据（WeChat Data）

本技能封装了两个能力域（详见 `skill-refs/INDEX.md` 的完整索引）：

- **读** `my_tools/`：微信本地数据库提取与查询
- **写** `my_automation/`：微信客户端自动化（检测登录 / 窗口初始化 / 点位 / 打开聊天 / 发消息 / 发送验证）

## 仓库位置

`C:/Users/86150/Desktop/微信数据/wechat-exp`（下文用 `REPO` 指代）。
所有脚本用绝对路径调用，仓库路径变更时同步修改脚本与本文档。

## 快速开始（脚本方式）

```bash
cd REPO

# 微信状态（运行 / 登录 / 占用账号 / 窗口）
python skill-scripts/wx_status.py

# 窗口初始化：自动关闭嵌入搜一搜页 → 唯一主窗口前置 → 左半屏
python skill-scripts/wx_init_window.py

# 点位：查看 / 交互采集（单击预览 / 双击确认 / 右键取消）
python skill-scripts/wx_points.py show
python skill-scripts/wx_points.py capture              # 全部 4 个点位
python skill-scripts/wx_points.py capture --point search_box

# 打开联系人聊天窗口（自动完成：检测登录→初始化窗口→搜索→点联系人→点输入框）
python skill-scripts/wx_open_chat.py --contact 张三

# 发消息（文字或文件，自动打开聊天窗口）
python skill-scripts/wx_send.py --contact 张三 --text "你好"
python skill-scripts/wx_send.py --contact 张三 --file "C:/path/file.csv"

# 发送 + 数据库验证（发送后轮询本地库确认消息已入库）
python skill-scripts/wx_send_verify.py --contact 张三 --content "验证内容"

# 🔑 窗口模式（Deskflow/键鼠切走也稳定）：全部消息直达微信窗口，不依赖系统焦点
python skill-scripts/wx_open_chat.py --contact 张三 --window
python skill-scripts/wx_send.py --contact 张三 --text "你好" --window
python skill-scripts/wx_send_verify.py --contact 张三 --content "验证内容" --window

# 本地数据库提取 / 查询（my_tools 能力）
python skill-scripts/wx_extract.py --wxid wxid_xxx --date-from 2025-01-01 --date-to 2025-12-31
python skill-scripts/wx_query.py --contact 张三 --date-from 2025-01-01 --date-to 2025-12-31
```

## 模块直达（库调用方式）

```python
import sys; sys.path.insert(0, f"REPO/my_automation"); sys.path.insert(0, f"REPO/my_tools"); sys.path.insert(0, f"REPO/src")

import wechat_status as ws          # 状态 / 窗口 / 主窗口识别 / 嵌入页检测
import points                       # 点位存取 + 交互采集
import wechat_input as wi           # 点击 / 打字 / 粘贴 / 清空
import sender                       # 剪贴板借用式粘贴（文本/文件）+ 回车发送
import tasks                        # 组合任务：打开聊天 / 发送与验证
from my_tools.extract import run_extract
from my_tools.query import run_query
```

## 组合方法（重点，详见 INDEX.md）

| 方法 | 做了什么 | 返回 |
|---|---|---|
| `tasks.open_contact_chat(contact)` | 检测登录→初始化窗口→清空并输入搜索→点第一联系人→校验(宽度/嵌入页/独立窗口)→点聊天输入框 | `{ok, code, message}` |
| `tasks.send_and_verify(contact, content)` | 打开聊天→粘贴+回车→轮询本地库验证（最多12次每秒1次，微信 checkpoint 约8~10s） | `{ok, code, message}` |
| `wechat_status.init_wechat_window()` | 若内嵌搜一搜页先点点位4关闭→关闭多余窗口/AppEx→前置→左半屏→校验(降级不阻塞) | `{ok, code, message}` |

## 失败处理约定

所有方法返回 `{"ok": bool, "code": str, "message": str}`。`code` 为预设错误码（`ERR_*`），错误码全表见 `skill-refs/INDEX.md`。失败时不得静默，必须把 message 原样上报。

## 开发边界（重要）

1. 默认**只读/检索** `my_tools/` 与 `my_automation/` 两个自定义模块
2. **不主动查看**主依赖项目：上游 `src/` 与参考项目（桌面`微信公众号ocr采集器`）；特殊情况需用户明确许可
3. `points.json`（点位坐标）与 `.wechat_exp_config.json`（解密密钥）已 gitignore，**不提交**
4. 微信数据合规：仅处理用户自己的数据

## 注意事项与经验（防坑）

- 微信数据库约 **5~10 秒才 checkpoint**，读库验证必须留足时间（`send_and_verify` 已内置轮询）
- 64 位句柄：所有 Win32 句柄 API 必须显式声明 `restype/argtypes`，否则句柄被截断
- 「搜一搜」嵌入页特征：微信主窗口出现 `Chrome_RenderWidgetHostHWND` 子窗口；关闭需先点击点位4（搜一搜窗口分离按钮）
- 主窗口识别：可见 + 标题含「微信」+ 面积最大（弹窗标题也可能是「微信」）
- 低层鼠标钩子在本环境不可靠，点位采集使用 `GetAsyncKeyState` 轮询