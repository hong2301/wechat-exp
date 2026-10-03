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
    init_wechat_window()     微信窗口初始化：前置主窗口并移动到左半屏
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


WECHAT_APPEX = "WeChatAppEx.exe"      # 小程序/外部容器进程
WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SM_CXSCREEN = 0
SM_CYSCREEN = 1


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _kernel32():
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    return k32


def _user32():
    u32 = ctypes.windll.user32
    u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_size_t]
    u32.GetSystemMetrics.restype = ctypes.c_int
    return u32


# ---------------------------------------------------------------------------
# 进程检测（独立实现）
# ---------------------------------------------------------------------------
def _pids_by_exe(exe_names) -> List[int]:
    """按可执行文件名集合枚举进程 PID（不区分大小写）。"""
    if not exe_names:
        return []
    k32 = _kernel32()
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, INVALID_HANDLE_VALUE):
        return []
    want = {n.lower() for n in exe_names}
    pids = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() in want:
                    pids.append(entry.th32ProcessID)
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return pids


def _wechat_pids() -> List[int]:
    """枚举当前所有微信（Weixin/WeChat）进程 PID。"""
    return _pids_by_exe(WECHAT_EXES)


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
def _windows_for_pids(pids: List[int]) -> List[Tuple[int, str, bool, int]]:
    """枚举属于指定进程集合的顶层窗口 [(hwnd, title, visible, pid), ...]。"""
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
            result.append((hwnd, buf.value, bool(u32.IsWindowVisible(hwnd)), pid.value))
        return True

    u32.EnumWindows(WNDENUMPROC(callback), 0)
    return result


def _wechat_windows(pids: List[int]) -> List[Tuple[int, str, bool]]:
    """枚举属于微信进程的所有顶层窗口 [(hwnd, title, visible), ...]（兼容旧签名）。"""
    return [(h, t, v) for h, t, v, _p in _windows_for_pids(pids)]


# ---------------------------------------------------------------------------
# 窗口管理：唯一主窗口 + 关闭冗余窗口（健壮性）
# ---------------------------------------------------------------------------
def _process_working_set(pid: int) -> int:
    """进程工作集大小（字节），失败返回 0。"""
    k32 = _kernel32()
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0
    try:
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.restype = wt.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p,
                                               ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                               wt.DWORD]
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize)
        return 0
    finally:
        k32.CloseHandle(h)


def _close_window(hwnd: int) -> None:
    """发送 WM_CLOSE 关闭窗口（正常关闭流程）。"""
    try:
        _user32().PostMessageW(hwnd, WM_CLOSE, 0, 0)
    except Exception:
        pass


def _select_main_hwnd(pids: List[int]):
    """从微信可见窗口中选出唯一主窗口句柄。

    优先：标题含「微信」的主窗口；若多个，取内存占用最大者。
    返回 hwnd 或 None。
    """
    wins = [(h, t, v, p) for h, t, v, p in _windows_for_pids(pids) if v]
    if not wins:
        return None
    mains = [w for w in wins if '微信' in w[1] or 'wechat' in w[1].lower()]
    pool = mains if mains else wins
    # 按进程工作集降序取最大
    best = max(pool, key=lambda w: _process_working_set(w[3]))
    return best[0]


def _close_redundant_windows(pids: List[int]) -> List[str]:
    """确保只剩一个微信主窗口：关闭多余可见 Weixin 窗口与全部可见 WeChatAppEx。

    返回日志列表。
    """
    logs = []
    if not pids:
        return logs
    # 1) 微信主窗口：保留唯一主窗口，其余可见窗口关闭
    wins = [(h, t, v, p) for h, t, v, p in _windows_for_pids(pids) if v]
    if len(wins) > 1:
        keep = _select_main_hwnd(pids)
        if keep:
            for h, t, v, p in wins:
                if h != keep:
                    _close_window(h)
                    logs.append(f"关闭多余微信窗口 #{h} ({t})")
            logs.append(f"保留主窗口 #{keep} ")
    # 2) 关闭可见 WeChatAppEx（小程序容器，避免干扰）
    appex_pids = _pids_by_exe([WECHAT_APPEX])
    for h, t, v, p in _windows_for_pids(appex_pids):
        if v:
            _close_window(h)
            logs.append(f"关闭 WeChatAppEx 窗口 #{h}")
    return logs


def _verify_left_half(hwnd: int, half_w: int) -> bool:
    """校验窗口是否就位于左半屏（左缘≈0 且 宽度≈半屏）。"""
    r = wt.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return abs(r.left) <= 2 and abs((r.right - r.left) - half_w) <= 2


