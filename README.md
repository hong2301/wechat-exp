# 微信数据（WeChat Data）

> 一个完整的 Agent Skill：**读**微信本地聊天数据库（提取 / 查询），并**写**微信客户端（自动化操作：状态检测、窗口初始化、发消息、发送验证）。

基于 [WeChat EXP](https://github.com/sunhanaix/pc_wechat_exp)（上游主依赖），以 skill 方式封装为两个自定义能力域，整体作为 pi skill 使用。

---

## ✨ 能力一览

| 域 | 模块 | 能力 |
|---|---|---|
| **读** `my_tools/` | `extract.py` | 输入微信本地数据库 + 时间范围 → 解密形成本地数据库 |
| | `query.py` | 联系人 + 时间段 → 完整聊天数据（JSON / TXT / HTML） |
| | `checker.py` | 检测模块：路径 / 密钥 / 时间 / 联系人校验，预设错误返回 |
| **写** `my_automation/` | `wechat_status.py` | 登录检测（数据目录锁定判定）、窗口初始化（唯一主窗口 + 左半屏）、嵌入页检测 |
| | `points.py` | 点位管理（JSON 存储 + 交互采集：单击预览 / 双击确认 / 右键取消） |
| | `wechat_input.py` | 点击 / UNICODE 输入 / 剪贴板粘贴 / 清空输入框 |
| | `sender.py` | 剪贴板借用式发送（文本 / 文件），用后恢复不影响日常剪贴板 |
| | `tasks.py` | **组合任务**：打开联系人聊天、发送 + 数据库验证、失败收尾清理 |

## 🚀 快速开始

```bash
# 技能脚本（skill-scripts/，也可直接 python wechat-exp 内模块）
python skill-scripts/wx_status.py                          # 微信状态
python skill-scripts/wx_open_chat.py --contact 张三        # 打开联系人聊天
python skill-scripts/wx_send.py --contact 张三 --text "你好"
python skill-scripts/wx_send.py --contact 张三 --file "C:/path/a.csv"            # 系统级(剪贴板)
python skill-scripts/wx_send.py --contact 张三 --file "C:/path/a.csv" --window   # 窗口级(文件按钮,不碰剪贴板)
python skill-scripts/wx_send_verify.py --contact 张三 --content "验证内容"
python skill-scripts/wx_points.py show                     # 查看点位
python skill-scripts/wx_extract.py --wxid wxid_xxx        # 提取数据库
python skill-scripts/wx_query.py --contact 张三           # 查询聊天
```

## 🧩 Skill 结构

```
.
├── SKILL.md                  ← skill 入口（pi 规范）
├── skill-refs/INDEX.md       ← 完整索引：方法签名 / 组合流程 / CLI / 错误码 / 防坑经验
├── skill-scripts/            ← 8 个可执行脚本（薄壳，可独立运行）
├── my_tools/                 ← 读域（本地数据库）
├── my_automation/            ← 写域（微信自动化）
├── src/                      ← 上游 WeChat EXP（主依赖，随 upstream 更新）
└── .gitignore                ← 忽略密钥配置 / 点位坐标 / 运行产物
```

## 🧵 组合任务（核心流程）

- **`tasks.open_contact_chat(contact)`**：检测登录 → 窗口初始化（自动关闭嵌入搜一搜页）→ 清空并搜索 → 点第一联系人 → **校验结果**（主窗口宽度变化 / 独立搜一搜 / 添加朋友 / 嵌入页 任一命中即判未找到）→ 点聊天输入框；失败自动收尾清理
- **`tasks.send_and_verify(contact, content)`**：打开聊天 → 粘贴 + 回车发送 → **轮询解密本地库验证**（每秒 1 次，最多 12 次；微信数据库约 5~10s 才 checkpoint，读库总是滞后几秒）

所有方法统一返回 `{"ok": bool, "code": str, "message": str}`，错误码全表见 `skill-refs/INDEX.md`。

## 📌 前提与合规

- Windows 10/11 + 微信 4.x，微信需已登录（密钥从进程内存自动提取）
- 仅处理**自己的**聊天数据，解密密钥与点位坐标不入库
- 主依赖项目（`src/`、参考项目）默认不主动查看，特殊情况经用户许可

## 🔄 上游同步

```bash
git fetch upstream && git merge upstream/master   # 自定义模块独立，几乎零冲突
```

## 📜 许可

私有工具项目（上游 WeChat EXP 部分版权归原作者；本自定义部分保留）。