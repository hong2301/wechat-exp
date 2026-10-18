# 关键经验（防坑记录）

> **动手改自动化代码前必读**，这 20 条都是实测踩过的坑。

1. **WAL checkpoint**：微信 4.x 消息先进 WAL，约 8~10s 才并入主库；读库验证必须轮询或留足时间
2. **64 位句柄**：`GlobalAlloc / SetClipboardData / CreateToolhelp32Snapshot / OpenProcess` 等必须显式 `restype=c_void_p`，否则句柄截断失败（多次踩坑）
3. **嵌入搜一搜页**：主窗口内出现 `Chrome_RenderWidgetHostHWND` 子窗口即嵌入页（正常聊天无）；无独立窗口、宽度可不变——窗口层唯一信号
4. **主窗口 vs 弹窗**：弹窗标题也可能是「微信」，主窗口 = 可见 + 标题含「微信」+ **面积最大**
5. **低层鼠标钩子不可靠**（本环境回调被静默丢弃），点位采集用 `GetAsyncKeyState` 轮询 + `GetCursorPos`（已实测稳定）
6. **剪贴板借用**：备份→置入→粘贴→恢复，不影响用户日常剪贴板
7. **敏感配置不外传**：`points.json` / 密钥配置不提交、不外传
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
20. **Deskflow 环境铁律：全链路必须窗口级**（重要教训）——只要有一个环节走系统级，就会**穿透到其它电脑**：
    - `open_contact_chat(window_mode=True)` 必须为 True（否则 `mouse_click`→SetCursorPos 移动系统鼠标、`type_text`/`ctrl_key` 注入键盘）
    - `init_wechat_window` 内部关闭嵌入页必须用 `post_click`（不要 `mouse_click`）
    - `_force_foreground` **禁止注入 Alt 键**（Deskflow 会同步 Alt → 其它电脑卡键）；改用 `AttachThreadInput + SetForegroundWindow`
    - 现象对照：鼠标乱动=系统级 SetCursorPos；Ctrl/Alt 卡住=系统级组合键注入；回车打到其它电脑=系统级 SendInput Enter（可能触发桌面全选等操作）
    - 默认值约定：`wx_send/wx_open_chat/wx_send_verify` 默认窗口级，系统级需显式 `--system`

