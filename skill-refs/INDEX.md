# 微信数据技能 · 完整索引

> REPO = `C:/Users/28910/Desktop/wechat-exp`
> 本索引是技能唯一权威参考：模块地图、方法签名、组合流程、CLI、错误码、经验教训。

---

## 1. 架构总览

```
wechat-exp/                            REPO（完整仓库）
├── my_tools/          【读】本地数据库域
│   ├── extract.py       功能一：微信数据库 → 解密形成本地数据库
│   ├── query.py         功能二：联系人 + 时间段 → 完整聊天数据
│   ├── checker.py       检测模块（预设错误返回）
│   ├── config.py        集中配置 + 错误码定义 EC
│   └── README.md
├── my_automation/     【写】自动化操作域
│   ├── wechat_status.py   状态/窗口/主窗口识别/嵌入页检测/窗口初始化
│   ├── points.py          点位（JSON 存储 + 交互采集）
│   ├── wechat_input.py    点击/打字/粘贴/清空
│   ├── sender.py          剪贴板借用式粘贴（文本/文件）+ 回车发送
│   ├── tasks.py           组合任务（打开聊天、发送与验证、收尾清理）
│   └── README.md
├── src/               上游 WeChat EXP（主依赖，只读，不主动查看）
├── SKILL.md            本技能入口
└── skill-refs/INDEX.md 本文档
```

运行前提：`sys.path` 需包含 `REPO/my_automation`、`REPO/my_tools`、`REPO/src`。
（scripts 已内置；库调用需自行 insert。）

---

## 2. my_tools —— 本地数据库域（读）

### 2.1 extract.py — 功能一：提取

**CLI**：`python my_tools/extract.py [--db-dir 路径] [--wxid 账号] [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD] [-o 输出目录]`

```python
from my_tools.extract import run_extract
result = run_extract(db_dir=...,        # 微信数据库路径(db_storage或账号根目录)，缺省自动检测
                     wxid=...,          # 多账号时指定
                     date_from="2025-01-01", date_to="2025-12-31",
                     output_dir=...)    # 输出目录（默认 my_output/backup）
# result = {"ok": bool, "code": str, "message": str, "data": {"output_dir", "stats"}}
# stats: {decrypted, migrated, v2_keys_harvested, indexed(chats.db路径)}
```

- 流程：扫描 → 密钥提取(内存/配置) → 解密 → 媒体迁移 → 索引(chats.db)
- 密钥：首次自动从微信进程内存提取并保存 `.wechat_exp_config.json`；**目标账号必须是当前登录账号**

### 2.2 query.py — 功能二：查询

**CLI**：`python my_tools/query.py --contact 张三 [--date-from] [--date-to] [--decrypted-dir 目录] [--format json|txt|html] [-o 输出目录]`

```python
from my_tools.query import run_query
result = run_query(contact,            # 显示名/备注/微信号，支持模糊匹配
                   date_from=..., date_to=...,
                   decrypted_dir=..., # 已解密数据目录（缺省自动定位最近备份）
                   fmt="json", out_dir=...)
# data.results = [{contact, username, is_group, date_from, date_to,
#                  message_count, messages:[{local_id,time,timestamp,sender,side,
#                                            type,type_name,content,status}]}]
```

- 消息字段：`time`(格式串) `timestamp`(秒) `sender`(显示名/我/系统消息) `side`(me/other/system/unknown) `type`(微信类型码) `type_name`(中文) `content`(解析后)
- 使用前需先 `extract` 得到解密目录

### 2.3 checker.py / config.py

- `config.EC` 定义全部错误码；`EC.label(code)` 取中文说明；`result(ok, code, message, data)` 统一结果
- 检测函数：`check_db_dir / check_keys / check_decrypted_dir / check_date_range / find_contact`

---

## 3. my_automation —— 自动化操作域（写）

### 3.1 wechat_status.py

