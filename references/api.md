# API 参考：模块地图与方法签名

> `SKILL.md` 的详细参考，按需查阅。**最后核对：2026-11-16（微信 4.x 实测版）**。
> 改实现时顺手核对本文件，尤其是「方法签名」与「错误码」两处。

## 1. 架构总览

`wechat-exp/` 本身就是一份完整技能包（git 仓库 = 真源，技能目录是部署副本）：

```
wechat-exp/
├── SKILL.md            技能入口（只写「怎么用」，不写开发流程）
├── README.md           仓库说明
├── references/         渐进式披露的参考 —— 本文件所在
│   ├── api.md              模块地图 / 方法签名（本文件）
│   ├── error-codes.md      错误码全表
│   └── pitfalls.md         实战防坑记录
├── skill-scripts/      8 个 CLI 薄壳，只做参数解析 + 调库
│   ├── wx_status.py        运行 / 登录 / 窗口状态
│   ├── wx_init_window.py   窗口摆到左半屏（不前置）
│   ├── wx_points.py        点位查看 / 交互采集
│   ├── wx_extract.py       解密导出（调 my_tools.extract）
│   ├── wx_query.py         按联系人+时间段查询（调 my_tools.query）
│   ├── wx_open_chat.py     打开联系人聊天
│   ├── wx_send.py          发文字 / 发文件
│   └── wx_send_verify.py   发送 + 读库验证
├── my_tools/       【读】本地数据库域
│   ├── extract.py          功能一：数据库 → 解密后的本地库 + 索引 chats.db
│   ├── query.py            功能二：联系人 + 时间段 → 完整聊天数据
│   ├── checker.py          检测模块（预设错误返回）
│   ├── config.py           集中配置 + 错误码定义 EC
│   └── README.md
├── my_automation/  【写】自动化操作域
│   ├── wechat_status.py    状态 / 窗口识别 / 嵌入页 / 搜索弹层 / 窗口初始化
│   ├── points.py           点位（JSON 存储 + 交互采集）
│   ├── wechat_input.py     点击 / 打字 / 粘贴 / 清空 / 回车（系统级 + 窗口级）
│   ├── sender.py           文本与文件发送（窗口级默认）
│   ├── tasks.py            组合任务（打开聊天、发送并验证、失败收尾）
│   ├── monitor.py          新消息监控（读库轮询）
│   ├── auto_reply.py       监控 + GLM 生成 + 自动发送
│   ├── pi_mesh.py          向本机 Pi 会话的 broker 管道投递消息
│   └── README.md
├── ai/             GLM 调用封装（ask / chat，密钥在 config.json）
└── src/            上游 WeChat EXP（只读依赖，不主动改）
    ├── backup/     scanner / decryptor / migrator / indexer / pipeline
    ├── engine/     decrypt / config_file / services/*（chat/message/media/...）
    ├── web/        Flask 查看器（技能不需要，部署时排除）
    └── main.py     CLI 入口（export --mode keys 等）
```

**两个数据流**

```
读：src/backup.decryptor.resolve_key_for → decrypt_database → my_tools.query（联系人+时间）
写：my_automation.wechat_status.init_wechat_window → wechat_input.post_* → sender → tasks 校验
```

**调用前提**：`sys.path` 需含 `REPO/my_automation`、`REPO/my_tools`、`REPO/src`。
`skill-scripts/*.py` 已内置；库调用需自行 insert。

```python
import sys
REPO = r"<SKILL_DIR>"
for p in (f"{REPO}/my_automation", f"{REPO}/my_tools", f"{REPO}/src"):
    sys.path.insert(0, p)
```

---

## 2. my_tools —— 本地数据库域（读）

### 2.1 extract.py — 功能一：提取

**CLI**：`python my_tools/extract.py [--db-dir 路径] [--wxid 账号] [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD] [-o 输出目录]`

```python
from my_tools.extract import run_extract
result = run_extract(db_dir=...,        # 微信数据库路径(db_storage 或账号根目录)，缺省自动检测
                     wxid=...,          # 多账号时指定
                     date_from="2025-01-01", date_to="2025-12-31",
                     output_dir=...)    # 输出目录（默认 my_output/backup）
# result = {"ok": bool, "code": str, "message": str,
#           "data": {"output_dir", "stats"}}
# stats: {decrypted, migrated, v2_keys_harvested, indexed(chats.db 路径)}
```

