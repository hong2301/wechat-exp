# -*- coding: utf-8 -*-
"""
wechat_input — 输入模块（点击 / 键盘输入 / 剪贴板粘贴）
========================================================
提供微信自动化操作所需的鼠标与键盘输入方法（纯标准库 ctypes）。

方法：
    mouse_click(x, y, hold_ms=80)    鼠标左键点击指定坐标
    type_text(text, char_delay=0.01) SendInput UNICODE 逐字符输入（支持中文）
    paste_text(text)                 写入剪贴板并 Ctrl+V 粘贴（长文本/特殊字符更稳）
    ctrl_key(letter)                 发送 Ctrl+字母 组合键
    key_press(vk)                    发送单键（如回车 VK_RETURN=0x0D）
"""
import ctypes
import ctypes.wintypes as wt
import time

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_DELETE = 0x2E
VK_A = 0x41
VK_V = 0x56
VK_BACK = 0x08
VK_END = 0x23
VK_ESCAPE = 0x1B
VK_DOWN = 0x28
VK_UP = 0x26
VK_SHIFT = 0x10
VK_MENU = 0x12      # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SETFOCUS = 0x0007
MK_LBUTTON = 0x0001

# ---------------------------------------------------------------------------
# 窗口级投递（PostMessage 直达微信窗口，不依赖系统焦点）
# 用途：Deskflow/远程键鼠切走时，系统级注入可能失效，
#       窗口级投递仍能直接操作微信窗口。
# ---------------------------------------------------------------------------

def _target_window():
    """获取微信主窗口句柄（供窗口级操作）。"""
    import wechat_status as ws
    return ws._find_main_hwnd(ws._wechat_pids())


def _target_window():
    """获取微信主窗口句柄（供窗口级操作）。"""
    import wechat_status as ws
    return ws._find_main_hwnd(ws._wechat_pids())


def _dropdown_window():
    """获取微信搜索下拉列表窗口（Qt 可见窗口，title='Weixin'）。

    搜索框聚焦后微信会弹出独立的 Qt 下拉窗口（368x802 左右），
    输入与“第一联系人”点击都在该窗口内进行；无下拉时返回 None。
    """
    import wechat_status as ws
    for h, t, v, p in ws._windows_for_pids(ws._wechat_pids()):
        if v and t.strip() == 'Weixin':
            return h
    return None


def _active_input_target():
    """输入目标：优先搜索下拉窗口，无则主窗口。"""
    return _dropdown_window() or _target_window()


# 点位采集时微信窗口的基准尺寸（点位均按此布局录制）
BASE_W, BASE_H = 768, 864