| 方法 | 说明 | 返回 |
|---|---|---|
| `is_wechat_running()` | 进程检测（Weixin/WeChat.exe） | bool |
| `is_logged_in()` | 登录判定（数据目录锁定，多级降级） | bool |
| `get_data_dirs()` | 全部账号数据目录（按 wxid 去重） | list[dict] |
| `get_locked_data_dirs()` | 被微信锁定的目录（=登录账号） | dict |
| `get_active_data_dir()` | 当前使用账号目录 | str/None |
| `init_wechat_window()` | **组合**：关嵌入页→唯1主窗口→前置→左半屏→校验(降级) | `{ok,code,message}` |
| `get_status()` | 全状态汇总 | dict |
| `_find_main_hwnd/_select_main_hwnd` | 主窗口识别：可见+标题含「微信」+面积最大 | hwnd |
| `has_embedded_page()` | 嵌入搜一搜页（RenderWidget 子窗口>0） | bool |
| `extra_visible_windows()` | 额外可见窗口（非主窗口 + AppEx） | [(hwnd,title)] |
| `get_window_width()` | 主窗口宽度 | int |

登录判定优先级：未运行→False；锁定探测成功（T0 句柄归属）→有锁定=True；降级→登录窗/主窗口启发式。

### 3.2 points.py — 点位

点位清单（`points.json`，已 gitignore）：

| name | 中文 |
|---|---|
| `search_box` | 搜索框 |
| `chat_input` | 聊天输入框 |
| `search_split_button` | 搜一搜窗口分离按钮 |
| `file_button` | 文件按钮（聊天输入框工具栏）|

| 方法 | 说明 |
|---|---|
| `load_points() / get_points()` | 全部点位 dict |
| `get_point(name)` | 单点位 `{x,y}` / None |
| `save_points(points)` / `clear_points()` | 保存 / 清空 |
| `capture_all()` | 依次采集全部点位 |
| `capture_one(prompt)` / `capture_one_point(name)` | 采单个点位并合并保存 |

**CLI**：`python my_automation/points.py show | capture [--point NAME] | clear`
**交互规则**：左键单击=记录预览；左键双击=确认（取第一次按下坐标）；右键=取消全部。

### 3.3 wechat_input.py

| 方法 | 说明 |
|---|---|
| `mouse_click(x, y, hold_ms=80, wait_after=0)` | 左键点击 |
| `type_text(text, char_delay=0.01)` | SendInput UNICODE 逐字符（支持中文） |
| `paste_text(text)` | 剪贴板写入 + Ctrl+V |
| `ctrl_key(letter)` / `key_press(vk)` | 组合键 / 单键 |
| `clear_input()` | Ctrl+A + Delete 清空当前输入框 |
| `set_clipboard_text(text)` | 写剪贴板 |

**CLI**：`python my_automation/wechat_input.py --click X Y | --type 文本 | --paste 文本`

### 3.4 sender.py — 消息与文件发送

**两种文件发送通道**（重要）：

