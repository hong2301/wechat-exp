# 错误码全表

> 所有方法返回 `{ok: bool, code: str, message: str}`（读域另有 `data`）。
> **失败时把 `message` 原样上报**，不要概括成「失败了」。
> 本表与 `my_tools/config.py` 的 `EC` 类、`my_automation/*.py` 的实际返回值核对过（2026-11-16）。

## 1. 通用

| code | 含义 |
|---|---|
| `OK` | 成功 |
| `OK_DEGRADED` | 成功但降级（如窗口没能摆到左半屏，不阻塞后续） |
| `ERR_INTERNAL` | 未预期异常（message 里带堆栈） |
| `ERR_INIT` | 模块初始化失败（如监控器找不到库/密钥） |
| `ERR_EMPTY` | 入参为空（文本、文件列表） |

## 2. 读域（`my_tools`）

| code | 含义 |
|---|---|
| `ERR_NO_DB_DIR` | 传入的数据库路径不存在 |
| `ERR_NO_WECHAT_DATA` | 路径下找不到微信数据库 |
| `ERR_NO_KEYS` | 无解密密钥（微信需运行且已登录） |
| `ERR_DECRYPT` / `ERR_INDEX` / `ERR_BACKUP` | 解密 / 索引 / 管线失败 |
| `ERR_OUTPUT_NOT_FOUND` | 产出物缺失 |
| `ERR_BAD_DATE` | 时间范围格式错误 |
| `ERR_NO_DECRYPTED_DIR` | 未先执行 `extract`，找不到已解密数据 |
| `ERR_NO_CONTACT` / `ERR_AMBIGUOUS_CONTACT` | 联系人不匹配 / 匹配到多个 |
| `ERR_NO_MESSAGES` | 该时间范围内无消息 |
| `ERR_QUERY` | 消息读取失败 |

## 3. 写域 · 微信状态与窗口

| code | 含义 |
|---|---|
| `ERR_NO_WECHAT` | 微信未运行 |
| `ERR_NOT_LOGGED_IN` | 微信未登录 |
| `ERR_NO_MAIN_WINDOW` | 找不到微信主窗口（可见 + 标题含「微信」+ 面积最大） |
| `ERR_WINDOW_INIT` | 窗口初始化失败（`init_wechat_window` 上层封装） |
| `ERR_MOVE_FAILED` | 窗口移动/尺寸设置失败（通常降级为 `OK_DEGRADED`） |

## 4. 写域 · 输入与点位

| code | 含义 |
|---|---|
| `ERR_NO_POINT` | 点位缺失 → 先 `wx_points.py capture` |
| `ERR_UNKNOWN_POINT` | 指定了不存在的点位名 |
| `ERR_NO_WINDOW` | 操作目标句柄为空 |
| `ERR_POST` | `PostMessage` 投递失败 |
| `ERR_SENDINPUT` | `SendInput` 注入失败 |
| `ERR_CLICK` / `ERR_INPUT` / `ERR_CLEAR` | 点击 / 输入 / 清空失败 |
| `ERR_NO_ACTIVE_DIR` | 找不到当前登录账号的数据目录 |

## 5. 写域 · 发送

| code | 含义 |
|---|---|
| `ERR_SEND` | 发送动作失败 |
| `ERR_CLIPBOARD` | 剪贴板写入失败（系统级通道） |
| `ERR_NO_FILE` | 文件不存在 |
| `ERR_NO_PICKER` | 没等到「选择文件」对话框（`#32770`） |
| `ERR_NO_EDIT` | 对话框里找不到路径栏 `Edit id=1148` |
| `ERR_SET_PATH` | `WM_SETTEXT` 写入路径后读回校验不一致（中文/长路径重点看这条） |
| `ERR_NO_BUTTON` | 对话框里找不到「打开(&O)」按钮 |
| `ERR_WRITE` | 管道 / 文件写入失败 |

## 6. 写域 · 任务与验证

| code | 含义 |
|---|---|
| `ERR_NO_CONTACT` | 未提供联系人名称（入参层） |
| `ERR_CONTACT_NOT_FOUND` | **回车后冒出了新的微信可见窗口**（搜一搜 / 添加朋友）⇒ 该查询词没匹配到联系人。旧判据「窗口宽度变化」已废弃 |
| `ERR_NO_CONTENT` | `send_and_verify` 未提供发送内容 |
| `ERR_SEND_UNVERIFIED` | **读库验证未命中**（不等于没发出去）。若是密钥问题，message 里会出现「无密钥，无法解密」→ 按 `SKILL.md` 重新提取密钥 |
| `ERR_NO_TARGET` | `pi_mesh` 目标地址无效（须为 `<cwd>@<name>`） |
| `ERR_NO_BROKER` | `pi_mesh` 连不上 broker 命名管道 |
