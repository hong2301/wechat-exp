# -*- coding: utf-8 -*-
"""
my_tools 集中配置
=================
- 项目路径 / src 路径解析
- 时间范围解析（YYYY-MM-DD）
- 错误码定义（检测模块统一使用）
"""
import os
import sys

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
# my_tools/ 位于项目根目录下，src/ 与 my_tools/ 平级
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')

def ensure_sys_path() -> None:
    """把 src/ 加入 sys.path，使 my_tools 可以引用 engine/* backup/* 等上游模块。"""
    if SRC_DIR not in sys.path:
        sys.path.insert(0, SRC_DIR)

# 默认输出目录（项目根目录下的 my_output/）
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'my_output')

# ---------------------------------------------------------------------------
# 时间范围
# ---------------------------------------------------------------------------
# 返回: (start_ts_seconds, end_ts_seconds) 或抛 ValueError
def parse_date_range(date_from: str = None, date_to: str = None):
    """解析 'YYYY-MM-DD' 起止日期。

    - 仅给 date_from: 范围 [该日 00:00:00, 无限)
    - 仅给 date_to:   范围 [无限, 该日 23:59:59]
    - 都给:           [from 00:00:00, to 23:59:59]
    返回 (start_ts, end_ts)，未给出的为 None。
    """
    import datetime as _dt
    from engine.constants import TZ  # noqa: F401  (由调用方 ensure_sys_path 后使用)

    start_ts = end_ts = None
    if date_from:
        d = _dt.datetime.strptime(date_from, '%Y-%m-%d').replace(tzinfo=TZ)
        start_ts = int(d.timestamp())
    if date_to:
        d = _dt.datetime.strptime(date_to, '%Y-%m-%d').replace(tzinfo=TZ)
        end_ts = int(d.timestamp()) + 86399  # 包含该日最后一秒
    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        raise ValueError(f'起始日期 {date_from} 晚于截止日期 {date_to}')
    return start_ts, end_ts


# ---------------------------------------------------------------------------
# 错误码（检测模块预设返回）
# ---------------------------------------------------------------------------
class EC:
    OK                    = 'OK'
    ERR_INTERNAL          = 'ERR_INTERNAL'           # 未预期异常
    ERR_NO_DB_DIR         = 'ERR_NO_DB_DIR'          # 传入的数据库路径不存在
    ERR_NO_WECHAT_DATA    = 'ERR_NO_WECHAT_DATA'     # 路径下找不到微信数据库
    ERR_NO_KEYS           = 'ERR_NO_KEYS'            # 无解密密钥（且无法从内存提取）
    ERR_DECRYPT           = 'ERR_DECRYPT'            # 解密阶段失败
    ERR_INDEX             = 'ERR_INDEX'              # 建索引失败
    ERR_BACKUP            = 'ERR_BACKUP'             # 备份管线整体失败
    ERR_OUTPUT_NOT_FOUND  = 'ERR_OUTPUT_NOT_FOUND'   # 产出物校验失败
    ERR_BAD_DATE          = 'ERR_BAD_DATE'           # 时间格式错误
    ERR_NO_DECRYPTED_DIR  = 'ERR_NO_DECRYPTED_DIR'   # 功能二找不到已解密数据
    ERR_NO_CONTACT        = 'ERR_NO_CONTACT'         # 找不到目标联系人
    ERR_AMBIGUOUS_CONTACT = 'ERR_AMBIGUOUS_CONTACT'  # 联系人匹配到多个结果
    ERR_NO_MESSAGES       = 'ERR_NO_MESSAGES'        # 该时间范围无消息
    ERR_QUERY             = 'ERR_QUERY'              # 消息读取失败

    _LABELS = {
        OK:                    '成功',
        ERR_INTERNAL:          '未预期异常',
        ERR_NO_DB_DIR:         '数据库路径不存在',
        ERR_NO_WECHAT_DATA:    '未找到微信数据库',
        ERR_NO_KEYS:           '无法获取解密密钥',
        ERR_DECRYPT:           '数据库解密失败',
        ERR_INDEX:             '索引构建失败',
        ERR_BACKUP:            '备份管线失败',
        ERR_OUTPUT_NOT_FOUND:  '产出文件校验失败',
        ERR_BAD_DATE:          '时间范围格式错误',
        ERR_NO_DECRYPTED_DIR:  '未找到已解密数据',
        ERR_NO_CONTACT:        '未找到目标联系人',
        ERR_AMBIGUOUS_CONTACT: '联系人匹配到多个结果',
        ERR_NO_MESSAGES:       '该时间范围没有消息',
        ERR_QUERY:             '聊天数据读取失败',
    }

    @staticmethod
    def label(code: str) -> str:
        return EC._LABELS.get(code, code)


# 统一结果结构：{"ok": bool, "code": str, "message": str, "data": ...}
def result(ok: bool, code: str, message: str, data=None) -> dict:
    return {'ok': ok, 'code': code, 'message': message, 'data': data}