# my_automation — 自动化操作微信模块

> 📌 **开发状态**：模块化开发中（整体项目将封装为 skill）

## 定位

自动化操作微信客户端，核心场景：**发消息**。

与 `my_tools/`（读取解密数据）互补：
- `my_tools/` ← 读（提取 / 查询本地聊天数据）
- `my_automation/` ← 写（自动化操作微信，如发消息）

## 模块规划

**无主程序**：本项目不设主入口，由各模块文件自行管理方法，按 skill 方向组织。

```
my_automation/
├── __init__.py        ← 模块说明
├── README.md          ← 本规范文档
├── wechat_status.py   ← 模块①：微信状态（运行 / 登录 / 窗口初始化）
├── points.py          ← 模块②：点位（搜索框 / 第一联系人 / 聊天输入框）
├── sender.py          ← 模块③：发消息核心（待实现）
└── ...
```

## 开发边界（重要规范）

1. **索引/阅读范围**：默认只检索本项目两个自定义模块
   - `my_tools/`（读取解密数据）
   - `my_automation/`（自动化操作）
2. **主依赖项目不主动查看**：上游 `src/`、参考项目等，仅在特殊情况且经用户允许时才查看
3. **实现风格**：轻量、独立、不照搬上游/参考项目；每个模块提供清晰的方法（函数）

## 方法清单（随开发补充）

### wechat_status.py — 微信状态模块

| 方法 | 说明 |
|---|---|
| `is_wechat_running()` | 检测微信进程是否在运行 |
| `is_logged_in()` | 检测微信是否已登录（数据目录锁定判定，多级降级） |
| `get_data_dirs()` | 检测本机全部微信数据目录（按 wxid 去重） |
| `get_locked_data_dirs()` | 检测被微信锁定的目录（= 登录中的账号目录） |
| `get_active_data_dir()` | 当前被锁定/使用中的目录（无则 None） |
| `init_wechat_window()` | 窗口初始化：前置主窗口并移动到左半屏 |
| `get_status()` | 汇总返回状态 dict |

### points.py — 点位模块

点位：`search_box`（搜索框）/ `chat_input`（聊天输入框）/ `search_split_button`（搜一搜窗口分离按钮），存储于 `points.json`（已 gitignore）。第一联系人无需点位（输入后回车默认选中第一项）。

| 方法 | 说明 |
|---|---|
| `load_points()` / `get_points()` | 读取全部点位 |
| `get_point(name)` | 读取单个点位 |
| `save_points(points)` | 保存全部点位 |
| `capture_all()` | 交互式采集 3 个点位（单击预览/双击确认/右键取消） |
| `capture_one(prompt)` | 交互式采集单个点位 |
| `clear_points()` | 清空点位 |

```bash
python my_automation/points.py show      # 查看点位
python my_automation/points.py capture   # 交互采集
python my_automation/points.py clear     # 清空
```