def get_window_width(hwnd: int = None) -> int:
    """读取微信主窗口当前宽度（px）；无主窗口返回 0。"""
    if hwnd is None:
        pids = _wechat_pids()
        if not pids:
            return 0
        hwnd = _find_main_hwnd(pids)
    if not hwnd:
        return 0
    r = wt.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return r.right - r.left


_CHILDPROC_T = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def has_embedded_page(hwnd: int = None) -> bool:
    """检测微信主窗口内是否嵌入了独立渲染页面（如「搜一搜」）。

    原理（零依赖、毫秒级）：微信 4.x 主界面无 Chrome_RenderWidgetHostHWND；
    嵌入的 web 页面（搜一搜等）会新建该渲染宿主子窗口。
    实测：正常聊天 = 0 个、搜一搜嵌入页 = 1 个。
    """
    if hwnd is None:
        pids = _wechat_pids()
        if not pids:
            return False
        hwnd = _find_main_hwnd(pids)
    if not hwnd:
        return False
    found = []
    u32 = _user32()

    def cb(h, lp):
        buf = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, buf, 64)
        if buf.value == 'Chrome_RenderWidgetHostHWND':
            found.append(h)
        return True

    try:
        u32.EnumChildWindows(wt.HWND(hwnd), _CHILDPROC_T(cb), 0)
    except Exception:
        return False
    return bool(found)


# 点击第一联系人后，出现即判失败的额外可见窗口标题关键词
FAIL_EXTRA_TITLES = ("搜一搜", "添加朋友", "添加好友", "搜索网络")


def _window_area(hwnd: int) -> int:
    """窗口面积（宽×高），失败返回 0。"""
    r = wt.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return max(0, r.right - r.left) * max(0, r.bottom - r.top)


def _find_main_hwnd_from(pids: List[int]) -> Optional[int]:
    """从微信进程可见窗口中选主窗口：标题含「微信」，若多个取面积最大。"""
    mains = [w for w in _windows_for_pids(pids)
             if w[2] and ('微信' in w[1] or 'wechat' in w[1].lower())]
    if not mains:
        return None
    return max(mains, key=lambda w: _window_area(w[0]))[0]


def extra_visible_windows(exclude_main=True) -> list:
    """枚举微信相关的所有额外可见窗口（非主窗口）。

    主窗口 = 可见 + 标题含「微信」+ 面积最大（弹出的小窗标题也可能是「微信」）。
    覆盖：Weixin 进程的非主窗口 + WeChatAppEx 进程可见窗口。
    返回 [(hwnd, title), ...]
    """
    out = []
    pids = _wechat_pids()
    main_hwnd = _find_main_hwnd_from(pids) if (pids and exclude_main) else None
    for h, t, v, p in _windows_for_pids(pids):
        if not v:
            continue
        if main_hwnd is not None and h == main_hwnd:
            continue
        out.append((h, t))
    for h, t, v, p in _windows_for_pids(_pids_by_exe([WECHAT_APPEX])):
        if v:
            out.append((h, t))
    return out


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
# 窗口初始化：前置主窗口并移动到左半屏
# ---------------------------------------------------------------------------
SW_RESTORE = 9
SW_SHOW = 5
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
SPI_GETWORKAREA = 0x0030
VK_MENU = 0x12


def _find_main_hwnd(pids: List[int]):
    """找微信主窗口句柄：可见 + 标题含「微信」/「WeChat」，若多个取面积最大。"""
    if not pids:
        return None
    return _find_main_hwnd_from(pids)


def _force_foreground(hwnd):
    """绕过 Windows 前台锁定，把窗口强制带到最顶层。"""
    import time
    u32 = _user32()
    u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    # 按住再松开 Alt，规避前台锁定限制（finally 兜底释放，防 Alt 卡住）
    try:
        _keybd_event(VK_MENU, 0, 0, 0)
        _keybd_event(VK_MENU, 0, 2, 0)  # KEYEVENTF_KEYUP
        u32.SetForegroundWindow(hwnd)
    finally:
        _keybd_event(VK_MENU, 0, 2, 0)  # 保险再抬一次
        time.sleep(0.05)
    u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.15)


def _keybd_event(vk, scancode, flags, extra):
    """模拟按键（绕过前台锁定需要）。"""
    ctypes.windll.user32.keybd_event(vk, scancode, flags, extra)


