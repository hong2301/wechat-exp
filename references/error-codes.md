# 错误码全表

> 所有方法返回 `{ok, code, message}`，此处为 `code` 的完整定义。

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

