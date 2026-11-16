# my_automation — 自动化操作微信模块（写域）

> 现状：**已可用**。默认全链路窗口级（`PostMessage` / `SendMessage`），
> 不前置窗口、不动真实鼠标键盘，Deskflow 切到别的机器时也能发。
> 方法签名与错误码详见 `../references/api.md`、`../references/error-codes.md`。

## 定位

与 `my_tools/`（读解密数据）互补：

- `my_tools/` ← **读**：提取 / 查询本地聊天数据
- `my_automation/` ← **写**：检测状态、摆窗口、打开聊天、发文字/文件、发送后读库验证、监控与自动回复

无主入口，每个模块自成一层，由 `skill-scripts/` 的薄壳或上层 `tasks.py` 组合调用。

## 模块清单

| 文件 | 角色 | 关键接口 |
|---|---|---|
| `wechat_status.py` | 状态与窗口 | `is_wechat_running` / `is_logged_in` / `get_data_dirs` / `get_active_data_dir` / `init_wechat_window` / `get_search_panel` / `has_embedded_page` / `extra_visible_windows` / `get_status` |
| `points.py` | 点位 | `get_point` / `save_points` / `capture_all` / `capture_one_point` / `clear_points`；`search_box` `search_split_button` `file_button` 必需，`chat_input` 可选 |
| `wechat_input.py` | 输入原子操作 | 窗口级 `post_click` / `post_text` / `post_enter` / `post_key` / `post_clear`；系统级 `mouse_click` / `type_text` / `paste_text` / `clear_input` / `key_press` |
| `sender.py` | 发送 | `send_text_window`（窗口级文本）/ `send_file_via_picker`（窗口级文件）/ `paste_text_to_chat` / `send_message`（系统级） |
| `tasks.py` | 组合任务 | `open_contact_chat` / `send_and_verify`（含轮询验证、失败收尾） |
| `monitor.py` | 新消息监控（只读） | `MessageMonitor.poll_once` / `.watch` / `.load_history_for` / `.wal_changed` |
| `auto_reply.py` | AI 自动回复 | `auto_reply(...)`（监控 + GLM 上下文 + 发送，单发即停、已回复持久化） |
| `pi_mesh.py` | Pi 消息网格 | `send(text, target)` / `list_peers()`（走 remote-pi broker 管道） |

## 常用命令

```bash
python my_automation/wechat_status.py          # 状态（也可 python -c 调 get_status）
python my_automation/points.py show            # 点位当前值
python my_automation/points.py capture         # 交互采集（单击预览 / 双击确认 / 右键取消）
python my_automation/monitor.py --seconds 60   # 监控新消息
python my_automation/auto_reply.py --dry-run --seconds 60
python my_automation/sender.py --text "你好"   # 底层发送（一般用 skill-scripts/wx_send.py）
```

日常请走 `../skill-scripts/`，那边已经处理了路径、日志与退出码。

## 开发边界

1. **索引/阅读范围**：默认只看 `my_tools/` 与 `my_automation/`
2. **上游 `src/` 不主动改**：只在需要解密/查询服务时按需 import（`backup.decryptor`、`engine.services.*`）
3. **实现风格**：轻量、独立，每个模块提供清晰函数；返回统一 `{ok, code, message}`

## 三条铁律（改动前必读）

1. **发送用 `post_enter()`，不要 `post_key(VK_RETURN)`** —— 微信 4.x 不响应
   `PostMessage` 投递的回车，文字只会变成草稿、或在搜索框里变成「搜一搜」。
2. **全链路窗口级** —— 任何一环回退到 `SetCursorPos` / `SendInput`，
   在 Deskflow 环境都会穿透到别的电脑（鼠标乱动、Alt 卡键）。系统级必须显式 `--system`。
3. **点位与窗口布局绑定** —— 采点前先 `init_wechat_window()` 把窗口摆成左半屏，
   否则换分辨率 / 改布局后点位全错。

更多实战坑见 `../references/pitfalls.md`。