- 流程：扫描 → 密钥提取（内存 / 配置）→ 解密 → 媒体迁移 → 建索引
- 密钥：首次自动从微信进程内存提取并写入 `.wechat_exp_config.json`（merge 语义，旧密钥不丢）
- **目标账号必须是当前登录账号**（密钥缓存在进程内存里）

### 2.2 query.py — 功能二：查询

**CLI**：`python my_tools/query.py --contact 张三 [--date-from] [--date-to] [--decrypted-dir 目录] [--format json|txt|html] [-o 输出目录]`

```python
from my_tools.query import run_query
result = run_query(contact,            # 显示名 / 备注 / 微信号，支持模糊匹配
                   date_from=..., date_to=...,
                   decrypted_dir=...,  # 已解密数据目录（缺省自动定位最近备份）
                   fmt="json", out_dir=...)
# data.results = [{contact, username, is_group, date_from, date_to,
#                  message_count, messages:[{local_id, time, timestamp, sender,
#                                            side, type, type_name, content, status}]}]
```

- 消息字段：`time`(格式串) `timestamp`(秒) `sender`(显示名 / 我 / 系统消息)
  `side`(me/other/system/unknown) `type`(微信类型码) `type_name`(中文) `content`(解析后)
- 使用前需先 `extract` 得到解密目录，否则 `ERR_NO_DECRYPTED_DIR`

### 2.3 checker.py / config.py

- `config.EC` 定义读域全部错误码，`EC.label(code)` 取中文说明，
  `config.result(ok, code, message, data)` 统一返回结构
- 检测函数：`check_db_dir / check_keys / check_decrypted_dir / check_date_range / find_contact`

---

## 3. my_automation —— 自动化操作域（写）

> 默认**全链路窗口级**（`PostMessage` / `SendMessage`），不前置窗口、不动真实鼠标键盘。
> 系统级（`SetCursorPos` + `SendInput`）只在显式 `--system` 时启用 —— Deskflow 环境下会穿透到别的电脑。

### 3.1 wechat_status.py

| 方法 | 说明 | 返回 |
|---|---|---|
| `is_wechat_running()` | 进程检测（Weixin/WeChat.exe） | bool |
| `is_logged_in()` | 登录判定（数据目录锁定为主，多级降级） | bool |
| `get_data_dirs()` | 全部账号数据目录（按 wxid 去重） | list[dict] |
| `get_locked_data_dirs()` | 被微信锁定的目录（=登录账号） | dict |
| `get_active_data_dir()` | 当前使用账号目录 | str/None |
| `init_wechat_window()` | **组合**：关嵌入页 → 唯 1 主窗口 → 唤出（`SW_SHOWNOACTIVATE`，不抢焦点）→ 左半屏 → 校验（降级不阻塞） | `{ok,code,message}` |
| `get_status()` | 全状态汇总（运行 / 登录 / pids / 数据目录 / 锁定 / 窗口） | dict |
| `_find_main_hwnd(pids)` / `_select_main_hwnd(pids)` | 主窗口识别：可见 + 标题含「微信」+ **面积最大** | hwnd |
| `has_embedded_page(hwnd=None)` | 嵌入搜一搜页（主窗口内 RenderWidget 子窗口 > 0） | bool |
| `extra_visible_windows(exclude_main=True, exclude_panel=True)` | 额外可见窗口（**默认已排除搜索弹层**） | [(hwnd,title)] |
| `get_search_panel(main_hwnd=None)` | 搜索下拉弹层 hwnd（类名含 `QWindowToolSaveBits`，标题 `Weixin`） | hwnd/None |
| `is_search_panel(hwnd)` | 判断某 hwnd 是否为搜索弹层 | bool |
| `get_window_width(hwnd=None)` | 主窗口宽度（**不要再当「找到联系人」判据**） | int |

登录判定优先级：未运行→False；锁定探测成功（句柄归属）→有锁定=True；降级→登录窗/主窗口启发式。