def _work_area() -> Optional[Tuple[int, int, int, int]]:
    """系统工作区（不含任务栏）: (x1, y1, x2, y2)。"""
    r = wt.RECT()
    ok = _user32().SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    if not ok:
        return None
    return (r.left, r.top, r.right, r.bottom)


def _move_to_left_half(hwnd) -> bool:
    """把窗口移动到左半屏（尺寸 = 工作区一半宽 × 满高）。"""
    import time
    u32 = _user32()
    area = _work_area()
    if not area:
        return False
    x1, y1, x2, y2 = area
    w, h = (x2 - x1) // 2, y2 - y1
    u32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.1)
    u32.SetWindowPos(hwnd, HWND_TOP, x1, y1, w, h, SWP_SHOWWINDOW | SWP_NOACTIVATE)
    time.sleep(0.2)
    # 复查未生效则重试一次（部分窗口拒绝首次移动）
    rect = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    if abs(rect.left - x1) > 2 or abs(rect.top - y1) > 2:
        u32.SetWindowPos(hwnd, HWND_TOP, x1, y1, w, h, SWP_SHOWWINDOW | SWP_NOACTIVATE)
        time.sleep(0.2)
    return True


def init_wechat_window() -> dict:
    """微信窗口初始化（健壮版）：确保**唯一**微信主窗口前置并位于左半屏。

    步骤：
        0) 若内嵌「搜一搜」页：点击点位4（分离按钮）先关闭嵌入页
        1) 关闭多余可见 Weixin 窗口（按标题/面积保留唯一主窗口）
        2) 关闭可见 WeChatAppEx 窗口（避免干扰）
        3) 唤出微信主窗口（恢复/显示/前置）
        4) 移动到左半屏（半屏宽 × 工作区满高）
        5) 校验是否就位（left≈0 且 宽≈半屏）；不合法重试一次

    返回: {"ok": bool, "code": str, "message": str}
        code: OK / OK_DEGRADED / ERR_NO_WECHAT / ERR_NO_MAIN_WINDOW / ERR_MOVE_FAILED / ERR_INTERNAL
    """
    if has_embedded_page():
        try:
            import points
            import wechat_input
            pt = points.get_point("search_split_button")
            if pt:
                for _i in range(2):
                    wechat_input.mouse_click(pt["x"], pt["y"], wait_after=0.8)
                    if not has_embedded_page():
                        break
        except Exception:
            pass
    import time
    logs = []

    def once() -> (bool, str):
        # 单次初始化
        pids = _wechat_pids()
        if not pids:
            return False, "微信未运行"
        logs.extend(_close_redundant_windows(pids))
        hwnd = _find_main_hwnd(pids)
        if not hwnd:
            # 兜底：按进程找任意可见窗口唤出
            wins = [(h, t, v, p) for h, t, v, p in _windows_for_pids(pids)]
            if wins:
                hwnd = wins[0][0]
                logs.append(f"兜底唤出窗口 #{hwnd}")
        if not hwnd:
            return False, "未找到微信主窗口（可能尚未打开主界面）"
        # 唤出并前置
        u32 = _user32()
        u32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
        u32.ShowWindow(hwnd, SW_SHOW)
        time.sleep(0.1)
        _force_foreground(hwnd)
        # 移动到左半屏
        area = _work_area()
        if not area:
            return False, "获取工作区失败"
        x1, y1, x2, y2 = area
        half_w = (x2 - x1) // 2
        _move_to_left_half(hwnd)
        if _verify_left_half(hwnd, half_w):
            logs.append(f"主窗口 #{hwnd} 已就位左半屏 ({half_w}px)")
            return True, "; ".join(logs)
        return False, f"主窗口 #{hwnd} 未就位左半屏"

    ok, info = once()
    if ok:
        return {"ok": True, "code": "OK", "message": info}
    # 左半屏未就位：重试一次，仍失败则降级（不阻塞任务）——
    # 只要微信主窗口可见即可继续，宽度由用户布局决定
    time.sleep(0.5)
    ok2, info2 = once()
    if ok2:
        return {"ok": True, "code": "OK", "message": info2}
    pids = _wechat_pids()
    hwnd = _find_main_hwnd(pids) if pids else None
    if hwnd:
        return {"ok": True, "code": "OK_DEGRADED",
                "message": f"主窗口已前置可见（左半屏未就位: {info2}，降级继续）"}
    return {"ok": False, "code": "ERR_NO_MAIN_WINDOW",
            "message": f"找不到微信主窗口: {info2}"}


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