def adapt_client_pt(x, y, hwnd=None):
    """点位自适应：按 当前窗口尺寸/基准尺寸 等比换算客户区坐标。

    解决窗口被拉伸/缩放（Deskflow、用户拖动）后点位错位问题。
    输入为点位录制时的屏幕坐标（录制时窗口位于左上角 0,0）。
    返回 (client_x, client_y)。
    """
    if hwnd is None:
        hwnd = _target_window()
    r = wt.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    cur_w = max(r.right - r.left, 1)
    cur_h = max(r.bottom - r.top, 1)
    cx = max(0, min(cur_w, (int(x) - r.left) * cur_w // BASE_W))
    cy = max(0, min(cur_h, (int(y) - r.top) * cur_h // BASE_H))
    return cx, cy


def adapt_screen_pt(x, y, hwnd=None):
    """点位自适应（屏幕坐标版）：用于系统级 SetCursorPos。"""
    if hwnd is None:
        hwnd = _target_window()
    r = wt.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    cur_w = max(r.right - r.left, 1)
    cur_h = max(r.bottom - r.top, 1)
    sx = r.left + (int(x) - r.left) * cur_w // BASE_W
    sy = r.top + (int(y) - r.top) * cur_h // BASE_H
    return sx, sy


def post_click(x, y, hwnd=None):
    """窗口内点击（点位自适应 → 客户区坐标 → PostMessage）。"""
    try:
        u32 = _user32()
        if hwnd is None:
            hwnd = _target_window()
        if not hwnd:
            return {"ok": False, "code": "ERR_NO_WINDOW", "message": "未找到微信主窗口"}
        if hwnd is None:
            # 默认主窗口：按基础尺寸比例自适应
            cx, cy = adapt_client_pt(x, y, hwnd)
        else:
            # 指定窗口（如搜索下拉窗口）：直接屏幕坐标→客户区（独立窗口不缩放）
            pt0 = wt.POINT(int(x), int(y))
            u32.ScreenToClient(hwnd, ctypes.byref(pt0))
            cx, cy = pt0.x, pt0.y
        lp = (cy & 0xFFFF) << 16 | (cx & 0xFFFF)
        u32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.05)
        u32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        u32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
        # 让 Chromium 编辑框获得键盘焦点（无系统焦点时的关键一步）
        u32.SendMessageW.restype = ctypes.c_ssize_t
        u32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t,
                                     ctypes.c_ssize_t]
        u32.SendMessageW(hwnd, WM_SETFOCUS, 0, 0)
        time.sleep(0.1)
        return {"ok": True, "code": "OK",
                "message": f"窗口内点击 ({x}, {y}) → 客户区 ({cx}, {cy})"}
    except Exception as e:
        return {"ok": False, "code": "ERR_POST",
                "message": f"窗口点击失败: {type(e).__name__}: {e}"}


def post_text(text, hwnd=None, char_delay=0.02):
    """窗口内输入文本（同步 SendMessage 击键投递，支持中文）。

    每字符发送 WM_KEYDOWN(0)+WM_CHAR(码点)+WM_KEYUP(0)，lParam 为标准击键格式
    （repeat=1, scan, prev/transition 标志），比异步 PostMessage 更可靠。
    返回: {"ok", "code", "message"}
    """
    try:
        u32 = _user32()
        if hwnd is None:
            hwnd = _target_window()   # 输入/键盘一律投主窗口（搜索框在主窗口；下拉仅显示）
        if not hwnd:
            return {"ok": False, "code": "ERR_NO_WINDOW", "message": "未找到微信主窗口"}
        u32.SendMessageW.restype = ctypes.c_ssize_t
        u32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t,
                                     ctypes.c_ssize_t]
        for ch in str(text):
            scan = ord(ch) & 0xFF
            lparam_down = 1 | (scan << 16)
            lparam_char = 1 | (scan << 16)
            lparam_up = 1 | 0xC0000000 | (scan << 16)   # prev+transition
            u32.SendMessageW(hwnd, WM_KEYDOWN, 0, lparam_down)
            u32.SendMessageW(hwnd, WM_CHAR, ord(ch), lparam_char)
            u32.SendMessageW(hwnd, WM_KEYUP, 0, lparam_up)
            if char_delay:
                time.sleep(char_delay)
        return {"ok": True, "code": "OK",
                "message": f"窗口内输入 {len(str(text))} 字符"}
    except Exception as e:
        return {"ok": False, "code": "ERR_POST",
                "message": f"窗口输入失败: {type(e).__name__}: {e}"}


def post_key(vk, hwnd=None, wait=0.06):
    """窗口内按键（按下+抬起）。"""
    try:
        u32 = _user32()
        if hwnd is None:
            hwnd = _target_window()   # 输入/键盘一律投主窗口（搜索框在主窗口；下拉仅显示）
        if not hwnd:
            return {"ok": False, "code": "ERR_NO_WINDOW", "message": "未找到微信主窗口"}
        u32.PostMessageW(hwnd, WM_KEYDOWN, vk, 1)
        if wait:
            time.sleep(wait)
        u32.PostMessageW(hwnd, WM_KEYUP, vk, 1)
        time.sleep(0.05)
        return {"ok": True, "code": "OK", "message": f"窗口内按键 0x{vk:x}"}
    except Exception as e:
        return {"ok": False, "code": "ERR_POST",
                "message": f"窗口按键失败: {type(e).__name__}: {e}"}


def post_clear(hwnd=None, max_backspaces=60):
    """窗口内清空输入框（同步击键流：End + 多次 Backspace）。

    只依赖窗口消息，不要求系统焦点；Backspace 用 WM_KEYDOWN 而非 WM_CHAR
    （Chromium 对 WM_CHAR backspace 兼容性差）。
    """
    try:
        u32 = _user32()
        if hwnd is None:
            hwnd = _target_window()   # 输入/键盘一律投主窗口（搜索框在主窗口；下拉仅显示）
        if not hwnd:
            return {"ok": False, "code": "ERR_NO_WINDOW", "message": "未找到微信主窗口"}
        u32.SendMessageW.restype = ctypes.c_ssize_t
        u32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t,
                                     ctypes.c_ssize_t]

        def _key(vk, flags=0):
            lp = (1 | (flags << 30))  # repeat=1; flags: 2=transition
            u32.SendMessageW(hwnd, WM_KEYDOWN if not flags else WM_KEYUP,
                             vk, lp)

        # 光标到末尾
        _key(VK_END, 0)
        _key(VK_END, 2)
        time.sleep(0.05)
        # 连续 Backspace 清空
        for _i in range(max_backspaces):
            _key(VK_BACK, 0)
            _key(VK_BACK, 2)
            time.sleep(0.012)
        time.sleep(0.1)
        return {"ok": True, "code": "OK",
                "message": f"窗口内清空输入框 (End+BS×{max_backspaces})"}
    except Exception as e:
        return {"ok": False, "code": "ERR_POST",
                "message": f"窗口清空失败: {type(e).__name__}: {e}"}

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", INPUTUNION)]


