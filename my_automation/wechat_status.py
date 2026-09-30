# -*- coding: utf-8 -*-
"""
wechat_status — 微信状态模块（模块①）
=====================================
功能：检测微信是否运行、是否真正登录、占用哪个数据目录。

方法：
    is_wechat_running()      检测微信进程是否在运行（纯标准库 ctypes）
    get_data_dirs()          检测本机全部微信数据目录
    get_locked_data_dirs()   检测被微信锁定的数据目录（= 真正登录中的账号）
    get_active_data_dir()    返回当前被锁定/使用中的目录（无则 None）
    is_logged_in()           是否已登录（有锁定目录 = 已登录，多级降级）
    get_status()             汇总返回状态 dict

检测逻辑（重要修正）：
    ⚠️ 「主窗口存在」≠「已登录」—— 微信打开但未登录时主窗口同样存在。
    可靠的登录判定依据：微信登录后才会**锁定**（占用）其数据目录里的数据库。
    - 有数据目录被锁定  ⇒ 已登录
    - 微信在运行但无目录被锁定 ⇒ 打开了但未登录（等待扫码等）
    - 锁定探测失败时降级为窗口启发式判定（主窗口存在视为已登录）

实现说明：
    - 进程/窗口检测：纯标准库 ctypes，独立实现。
    - 数据目录枚举与锁定探测：复用依赖项目（wechat-exp 上游 src/）能力
      （*经用户许可*：engine.utils.find_all_wechat_data_dirs /
      engine.services.active_dir.dirs_in_use_by_wechat —— T0 句柄归属，
      精确命中"微信进程实际打开/使用的 db_storage"）。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# sys.path：复用依赖项目（上游 src/）的数据目录检测能力（用户已许可）
# ---------------------------------------------------------------------------
_SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# ---------------------------------------------------------------------------
# Windows API 常量 / 结构（纯 ctypes，与上游无关）
# ---------------------------------------------------------------------------
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

# 微信可执行文件名（覆盖 3.x / 4.x）
WECHAT_EXES = {"wechat.exe", "weixin.exe"}


def _kernel32():
    return ctypes.windll.kernel32


def _user32():
    return ctypes.windll.user32


# ---------------------------------------------------------------------------
# 进程检测（独立实现）
# ---------------------------------------------------------------------------
def _wechat_pids() -> List[int]:
    """枚举当前所有微信进程 PID。"""
    k32 = _kernel32()
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, INVALID_HANDLE_VALUE):
        return []
    pids = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() in WECHAT_EXES:
                    pids.append(entry.th32ProcessID)
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return pids


def is_wechat_running() -> bool:
    """微信进程是否在运行。"""
    return bool(_wechat_pids())


# ---------------------------------------------------------------------------
# 数据目录检测（复用依赖项目能力，用户已许可）
# ---------------------------------------------------------------------------
def get_data_dirs() -> List[dict]:
    """检测本机全部微信数据目录。

    返回 [{'db_path': str, 'wxid': str, 'db_count': int, 'size_mb': float}, ...]
    同 wxid 目录可能重复出现（上游枚举多条路径），本函数按 wxid 去重。
    """
    from engine.utils import find_all_wechat_data_dirs
    _by_wxid = {}
    for d in find_all_wechat_data_dirs():
        w = d.get('wxid') or d.get('db_path')
        if w not in _by_wxid or d.get('db_count', 0) > _by_wxid[w].get('db_count', 0):
            _by_wxid[w] = d
    return list(_by_wxid.values())


def get_locked_data_dirs(errors: Optional[list] = None) -> dict:
    """检测被微信锁定的数据目录（= 真正登录中的账号目录）。

    复用依赖项目 T0 句柄归属探测：精确命中微信进程实际打开/使用的 db_storage。
    返回 {db_storage 根路径: [pid, ...]}；微信未运行或未锁定时返回 {}。
    """
    from engine.services.active_dir import dirs_in_use_by_wechat
    if errors is None:
        errors = []
    return dirs_in_use_by_wechat(errors=errors, timeout_s=1.5)


def get_active_data_dir() -> Optional[str]:
    """当前被微信锁定/使用的数据目录（无则 None）。"""
    locked = get_locked_data_dirs()
    if not locked:
        return None
    # 锁定探测成功时取锁定的目录；若同一 wxid 多条, 返回第一个
    import os as _os
    return sorted(locked.keys())[0]


# ---------------------------------------------------------------------------
# 窗口检测（独立实现，仅作降级参考）
# ---------------------------------------------------------------------------
def _wechat_windows(pids: List[int]) -> List[Tuple[int, str, bool]]:
    """枚举属于微信进程的所有顶层窗口 [(hwnd, title, visible), ...]。"""
    if not pids:
        return []
    u32 = _user32()
    pid_set = set(pids)
    result = []

    def callback(hwnd, lparam):
        buf = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, buf, 512)
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pid_set:
            result.append((hwnd, buf.value, bool(u32.IsWindowVisible(hwnd))))
        return True

    u32.EnumWindows(WNDENUMPROC(callback), 0)
    return result


_LOGIN_KEYWORDS = ("登录", "login", "扫一扫", "二维码")
_MAIN_KEYWORDS = ("微信", "wechat")


def _has_login_window(pids: List[int]) -> bool:
    """是否存在微信登录窗口（未登录状态的信号）。"""
    for _hwnd, title, _vis in _wechat_windows(pids):
        t = title.strip().lower()
        if any(k in t for k in _LOGIN_KEYWORDS):
            return True
    return False


def _has_main_window(pids: List[int]) -> bool:
    """是否存在微信主窗口。"""
    for _hwnd, title, _vis in _wechat_windows(pids):
        t = title.strip().lower()
        if any(k in t for k in _MAIN_KEYWORDS):
            return True
    return False


# ---------------------------------------------------------------------------
# 登录判定（核心：数据目录锁定）
# ---------------------------------------------------------------------------
def is_logged_in() -> bool:
    """微信是否已真正登录。

    判定优先级：
      1. 微信未运行                                    → False
      2. 锁定探测成功（T0 句柄归属，errors 无 t0 错误）：
           有锁定目录  → True（已登录，正在用该账号）
           无锁定目录  → False（打开了但未登录）
      3. 锁定探测失败（权限/降级）                     → 窗口启发式兜底：
           有登录窗 → False；有主窗口 → True
    """
    pids = _wechat_pids()
    if not pids:
        return False

    errors = []
    locked = get_locked_data_dirs(errors=errors)
    t0_failed = any(str(e).startswith('t0:') for e in errors)
    if not t0_failed:
        return bool(locked)  # 锁定探测可靠：有锁定=已登录

    # 降级：窗口启发式
    if _has_login_window(pids):
        return False
    return _has_main_window(pids)


# ---------------------------------------------------------------------------
# 汇总状态
# ---------------------------------------------------------------------------
def get_status() -> dict:
    """汇总微信状态。

    返回示例：
        {
            "running": True,
            "logged_in": True,
            "pids": [12345, ...],
            "data_dirs": [{"wxid": ..., "db_path": ..., ...}],   # 全部账号目录
            "locked_dirs": {"D:/.../db_storage": [pid, ...]},    # 登录中账号
            "windows": [...],
            "detail": "运行中且已登录（占用账号: wxid_xxx）"
        }
    """
    pids = _wechat_pids()
    running = bool(pids)

    data_dirs = get_data_dirs() if running else []
    locked = get_locked_data_dirs() if running else {}
    logged_in = is_logged_in() if running else False

    if not running:
        detail = "微信未运行"
    elif logged_in:
        wxid = ""
        for d in data_dirs:
            if d.get('db_path') and os.path.normcase(d['db_path']) in \
                    [os.path.normcase(k) for k in locked]:
                wxid = d.get('wxid', '')
                break
        detail = f"运行中且已登录（占用账号: {wxid or '未知'}）"
    else:
        detail = "运行中但未登录（已打开，等待扫码/登录）"

    return {
        "running": running,
        "logged_in": logged_in,
        "pids": pids,
        "data_dirs": data_dirs,
        "locked_dirs": locked,
        "windows": [{"title": t, "visible": v} for _h, t, v in _wechat_windows(pids)],
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# CLI 便捷入口（python my_automation/wechat_status.py 直接查看状态）
# ---------------------------------------------------------------------------
def main():
    import json
    print(json.dumps(get_status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()