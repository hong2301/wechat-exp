# -*- coding: utf-8 -*-
"""
检测模块（checker）
===================
所有检测函数返回统一结构：
    {"ok": bool, "code": str, "message": str, "data": ...}

错误码定义见 config.EC。失败时调用方（extract / query）把该结构
原样打印/返回，便于人工检查缺了什么。
"""
import os
import sys

from config import EC, result, ensure_sys_path

ensure_sys_path()


# ---------------------------------------------------------------------------
# 微信数据库路径检测
# ---------------------------------------------------------------------------
def check_db_dir(db_dir: str):
    """校验微信数据库路径。支持两种形态：
       1) db_storage 目录（含 message/contact/session 等子目录）
       2) xwechat_files 账号根目录（如 wxid_xxx_abcd，自动定位 db_storage）
    """
    if not db_dir:
        return result(False, EC.ERR_NO_DB_DIR, '未提供微信数据库路径')
    if not os.path.isdir(db_dir):
        return result(False, EC.ERR_NO_DB_DIR, f'路径不存在: {db_dir}')

    candidates = []
    # 形态 1: 直接就是 db_storage
    if os.path.isdir(os.path.join(db_dir, 'message')) or \
       os.path.isdir(os.path.join(db_dir, 'db_storage')):
        candidates.append(db_dir)
    # 形态 2: 账号根目录（含 db_storage 子目录）
    sub = os.path.join(db_dir, 'db_storage')
    if os.path.isdir(sub) and os.path.isdir(os.path.join(sub, 'message')):
        candidates.append(sub)

    if not candidates:
        return result(False, EC.ERR_NO_WECHAT_DATA,
                      f'目录下未找到微信数据库(db_storage/message): {db_dir}')

    db_path = candidates[0]
    msg_dir = os.path.join(db_path, 'message')
    try:
        dbs = [f for f in os.listdir(msg_dir) if f.endswith('.db')] \
            if os.path.isdir(msg_dir) else []
    except OSError as e:
        return result(False, EC.ERR_NO_WECHAT_DATA, f'读取 message 目录失败: {e}')

    if not dbs:
        return result(False, EC.ERR_NO_WECHAT_DATA,
                      f'db_storage 下没有任何 message 数据库: {db_path}')

    return result(True, EC.OK, f'数据库目录有效，发现 {len(dbs)} 个消息库',
                  {'db_path': db_path, 'msg_db_count': len(dbs)})


# ---------------------------------------------------------------------------
# 解密密钥检测
# ---------------------------------------------------------------------------
def check_keys():
    """检查本地是否已保存解密密钥（.wechat_exp_config.json 中的 db_keys）。"""
    try:
        from engine.config_file import get_db_keys
        keys = get_db_keys()
    except Exception:
        keys = None
    if keys:
        return result(True, EC.OK, f'已找到 {len(keys)} 个数据库密钥')
    return result(False, EC.ERR_NO_KEYS,
                  '本地无解密密钥；请确保微信(Weixin.exe)正在运行，'
                  '解密阶段会自动从进程内存提取，或先用 Web 界面执行"密钥提取"')


# ---------------------------------------------------------------------------
# 已解密数据目录检测（功能二使用）
# ---------------------------------------------------------------------------
def check_decrypted_dir(decrypted_dir: str):
    """校验解密后的数据目录是否完整（contact.db / message 库存在）。"""
    if not decrypted_dir or not os.path.isdir(decrypted_dir):
        return result(False, EC.ERR_NO_DECRYPTED_DIR,
                      f'已解密数据目录不存在: {decrypted_dir}\n'
                      f'请先运行 my_tools/extract.py 完成备份解密，'
                      f'或用 --decrypted-dir 指定已有目录')
    contact_db = os.path.join(decrypted_dir, 'contact', 'contact.db')
    msg_dir = os.path.join(decrypted_dir, 'message')
    have_contact = os.path.isfile(contact_db)
    have_msg = os.path.isdir(msg_dir) and \
        any(f.endswith('.db') for f in os.listdir(msg_dir))
    if not (have_contact and have_msg):
        return result(False, EC.ERR_NO_DECRYPTED_DIR,
                      f'解密目录不完整 (contact.db={have_contact}, message库={have_msg}): '
                      f'{decrypted_dir}')
    return result(True, EC.OK, f'解密目录有效: {decrypted_dir}')


# ---------------------------------------------------------------------------
# 时间范围检测
# ---------------------------------------------------------------------------
def check_date_range(date_from=None, date_to=None):
    """校验时间范围，成功时返回 (start_ts, end_ts)。"""
    try:
        from config import parse_date_range
        start_ts, end_ts = parse_date_range(date_from, date_to)
    except ValueError as e:
        return result(False, EC.ERR_BAD_DATE, f'时间范围错误: {e}')
    return result(True, EC.OK, '时间范围有效', (start_ts, end_ts))


# ---------------------------------------------------------------------------
# 联系人匹配（功能二使用）
# ---------------------------------------------------------------------------
def find_contact(decrypted_dir: str, contact_key: str):
    """按显示名 / 备注 / 微信号模糊匹配联系人会话。

    返回统一结果，data 为 [{username, display_name, msg_count, is_group, tables}]
    """
    try:
        from chat_list import scan_chats
        chats, id_to_name, name_to_id = scan_chats(decrypted_dir)
    except Exception as e:
        return result(False, EC.ERR_QUERY, f'会话扫描失败: {e}')

    if not contact_key:
        return result(False, EC.ERR_NO_CONTACT, '未提供联系人（显示名或微信号）')

    key = str(contact_key).strip().lower()
    exact = [c for c in chats
             if c['username'].lower() == key
             or str(c['display_name']).lower() == key]
    if exact:
        return result(True, EC.OK, f'精确匹配 {len(exact)} 个会话', exact)

    fuzzy = [c for c in chats
             if key in str(c['username']).lower()
             or key in str(c['display_name']).lower()]
    if not fuzzy:
        return result(False, EC.ERR_NO_CONTACT,
                      f'未找到联系人: {contact_key}（尝试用微信号或昵称）')
    if len(fuzzy) > 5:
        return result(False, EC.ERR_AMBIGUOUS_CONTACT,
                      f'“{contact_key}”匹配到 {len(fuzzy)} 个会话，请用微信号精确定位',
                      fuzzy[:10])
    return result(True, EC.OK, f'模糊匹配 {len(fuzzy)} 个会话', fuzzy)