def _user32():
    u32 = ctypes.windll.user32
    # 键盘/鼠标
    u32.SendInput.restype = wt.UINT
    u32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    # 剪贴板（关键：句柄类必须显式声明，否则 64 位句柄被截断）
    u32.OpenClipboard.restype = wt.BOOL
    u32.OpenClipboard.argtypes = [wt.HWND]
    u32.EmptyClipboard.restype = wt.BOOL
    u32.CloseClipboard.restype = wt.BOOL
    u32.SetClipboardData.restype = ctypes.c_void_p
    u32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
    u32.GetClipboardData.restype = ctypes.c_void_p
    u32.GetClipboardData.argtypes = [wt.UINT]
    return u32


def _kernel32():
    k32 = ctypes.windll.kernel32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.restype = wt.BOOL
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    return k32


# ---------------------------------------------------------------------------
# 鼠标点击
# ---------------------------------------------------------------------------
def mouse_click(x, y, hold_ms=80, wait_after=0):
    """左键点击指定屏幕坐标。

    参数：
        x, y        坐标
        hold_ms     按住时长（毫秒，模拟人手按压，默认 80）
        wait_after  点击后等待秒数
    返回: {"ok": bool, "code": str, "message": str}
    """
    try:
        u32 = _user32()
        # 点位为采集时的真实屏幕坐标。open_chat 流程每次先 init_wechat_window
        # 把窗口摆回采集时的左半屏布局，直接用原始坐标最准。
        # （旧版按固定基准 768×864 等比缩放，本机 640px 半屏下 113→94 点偏）
        sx, sy = int(x), int(y)
        u32.SetCursorPos(sx, sy)
        time.sleep(0.05)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        if hold_ms:
            time.sleep(hold_ms / 1000.0)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
        if wait_after:
            time.sleep(wait_after)
        return {"ok": True, "code": "OK",
                "message": f"已点击 ({sx}, {sy})"}
    except Exception as e:
        return {"ok": False, "code": "ERR_CLICK",
                "message": f"点击失败: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 键盘输入
# ---------------------------------------------------------------------------
def _send_keys(entries):
    """批量发送按键事件（SendInput）。entries = [(vk, scan, flags), ...]"""
    u32 = _user32()
    arr = (INPUT * len(entries))()
    for i, (vk, scan, flags) in enumerate(entries):
        ki = KEYBDINPUT()
        ki.wVk = vk
        ki.wScan = scan
        ki.dwFlags = flags
        u = INPUTUNION()
        u.ki = ki
        arr[i].type = INPUT_KEYBOARD
        arr[i].u = u
    sent = u32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))
    return sent