### 3.2 points.py — 点位

点位清单（`points.json`，**已 gitignore**）：

| name | 必需 | 用途 |
|---|---|---|
| `search_box` | ✅ | 点搜索框并清空 |
| `search_split_button` | ✅ | 内嵌搜一搜页时点它分离/关闭 |
| `file_button` | ✅ | 发文件时点「文件夹」图标 |
| `chat_input` | 可选 | 回车后焦点已在输入框，一般不需要（仅异常路径兜底） |

| 方法 | 说明 |
|---|---|
| `load_points() / get_points()` | 全部点位 dict |
| `get_point(name)` | 单点位 `{x,y}` / None |
| `save_points(points)` / `clear_points()` | 保存 / 清空 |
| `capture_all()` | 依次采集全部点位 |
| `capture_one(prompt=None)` / `capture_one_point(name)` | 采单个点位并合并保存 |
| `POINT_NAMES` | 点位名 → 中文说明映射 |

**CLI**：`python my_automation/points.py show | capture [--point NAME] | clear`
**交互规则**：左键单击=记录预览；左键双击=确认（取第一次按下坐标）；右键=取消全部。
采集用 `GetAsyncKeyState` + `GetCursorPos` 轮询（低层鼠标钩子在本环境不可靠）。

### 3.3 wechat_input.py

**系统级（需鼠标键盘在本机）**

| 方法 | 说明 |
|---|---|
| `mouse_click(x, y, hold_ms=80, wait_after=0)` | 左键点击（`SetCursorPos` + `mouse_event`） |
| `type_text(text, char_delay=0.01)` | `SendInput` UNICODE 逐字符（支持中文） |
| `paste_text(text)` | 写剪贴板 + Ctrl+V |
| `ctrl_key(letter)` / `key_press(vk)` | 组合键 / 单键 |
| `clear_input()` | Ctrl+A + Delete |
| `set_clipboard_text(text)` / `mark_clipboard_private()` | 写剪贴板 / 标记不进 Win+V 历史 |
| `release_modifiers()` | 兜底释放 Ctrl/Shift/Alt/Win（注入被中断也不卡键） |

**窗口级（Deskflow 场景核心，默认路径）**

| 方法 | 说明 |
|---|---|
| `post_click(x, y, hwnd=None)` | 窗口内点击：屏幕坐标 → 客户区 → `PostMessage`；点后补 `WM_SETFOCUS`（Chromium 编辑框必需）。**点弹层必须传 `hwnd=panel`** |
| `post_text(text, hwnd=None, char_delay=0.02)` | 同步击键输入（KEYDOWN + CHAR + KEYUP，支持中文） |
| `post_enter(hwnd=None)` | **同步 `SendMessage` 回车**（4.x 只认这个；`post_key(VK_RETURN)` 会变草稿/搜一搜） |
| `post_key(vk, hwnd=None, wait=0.06)` | 窗口内按键 —— 只给方向键 / Esc 用 |
| `post_clear(hwnd=None, max_backspaces=60)` | 清空输入框（End + Backspace×N；Ctrl+A 在 Qt/Chromium 不可靠） |
| `adapt_client_pt / adapt_screen_pt` | 点位等比自适应换算（基准尺寸 → 当前窗口） |

**CLI**：`python my_automation/wechat_input.py --click X Y | --type 文本 | --paste 文本`

### 3.4 sender.py — 消息与文件发送

**文本**

| 方法 | 通道 | 说明 |
|---|---|---|
| `send_text_window(text, hwnd=None)` | 窗口级 ✅ | 清空输入框 → `post_text` → **`post_enter()`** |
| `paste_text_to_chat(text)` | 窗口级 | 粘贴到输入框（不发送） |
| `send_message(content, send=True)` | 系统级 | str=文本 / 路径 list=文件；`send=True` 回车发送 |

**文件：两条通道（重要）**