| 通道 | 实现 | 剪贴板 | Deskflow | 其他电脑 |
|---|---|---|---|---|
| **窗口级（推荐）** | `send_file_via_picker()`：点`file_button`点位 → 等「选择文件」对话框(#32770) → 轮询找路径栏 `Edit id=1148` → **WM_SETTEXT + 读回校验(3次重试)** → 轮询找 `Button id=1「打开」` → **BM_CLICK** → 回车发送 | ❌ 不碰 | ✅ 可用 | ✅ 无影响 |
| 系统级 | `send_message(path)`：CF_HDROP 写剪贴板 + 系统 Ctrl+V | ✅ 占用 | ❌ 失效 | ⚠️ Deskflow 会同步 |

### 3.4b sender.py — 剪贴板借用式发送（文本）

设计：备份当前剪贴板（文本/文件）→ 置入本次内容 → Ctrl+V → 回车(可选) → **恢复用户剪贴板**（不影响日常使用）。

| 方法 | 说明 |
|---|---|
| `paste_text_to_chat(text)` | 粘贴文本到聊天输入框（不发送） |
| `paste_files_to_chat(paths)` | 粘贴文件（支持多个，CF_HDROP） |
| `send_message(content, send=True)` | str=文本；存在的路径=list 按文件（系统级）；send=True 回车发送 |
| `send_file_via_picker(path)` | **窗口级文件发送（推荐）**：文件按钮 → 对话框控件操作 → 回车 |
| `send_text_window(text)` | 窗口级文本（WM_CHAR，Deskflow 可用）|

**CLI**：`python my_automation/sender.py --text 文本 | --file 路径... | --send-msg 内容`

### 3.5 tasks.py — 组合任务（核心）

> **两种操作模式**（所有任务支持 `window_mode` 参数）：
> - **常规模式**（默认）：系统级 `SetCursorPos + mouse_event + SendInput`，需要鼠标/键盘在本机
> - **窗口模式** `--window`：全部 `PostMessage/ SendMessage` **直达微信主窗口**，不依赖系统焦点——
>   适合 **Deskflow / 远程键鼠切走** 的场景（实测鼠标移走仍全链路成功）

窗口模式要点（重要经验）：
- 点击搜索框/聊天输入框：窗口消息发**主窗口**，坐标按 `当前窗口尺寸/基准768×864` 等比自适应
- 输入/清空/回车：**同步击键流**（KEYDOWN+CHAR+KEYUP）发**主窗口**（搜索框在主窗口）
- 点击搜索框后必须补发 `WM_SETFOCUS` 让 Chromium 编辑框获得键盘焦点
- 清空用 **End + Backspace×60**（Ctrl+A 在 Qt/Chromium 下不可靠）
- **搜索下拉窗（Qt title='Weixin'）只做显示**：输入后第一项默认选中，
  直接 `post_key(VK_RETURN)` 即可打开联系人（**不要按 ↓**）

#### `open_contact_chat(contact, use_paste=False, wait_search=0.8, window_mode=False)` 

逐步流程：
1. 参数校验（contact 非空）
2. `is_logged_in()` 失败→`ERR_NOT_LOGGED_IN`
3. `init_wechat_window()`（内含关闭嵌入页等）失败→`ERR_WINDOW_INIT`
4. 点击点位1 搜索框 → **清空**（Ctrl+A+Delete）
5. 输入联系人（use_paste 或 type_text）→ 等待搜索结果（wait_search）
6. 记 `before_width` → 点击点位2（第一联系人）
7. **校验结果** `_check_contact_result`：宽度变化 / 额外可见窗口（搜一搜·添加朋友）/ 嵌入页 → 任一命中即失败 `ERR_CONTACT_NOT_FOUND`
8. 失败收尾 `_cleanup_contact_fail`：独立窗口直接关；嵌入页先点**点位4**再关
9. 点击点位3 聊天输入框 → 完成

#### `send_and_verify(contact, content, use_paste=False, wait_search=0.8, verify_backoff=15, save_sql=5)`

流程：`open_contact_chat` → `sender.send_message(content, send=True)` → **轮询验证**：
- 每秒 1 次解密 `message_0.db` 扫描，最多 12 次
- 查询窗口起点 `send_time - (5+attempt)`（前5→前10...），终点 `send_time+5`
- 匹配条件：时间在窗口内 + 内容存在于解压后的 `message_content`
- 命中→`OK`（附耗时次数）；12 次未中→`ERR_SEND_UNVERIFIED`

⚠️ **经验**：微信数据库约 5~10s 才 checkpoint（WAL→主库），读库总是滞后几秒，故需轮询而非一次性等待。

#### `_cleanup_contact_fail()` — 失败收尾

- 独立可见窗口（搜一搜/添加朋友）：直接 `WM_CLOSE`
- 嵌入搜一搜页：点**点位4**（分离按钮）循环最多3次 + 关闭分离出的独立窗口，直到 `has_embedded_page()==False`

---

## 4. 错误码全表（config.EC / 任务 ERR_*）

| code | 含义 |
|---|---|
| `OK` / `OK_DEGRADED` | 成功 / 降级成功 |
| `ERR_INTERNAL` | 未预期异常（附堆栈） |
| `ERR_NO_DB_DIR` / `ERR_NO_WECHAT_DATA` | 数据库路径无效 / 无微信数据 |
| `ERR_NO_KEYS` | 无解密密钥（微信需运行） |
| `ERR_DECRYPT` / `ERR_INDEX` / `ERR_BACKUP` | 解密/索引/管线失败 |
| `ERR_BAD_DATE` / `ERR_OUTPUT_NOT_FOUND` | 日期错误 / 产出物缺失 |
| `ERR_NO_DECRYPTED_DIR` | 未先执行 extract |
| `ERR_NO_CONTACT` / `ERR_AMBIGUOUS_CONTACT` | 联系人不匹配 / 匹配多个 |
| `ERR_NO_MESSAGES` | 时间范围内无消息 |
| `ERR_NOT_LOGGED_IN` | 微信未登录 |
| `ERR_WINDOW_INIT` | 窗口初始化失败 |
| `ERR_NO_POINT` | 点位缺失（先 capture） |
| `ERR_CLICK` / `ERR_INPUT` / `ERR_CLEAR` | 点击/输入/清空失败 |
| `ERR_SEND` / `ERR_CLIPBOARD` / `ERR_NO_FILE` | 发送/剪贴板/文件失败 |
| `ERR_CONTACT_NOT_FOUND` | **点击联系人后校验失败**（宽度变化/独立窗口/嵌入页） |
| `ERR_SEND_UNVERIFIED` | 轮询未在本地库找到刚发消息 |
| `ERR_NO_ACTIVE_DIR` / `ERR_RE_VERIFY` / `ERR_VERIFY_QUERY` | 验证链路失败 |

### 3.5 补充：AI 自动回复（context 多轮）

`auto_reply.py`：监控新消息 → 构建上下文 → GLM 生成 → 发送回复。

| 方法 | 说明 |
|---|---|
| `auto_reply(...)` | 组合任务：interval / only_contact / cooldown / dry_run / history_limit / extra_contacts |
| `_build_context(mon, sender, content, sys, history_limit, extra_contacts)` | 多轮 messages（对方=user，我方=assistant；extra_contacts 额外附加其他联系人消息）|
| `_generate_reply_ctx(mon, sender, content, ...)` | 带上下文调用 `ai.chat(messages)` |

`monitor.MessageMonitor.load_history_for(sender_id, limit)`：按 real_sender_id 拉历史（上下文数据源）。

**AI 模块**（`ai/`，来自 Z 盘头歌闯关王，已适配独立运行）：
- `ai.ask(prompt, provider='glm')` / `ai.chat(messages, provider='glm')`（支持多轮+system）
- 密钥：`config.json` 的 `GLM_API_KEYS`（已 gitignore，不入库）
- 错误分类+自动重试（quota/rate_limit/network/server/auth）

```bash
python my_automation/auto_reply.py --dry-run --seconds 60          # 只生成不发送
python my_automation/auto_reply.py --seconds 3600 --only 关键词     # 持续自动回复
python my_automation/auto_reply.py --extra wxid_a --extra wxid_b    # 附加上下文联系人
```

### 3.5 补充：窗口模式（window_mode）方法

`wechat_input.py` 窗口级方法（Deskflow 场景核心）：

| 方法 | 说明 |
|---|---|
| `post_click(x, y, hwnd=None)` | 窗口内点击（自适应坐标 → 客户区 → PostMessage）|
| `post_text(text, hwnd=None)` | 同步击键输入（KEYDOWN+CHAR+KEYUP，支持中文）|
| `post_key(vk, hwnd=None)` | 窗口内按键（→ 主窗口）|
| `post_clear()` | 清空输入框（End + Backspace×60）|
| `adapt_client_pt / adapt_screen_pt` | 点位等比自适应换算 |
| `_dropdown_window()` | 搜索下拉窗口识别（Qt 'Weixin'，仅诊断/显示用）|

发送：`sender.send_text_window(text)` 窗口级发文本（清空→输入→回车）；文件发送仍走系统级。

## 5. 关键经验（防坑记录）

1. **WAL checkpoint**：微信 4.x 消息先进 WAL，约 8~10s 才并入主库；读库验证必须轮询或留足时间
2. **64 位句柄**：`GlobalAlloc / SetClipboardData / CreateToolhelp32Snapshot / OpenProcess` 等必须显式 `restype=c_void_p`，否则句柄截断失败（多次踩坑）
3. **嵌入搜一搜页**：主窗口内出现 `Chrome_RenderWidgetHostHWND` 子窗口即嵌入页（正常聊天无）；无独立窗口、宽度可不变——窗口层唯一信号
4. **主窗口 vs 弹窗**：弹窗标题也可能是「微信」，主窗口 = 可见 + 标题含「微信」+ **面积最大**
5. **低层鼠标钩子不可靠**（本环境回调被静默丢弃），点位采集用 `GetAsyncKeyState` 轮询 + `GetCursorPos`（已实测稳定）
6. **剪贴板借用**：备份→置入→粘贴→恢复，不影响用户日常剪贴板
7. **微信数据合规**：仅个人数据；`points.json`/密钥配置不入库
8. **搜索下拉是独立 Qt 窗口**（title='Weixin'）：只显示候选，不接收操作；输入/键盘全走主窗口；第一项默认选中，回车即选
9. **Deskflow 场景**：所有自动化用窗口模式（`--window`），PostMessage 直达微信窗口，鼠标/键盘在哪台机器都无影响
10. **窗口焦点**：窗口级点击后发 `WM_SETFOCUS`，否则 Chromium 编辑框收不到键盘消息
11. **消息库内容**：当前 message_0.db 只含近期消息（WAL checkpoint 节奏），历史消息可能不在主库；AI 上下文以库内已有内容为准
12. **上下文角色**：对方消息=user、我方=assistant；extra_contacts 用 system 角色注入参考，不打断主对话
13. **文件发送双通道**：窗口级（文件按钮+对话框控件 WM_SETTEXT/BM_CLICK，不碰剪贴板，推荐）；系统级（剪贴板粘贴，Deskflow 下失效且同步到其它电脑）
14. **剪贴板借用不干扰**：全格式备份/还原 + `CanIncludeInClipboardHistory=0` + `ExcludeClipboardContentFromMonitorProcessing` + `Clipboard Viewer Ignore`（不进 Win+V 历史；Deskflow 仍会同步剪贴板，需在其设置关闭）
15. **修饰键防卡死**：`ctrl_key` / 窗口前置(Alt) 均有 finally 兜底释放（Ctrl/Shift/Alt/Win），注入被 Deskflow 中断也不会卡键
16. **文件对话框结构**（标准 IFileDialog）：`#32770` 标题「选择文件」+ 路径 `Edit id=1148` + 按钮 `Button id=1「打开(&O)」`；窗口级操作需**直投子控件**（顶层对话框不转发 WM_CHAR/按键）
17. **Win32 Edit 必须 WM_SETTEXT**：标准控件无输入焦点时不处理 WM_CHAR（与 Chromium 相反）；WM_SETTEXT 后**读回校验**（WM_GETTEXT）并重试，中文/长路径才稳
18. **指针参数**：ctypes 给 `LPARAM` 传字符串/缓冲区要转 int 地址 `ctypes.cast(obj, c_void_p).value`（argtypes 用 c_ssize_t）
19. **路径规范化**：发送前 `os.path.normpath(os.path.abspath(p))` → Windows 反斜杠形式

## 6. 演练示例

```bash
# 查看微信是否登录
python skill-scripts/wx_status.py

# 发送文件给联系人
python skill-scripts/wx_send.py --contact <联系人> --file "C:/Users/28910/Desktop/示例文件.csv"

# 发送并验证
python skill-scripts/wx_send_verify.py --contact 张三 --content "重要通知"
```