def type_text(text, char_delay=0.01):
    """SendInput UNICODE 逐字符输入（支持任意字符含中文）。

    返回: {"ok", "code", "message"}
    """
    try:
        text = str(text)
        if not text:
            return {"ok": False, "code": "ERR_EMPTY", "message": "输入文本为空"}
        entries = []
        for ch in text:
            entries.append((0, ord(ch), KEYEVENTF_UNICODE))
            entries.append((0, ord(ch), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        sent = _send_keys(entries)
        if sent != len(entries):
            return {"ok": False, "code": "ERR_SENDINPUT",
                    f"message": f"SendInput 部分发送 ({sent}/{len(entries)})"}
        if char_delay:
            time.sleep(char_delay * len(text))
        return {"ok": True, "code": "OK", "message": f"已输入 {len(text)} 字符"}
    except Exception as e:
        return {"ok": False, "code": "ERR_INPUT",
                "message": f"输入失败: {type(e).__name__}: {e}"}


def release_modifiers():
    """兜底释放所有修饰键（Ctrl/Shift/Alt/Win），防止注入中断导致按键卡住。"""
    try:
        _send_keys([(VK_CONTROL, 0, KEYEVENTF_KEYUP),
                    (VK_SHIFT, 0, KEYEVENTF_KEYUP),
                    (VK_MENU, 0, KEYEVENTF_KEYUP),
                    (VK_LWIN, 0, KEYEVENTF_KEYUP),
                    (VK_RWIN, 0, KEYEVENTF_KEYUP)])
    except Exception:
        pass


def ctrl_key(letter):
    """发送 Ctrl+字母 组合键（无论成败都兜底释放修饰键，避免 Ctrl 卡住）。

    返回: {"ok", "code", "message"}
    """
    try:
        vk = ord(str(letter).upper())
        sent = _send_keys([(VK_CONTROL, 0, 0),
                           (vk, 0, 0),
                           (vk, 0, KEYEVENTF_KEYUP),
                           (VK_CONTROL, 0, KEYEVENTF_KEYUP)])
        time.sleep(0.1)
        if sent != 4:
            return {"ok": False, "code": "ERR_SENDINPUT",
                    "message": f"SendInput 部分发送 ({sent}/4)"}
        return {"ok": True, "code": "OK", "message": f"已发送 Ctrl+{str(letter).upper()}"}
    except Exception as e:
        return {"ok": False, "code": "ERR_INPUT",
                "message": f"组合键失败: {type(e).__name__}: {e}"}
    finally:
        release_modifiers()
        time.sleep(0.02)


def key_press(vk):
    """发送单键（如回车 VK_RETURN=0x0D）。

    返回: {"ok", "code", "message"}
    """
    try:
        sent = _send_keys([(vk, 0, 0), (vk, 0, KEYEVENTF_KEYUP)])
        time.sleep(0.1)
        if sent != 2:
            return {"ok": False, "code": "ERR_SENDINPUT",
                    "message": f"SendInput 部分发送 ({sent}/2)"}
        return {"ok": True, "code": "OK", "message": f"已发送按键 VK=0x{vk:x}"}
    except Exception as e:
        return {"ok": False, "code": "ERR_INPUT",
                "message": f"按键失败: {type(e).__name__}: {e}"}


def clear_input():
    """清空当前焦点输入框内容（Ctrl+A 全选 + Delete）。

    用于每次输入前清空，避免上次内容残留。
    返回: {"ok", "code", "message"}
    """
    try:
        ctrl_key("A")
        time.sleep(0.1)
        key_press(VK_DELETE)
        return {"ok": True, "code": "OK", "message": "已清空输入框"}
    except Exception as e:
        return {"ok": False, "code": "ERR_CLEAR",
                "message": f"清空失败: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 剪贴板粘贴
# ---------------------------------------------------------------------------
def mark_clipboard_private(u32=None):
    """标记当前剪贴板内容“不进入历史/云同步”（保持用户 Win+V 历史不受干扰）。

    写入两个 Windows 注册格式：
      - CanIncludeInClipboardHistory = 0   （不记入 Win+V 剪贴板历史）
      - ExcludeClipboardContentFromMonitorProcessing = 0 （不参与同步/监控）
    需在 OpenClipboard 会话内调用。
    """
    if u32 is None:
        u32 = _user32()
    k32 = _kernel32()
    for name in ("CanIncludeInClipboardHistory",
                 "ExcludeClipboardContentFromMonitorProcessing",
                 "Clipboard Viewer Ignore"):   # Deskflow/Synergy 等同步软件据此跳过
        try:
            fmt = u32.RegisterClipboardFormatW(name)
            if not fmt:
                continue
            h = k32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, 4)
            if not h:
                continue
            p = k32.GlobalLock(h)
            if p:
                ctypes.cast(p, ctypes.POINTER(ctypes.c_uint32))[0] = 0
                k32.GlobalUnlock(h)
                if u32.SetClipboardData(fmt, h):
                    continue
            k32.GlobalFree(h)
        except Exception:
            continue


def set_clipboard_text(text):
    """把文本写入剪贴板（CF_UNICODETEXT），并标记不进历史/同步。成功返回 True。"""
    u32 = _user32()
    k32 = _kernel32()
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        data = (str(text) + "\x00").encode("utf-16-le")
        h = k32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        try:
            ctypes.memmove(p, data, len(data))
        finally:
            k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            k32.GlobalFree(h)
            return False
        mark_clipboard_private(u32)   # 不进 Win+V 历史、不参与同步
        return True
    finally:
        u32.CloseClipboard()


def paste_text(text):
    """写入剪贴板并 Ctrl+V 粘贴（长文本/特殊符号更稳）。

    返回: {"ok", "code", "message"}
    """
    if not set_clipboard_text(text):
        return {"ok": False, "code": "ERR_CLIPBOARD", "message": "剪贴板写入失败"}
    time.sleep(0.05)
    ctrl_key("V")
    return {"ok": True, "code": "OK", "message": f"已粘贴 {len(str(text))} 字符"}


# ---------------------------------------------------------------------------
# CLI 便捷（python my_automation/wechat_input.py --click 100 200）
# ---------------------------------------------------------------------------
def main():
    import sys
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == '--click':
        print(mouse_click(int(args[1]), int(args[2])))
    elif len(args) >= 2 and args[0] == '--type':
        print(type_text(args[1]))
    elif len(args) >= 2 and args[0] == '--paste':
        print(paste_text(args[1]))
    else:
        print("用法: python my_automation/wechat_input.py --click X Y | --type 文本 | --paste 文本")


if __name__ == '__main__':
    main()