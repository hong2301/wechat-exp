# my_tools — 微信聊天数据自定义工具

基于 WeChat EXP（pc_wechat_exp）抽离的两个核心功能，独立文件夹，不与上游源码冲突。

## 功能

| 模块 | 功能 | 输入 | 输出 |
|---|---|---|---|
| `extract.py` | 功能一：提取 | 微信数据库路径 + 时间范围 | 解密后的完整数据库 + 摘要索引 `chats.db` |
| `query.py` | 功能二：查询 | 联系人 + 时间范围 | 完整聊天数据（结构化 JSON / TXT / HTML） |

## 快速使用

先决条件：微信（Weixin.exe）正在运行（密钥从进程内存自动提取，只需首次提取一次，之后保存在 `.wechat_exp_config.json`）。

```bash
# 功能一：自动检测微信数据目录（多账号时用 --wxid 指定），解密全量数据
python my_tools/extract.py

# 功能一：指定数据库路径 + 时间范围
python my_tools/extract.py --db-dir D:\xwechat_files\wxid_xxx\db_storage \
                           --date-from 2024-01-01 --date-to 2024-12-31 \
                           -o my_output/backup

# 功能二：查询某联系人的全部聊天记录（自动定位最近一次备份）
python my_tools/query.py --contact 张三

# 功能二：联系人 + 时间段，输出 JSON / TXT / HTML
python my_tools/query.py --contact 张三 --date-from 2024-01-01 --date-to 2024-06-30 \
                         --format json -o my_output/query
```

### 输出结构

- `my_output/backup/` — 功能一输出（解密库 + `data/chats.db`）
- `my_output/query/` — 功能二输出（每人一个 JSON / TXT / HTML 文件）

JSON 消息字段：`local_id`、`time`、`timestamp`、`sender`（发送者显示名）、`side`（me/other/system/unknown）、`type`（原始类型码）、`type_name`（中文类型）、`content`（解析后内容）、`status`。

## 检测模块（预设错误返回）

所有失败场景返回统一结构，方便人工检查：

```json
{"ok": false, "code": "ERR_NO_CONTACT", "message": "未找到联系人: 张三（尝试用微信号或昵称）", "data": null}
```

| 错误码 | 含义 |
|---|---|
| `ERR_NO_DB_DIR` | 传入的数据库路径不存在 |
| `ERR_NO_WECHAT_DATA` | 目录下未找到微信数据库 |
| `ERR_NO_KEYS` | 无解密密钥（微信未运行或从未提取过密钥） |
| `ERR_BAD_DATE` | 时间范围格式错误 |
| `ERR_DECRYPT` / `ERR_INDEX` / `ERR_BACKUP` | 解密 / 索引 / 管线失败 |
| `ERR_NO_DECRYPTED_DIR` | 未找到已解密数据（先运行 extract） |
| `ERR_NO_CONTACT` / `ERR_AMBIGUOUS_CONTACT` | 联系人未找到 / 匹配多个 |
| `ERR_NO_MESSAGES` | 该时间段没有消息 |
| `ERR_INTERNAL` | 未预期异常（附堆栈，便于人工排查） |

## 与上游同步更新

本文件夹不修改上游任何文件，因此上游更新 merge 时**几乎零冲突**：

```bash
# 首次：关联上游
git remote add upstream https://github.com/sunhanaix/pc_wechat_exp.git

# 每次上游更新后：
git fetch upstream
git merge upstream/main
```

若 GitHub 上使用 fork，则直接在页面点 **Sync fork** 即可同步。

> 注意：密钥 `.wechat_exp_config.json` 位于项目根目录（已被 gitignore），不会提交；`my_output/` 也在 gitignore 内。