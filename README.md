# 微信数据（WeChat Data）

本机微信的读写技能：**读**本地聊天数据库，**写**微信客户端（发文字/文件、自动回复）。
全程走 Windows 窗口消息（`PostMessage` / `SendMessage`），**不前置窗口、不动真实鼠标键盘**，
所以 Deskflow 切到别的机器时也能正常发。

## 你可以这样跟 agent 说

```text
给泰运长临发条消息：明天下午三点开会。
看看我和「五和」最近的聊天记录，导出成表格。
微信现在是登录状态吗？窗口有没有被别的页面占掉？
新人加我微信没？没加上就发条消息问一下。
```

## 三个域

| 目录 | 能力 |
|---|---|
| `my_tools/` | **读**：数据库解密 → 导出 / 按联系人和时间段查询 |
| `my_automation/` | **写**：登录检测、窗口初始化、点位管理、打开聊天、发消息、发送后读库验证、新消息监控、AI 自动回复 |
| `ai/` | GLM 调用（自动回复用，密钥在 `config.json`，已 gitignore） |
| `src/` | 底层：SQLCipher 解密、zstd 解压、密钥提取 |

命令行入口在 `skill-scripts/`，每个都是薄壳：

```bash
python skill-scripts/wx_status.py                 # 运行/登录/窗口状态
python skill-scripts/wx_init_window.py            # 窗口就位左半屏（不前置）
python skill-scripts/wx_points.py show|capture    # 点位查看 / 交互采集
python skill-scripts/wx_open_chat.py --contact 张三
python skill-scripts/wx_send.py --contact 张三 --text "你好"
python skill-scripts/wx_send_verify.py --contact 张三 --content "你好"   # 发送 + 读库验证
python skill-scripts/wx_query.py --contact 张三 --date-from 2025-01-01 --date-to 2025-12-31
```

监控与自动回复直接调模块（没有薄壳）：

```bash
python my_automation/monitor.py --seconds 60              # 只监控新消息
python my_automation/auto_reply.py --dry-run --seconds 60 # 只生成回复不发送
```

## 前置条件

- 微信 PC 版（Weixin.exe）**运行且已登录**
- 系统 Python 装好依赖：

```bash
pip install -r requirements.txt     # pycryptodome / zstandard / openpyxl / jieba / flask
python -c "import Crypto, zstandard; print('核心依赖 OK')"
```

- 点位已采集（`my_automation/points.json`）：搜索框、搜一搜分离按钮、文件按钮。
  换屏幕分辨率 / 改微信窗口布局后必须重新采：

```bash
python my_automation/points.py capture
```

采集时的窗口布局要和运行一致 —— 先跑一次 `wx_init_window.py`（窗口会摆到左半屏）再采。

## 微信 4.x 的四个坑（改代码前必看）

1. **`PostMessage` 的 Enter 不发送**：文字只会变成草稿。必须用同步 `SendMessage`
   （已封装为 `wechat_input.post_enter()`）。
2. **搜索结果在独立的 Qt 弹层窗口里**（类名 `QWindowToolSaveBits`），主窗口收不到对它的点击。
3. **回车打开联系人后焦点自动在输入框**，不需要再点输入框。
4. **找不到联系人的信号**：回车后冒出新的微信窗口（搜一搜/添加朋友）＝这个名字没匹配到人。

## 发送验证失败先看是不是密钥问题

`ERR_SEND_UNVERIFIED` 的 message 里如果出现「无密钥，无法解密」，说明**不是没发出去**，
而是解密密钥跟当前库对不上（微信升级、切账号、库重建都会变）。重新提取即可：

```bash
python src/main.py export --mode keys --db-dir "D:\xwechat_files\wxid_xxx_ccb3\db_storage"
```

## 注意

- `points.json`（点位）和 `.wechat_exp_config.json`（解密密钥）是本机敏感配置，已 gitignore，
  不要外传、不要贴进任何输出。
- 发消息是真实操作，测试请用自己的号 / 「文件传输助手」，不要随手发给真实联系人。
