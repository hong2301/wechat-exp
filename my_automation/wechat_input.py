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
        u32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        if hold_ms:
            time.sleep(hold_ms / 1000.0)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
        if wait_after:
            time.sleep(wait_after)
        return {"ok": True, "code": "OK",
                "message": f"已点击 ({x}, {y})"}
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


def ctrl_key(letter):
    """发送 Ctrl+字母 组合键。"""
    vk = ord(str(letter).upper())
    _send_keys([(VK_CONTROL, 0, 0),
                (vk, 0, 0),
                (vk, 0, KEYEVENTF_KEYUP),
                (VK_CONTROL, 0, KEYEVENTF_KEYUP)])
    time.sleep(0.1)


def key_press(vk):
    """发送单键（如回车 VK_RETURN=0x0D）。"""
    _send_keys([(vk, 0, 0), (vk, 0, KEYEVENTF_KEYUP)])
    time.sleep(0.1)


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
def set_clipboard_text(text):
    """把文本写入剪贴板（CF_UNICODETEXT）。成功返回 True。"""
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
        u32.SetClipboardData(CF_UNICODETEXT, h)
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