| 通道 | 实现 | 剪贴板 | Deskflow | 其它电脑 |
|---|---|---|---|---|
| **窗口级（默认）** | `send_file_via_picker(path, hwnd=None, wait_picker=5.0)`：点 `file_button` → 等「选择文件」对话框（`#32770`）→ 找路径栏 `Edit id=1148` → **WM_SETTEXT + 读回校验（3 次重试）** → 找 `Button id=1「打开(&O)」` → **BM_CLICK** → 回车发送 | ❌ 不碰 | ✅ 可用 | ✅ 无影响 |
| 系统级（`--system`） | `paste_files_to_chat(paths)` / `send_message(paths)`：CF_HDROP 写剪贴板 + 系统 Ctrl+V | ✅ 占用（用完还原） | ❌ 失效 | ⚠️ 会同步过去 |

**CLI**：`python my_automation/sender.py --text 文本 | --file 路径... | --send-msg 内容`

### 3.5 tasks.py — 组合任务（核心）

#### `open_contact_chat(contact, use_paste=False, wait_search=0.8, clear_first=True, window_mode=True)`

流程（微信 4.x，2026-11 实测版）：

1. 参数校验（contact 非空）→ `ERR_NO_CONTACT`
2. `is_logged_in()` 失败 → `ERR_NOT_LOGGED_IN`
3. `init_wechat_window()`（左半屏、不前置）失败 → `ERR_WINDOW_INIT`
4. `_clear_search_box()`：点 `search_box` + 清空（窗口级 End + 退格流）
5. `post_text(contact)` 输入 → `_wait_search_panel()` 等弹层出现；
   等不到（焦点丢了）就清空重输一次
6. 记 `wins_before = _visible_wechat_hwnds()` → **`post_enter()`** 回车打开第一项
   （回车后焦点自动落在聊天输入框）
7. `_check_contact_result(wins_before)`：出现**新的**微信可见窗口（搜一搜 / 添加朋友）
   → `ERR_CONTACT_NOT_FOUND`；弹层自己收起不算新窗口
8. 失败收尾 `_cleanup_contact_fail()`：独立窗口 `WM_CLOSE`；嵌入页先点 `search_split_button` 再关
9. 完成 —— **不再点击输入框**（`chat_input` 已降级为可选）

#### `send_and_verify(contact, content, use_paste=False, wait_search=0.8, verify_backoff=15, save_sql=5, window_mode=True)`

流程：`open_contact_chat` → `send_text_window`（窗口级发送）→ **轮询验证**：

- 每秒 1 次解密 `message_0.db` 扫描，最多 12 次
- 查询窗口起点 `send_time - (5+attempt)`（前 5 → 前 10 …），终点 `send_time + 5`
- 匹配条件：时间在窗口内 + 内容存在于解压后的 `message_content`
- 命中 → `OK`（附耗时/次数）；12 次未中 → `ERR_SEND_UNVERIFIED`

⚠️ WAL checkpoint 约 5~10s，读库总是滞后，故必须轮询而非一次性等待。
`ERR_SEND_UNVERIFIED` **不等于没发出去**，只代表无法确认；此时如实上报，不要重发。

#### 辅助方法

| 方法 | 说明 |
|---|---|
| `_visible_wechat_hwnds()` | `{hwnd: title}`，回车前后对比用 |
| `_check_contact_result(wins_before=None)` | 判据只有一条：有没有出现新的可见窗口 |
| `_wait_search_panel(main_hwnd, timeout=2.0)` | 等搜索弹层出现，返回 hwnd / None |
| `_clear_search_box(window_mode=False)` | 点搜索框 + 清空 |
| `_cleanup_contact_fail(window_mode=False)` | 失败收尾，返回日志行 list |
| `_step_ok / _step_fail` | 统一 `{ok, code, message}` 构造 |

### 3.6 monitor.py — 新消息监控（只读）

```python
from monitor import MessageMonitor, watch
mon = MessageMonitor()            # db_storage 缺省取 get_active_data_dir()
mon.poll_once()                   # 本轮新消息 list[dict]（窗口内、去重）
mon.watch(interval=1.0, on_message=None, run_seconds=None, stop_event=None)
watch(interval=1.0, on_message=None, run_seconds=None, stop_event=None, db_storage=None)
```

| 成员 / 方法 | 说明 |
|---|---|
| `wal_changed()` | `(changed, wal_size)`：WAL 变大=有消息但还没 checkpoint 进主库 |
| `baseline()` | 清空去重集合，从当前起点开始（不预上报历史） |
| `poll_once()` | 轮询一次，返回新消息；按 `server_id`（无则 `local_id`）去重 |
| `load_history_for(sender_id, limit=10, before_ts=None)` | 某发送者的最近历史（升序），AI 上下文数据源 |
| `search_messages(keyword, limit=5)` | 关键词检索（AI 参考用） |
| `window_seconds` | 扫描窗口（默认最近 600s） |
| `stats` | `{scans, new_messages, errors}` |

消息 dict 字段：`time / side(对方|我) / type / type_name / content / sender_id / msg_id` 等。

**CLI**：`python my_automation/monitor.py [--seconds N] [--interval S]`

### 3.7 auto_reply.py — AI 自动回复

```python
from auto_reply import auto_reply
auto_reply(interval=1.0, only_contact=None, window_mode=True,
           cooldown=60, system_prompt=DEFAULT_SYSTEM,
           run_seconds=None, stop_event=None, dry_run=False,
           history_limit=10, extra_contacts=None,
           max_msg_chars=300, max_context_chars=4000,
           search_keywords=None, one_shot=True)
# → {"ok", "code", "message", "stats"?}
```

- 只回复**对方**发的**文本**消息（type=1）
- 安全阀：`sender_id` 必须解析成真实 wxid，且 `resolve_open_target()` 能找到可搜索身份，
  否则跳过（避免误发给同名的人）
- `_build_context()`：多轮 messages（对方=user，我方=assistant；`extra_contacts` 以 system 注入参考）
- `_generate_reply_ctx()`：带上下文调 `ai.chat(messages)`
- `one_shot=True`：同一发送者回复一条即停；已回复消息持久化在 `auto_reply_state.json`（已 gitignore）
- `cooldown`：同一联系人冷却秒数

```bash
python my_automation/auto_reply.py --dry-run --seconds 60           # 只生成不发送
python my_automation/auto_reply.py --seconds 3600 --only 关键词      # 持续自动回复
python my_automation/auto_reply.py --extra wxid_a --extra wxid_b     # 附加上下文联系人
```

### 3.8 pi_mesh.py — 向 Pi 会话投递消息

```python
from pi_mesh import send, list_peers
send(text, target, name='voice', cwd=None, body_type='voice',
     timeout=3.0, wait_ack=True)     # → {"ok","code","message","address","ack"}
list_peers(timeout=2.0)              # 当前 broker 上的 peer 列表
```

pipe：`\\.\pipe\remote-pi-broker-local-<USERNAME>`（remote-pi v0.5 协议，JSONL）。
失败码：`ERR_EMPTY` / `ERR_NO_TARGET`（地址须为 `<cwd>@<name>`）/ `ERR_NO_BROKER`。

**CLI**：`python my_automation/pi_mesh.py "文本" [--target 地址] [--name 发送者名]`

---

## 4. ai/ — GLM 调用

```python
import ai
ai.ask(prompt, provider='glm')            # 单轮
ai.chat(messages, provider='glm')         # 多轮（支持 system / assistant）
```

- 密钥：`config.json` 的 `GLM_API_KEYS`（**已 gitignore，不入库**）
- 错误分类 + 自动重试：quota / rate_limit / network / server / auth
- 依赖：`requests`（缺了也不会崩，只会在自动回复时报错）

---

## 5. 调用约定

1. **返回结构统一**：`{"ok": bool, "code": str, "message": str, "data"?: any}`，
   失败时 `message` 必须原样上报，不要改写成「失败了」。
2. **`window_mode` 默认 True**（窗口级）。`skill-scripts` 里系统级要显式 `--system`。
   `--window` 参数保留仅为兼容旧命令，**默认已是窗口级**。
3. **点位是屏幕绝对坐标**，与采集时的窗口布局绑定；运行时先 `init_wechat_window()`
   摆成左半屏，所以**采点前也要先初始化一次窗口**。
4. 读库类接口都依赖「微信运行 + 密钥可用」；`ERR_NO_KEYS` 先按
   `SKILL.md`「密钥失效时重新获取」处理。
