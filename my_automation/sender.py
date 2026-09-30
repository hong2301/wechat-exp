# -*- coding: utf-8 -*-
"""
sender — 聊天输入模块（剪贴板备份→置入→粘贴→恢复）
=====================================================
向微信聊天输入框粘贴内容（文字 / 文件）。

设计（用户需求）：
    “内容存在剪贴板的倒数一位，不影响系统平时使用” ——
    1. 粘贴前 **备份**当前剪贴板内容（文本 / 文件列表）
    2. 将我们的内容 **置入**剪贴板（成为当前/最后一位）
    3. Ctrl+V 粘贴到微信聊天输入框
    4. 用后立即 **恢复**用户原本的剪贴板内容
    效果：自动化粘贴不改变用户日常剪贴板使用体验。

方法：
    paste_text_to_chat(text)        粘贴文本到聊天输入框
    paste_files_to_chat(paths)      粘贴文件列表到聊天输入框
    send_message(content, send=True) 组合：粘贴内容，send=True 时按回车发送

返回统一 {"ok": bool, "code": str, "message": str}
"""
import ctypes
import ctypes.wintypes as wt
import os
import time

import wechat_input as wi

# ---------------------------------------------------------------------------
# 剪贴板常量 / 结构
# ---------------------------------------------------------------------------
CF_UNICODETEXT = 13
CF_HDROP = 15

GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

GHND = GMEM_MOVEABLE | GMEM_ZEROINIT

VK_RETURN = 0x0D


class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wt.DWORD),
        ("pt", wt.POINT),
        ("fNC", wt.BOOL),
        ("fWide", wt.BOOL),
    ]


def _user32():
    # sender 复用 wechat_input 的签名设置（含句柄声明），仅再取函数
    return wi._user32()


def _kernel32():
    return wi._kernel32()


def _shell32():
    sh = ctypes.windll.shell32
    sh.DragQueryFileW.restype = wt.UINT
    sh.DragQueryFileW.argtypes = [ctypes.c_void_p, wt.UINT,
                                  ctypes.c_wchar_p, wt.UINT]
    return sh


# ---------------------------------------------------------------------------
# 剪贴板读写（文本 / 文件）
# ---------------------------------------------------------------------------
def _read_clipboard_text():
    """读取当前剪贴板文本；无文本返回 None。"""
    u32 = _user32()
    k32 = _kernel32()
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def _read_clipboard_files():
    """读取当前剪贴板文件列表；无文件返回 None。"""
    u32 = _user32()
    sh = _shell32()
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(CF_HDROP)
        if not h:
            return None
        out = []
        count = sh.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
        for i in range(count):
            n = sh.DragQueryFileW(h, i, None, 0)
            buf = ctypes.create_unicode_buffer(n + 1)
            sh.DragQueryFileW(h, i, buf, n + 1)
            out.append(buf.value)
        return out
    finally:
        u32.CloseClipboard()


def _set_clipboard_text(text):
    """写入剪贴板文本。"""
    return wi.set_clipboard_text(text)


def _set_clipboard_files(paths):
    """写入剪贴板文件列表（CF_HDROP 结构）。"""
    k32 = _kernel32()
    u32 = _user32()
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        # 组装 DROPFILES + 文件路径（utf-16，\0 分隔，结尾双 \0）
        header = ctypes.sizeof(DROPFILES)
        items = [os.path.abspath(p) for p in paths if os.path.exists(p)]
        if not items:
            return False
        payload = b"".join((p + "\x00").encode("utf-16-le") for p in items) + b"\x00\x00"
        total = header + len(payload)
        h = k32.GlobalAlloc(GHND, total)
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        try:
            df = DROPFILES()
            df.pFiles = header
            df.fWide = True
            ctypes.memmove(p, ctypes.byref(df), header)
            ctypes.memmove(p + header, payload, len(payload))
        finally:
            k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_HDROP, h)
        return True
    finally:
        u32.CloseClipboard()


class _ClipboardBackup:
    """备份/恢复剪贴板内容（文本 + 文件列表）。"""

    def __init__(self):
        self.text = None
        self.files = None

    def save(self):
        self.text = _read_clipboard_text()
        self.files = _read_clipboard_files()

    def restore(self):
        # 恢复优先级：文件 > 文本（原样还原）
        if self.files is not None:
            _set_clipboard_files(self.files)
        elif self.text is not None:
            _set_clipboard_text(self.text)
        else:
            try:
                _user32().OpenClipboard(None)
                _user32().EmptyClipboard()
                _user32().CloseClipboard()
            except Exception:
                pass


def _paste_from_clipboard():
    """Ctrl+V 粘贴（当前剪贴板内容 → 焦点窗口）。"""
    wi.ctrl_key("V")
    time.sleep(0.3)


# ---------------------------------------------------------------------------
# 对外方法
# ---------------------------------------------------------------------------
def _focus_and_clear_input(window_mode=False) -> dict:
    """点击聊天输入框并清空内容（每次输入前调用）。

    系统级：mouse_click(chat_input) + Ctrl+A+Delete
    窗口级：post_click(chat_input) + 窗口内清空
    """
    import points
    pt = points.get_point("chat_input")
    if not pt:
        return {"ok": False, "code": "ERR_NO_POINT",
                "message": "缺少点位 chat_input"}
    if window_mode:
        wi.post_click(pt["x"], pt["y"])
        r = wi.post_clear()
    else:
        wi.mouse_click(pt["x"], pt["y"], wait_after=0.2)
        r = wi.clear_input()
    if not r["ok"]:
        return r
    return {"ok": True, "code": "OK", "message": "聊天输入框已清空"}


def paste_text_to_chat(text: str) -> dict:
    """粘贴文本到微信聊天输入框（临时借用剪贴板，用后恢复）。"""
    text = str(text)
    if not text.strip():
        return {"ok": False, "code": "ERR_EMPTY", "message": "文本为空"}
    r = _focus_and_clear_input(window_mode=False)
    if not r["ok"]:
        return r
    backup = _ClipboardBackup()
    backup.save()
    try:
        if not _set_clipboard_text(text):
            return {"ok": False, "code": "ERR_CLIPBOARD", "message": "剪贴板写入失败"}
        _paste_from_clipboard()
        return {"ok": True, "code": "OK",
                "message": f"已粘贴 {len(text)} 字符到聊天输入框"}
    finally:
        backup.restore()


def paste_files_to_chat(paths) -> dict:
    """粘贴文件（支持多个）到微信聊天输入框（临时借用剪贴板，用后恢复）。"""
    paths = [str(p) for p in (paths or [])]
    if not paths:
        return {"ok": False, "code": "ERR_EMPTY", "message": "文件列表为空"}
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        return {"ok": False, "code": "ERR_NO_FILE",
                "message": f"文件不存在: {missing[0]}"}
    backup = _ClipboardBackup()
    backup.save()
    try:
        if not _set_clipboard_files(paths):
            return {"ok": False, "code": "ERR_CLIPBOARD", "message": "剪贴板写入失败"}
        _paste_from_clipboard()
        return {"ok": True, "code": "OK",
                "message": f"已粘贴 {len(paths)} 个文件到聊天输入框"}
    finally:
        backup.restore()


def send_message(content, send=True) -> dict:
    """发送消息：粘贴内容（文本或文件路径）到输入框；send=True 时回车发送。

    content 为 str：粘贴为文本（若指向存在的文件，则按文件粘贴）
    content 为 list/tuple：作为文件列表粘贴
    """
    if isinstance(content, (list, tuple)):
        r = paste_files_to_chat(content)
    elif isinstance(content, str) and os.path.exists(content):
        r = paste_files_to_chat([content])
    else:
        r = paste_text_to_chat(content)
    if not r["ok"] or not send:
        return r
    wi.key_press(VK_RETURN)   # 回车发送
    time.sleep(0.3)
    r["message"] += "，已回车发送"
    return r


def send_text_window(text: str, hwnd=None) -> dict:
    """窗口级发送文本（PostMessage 投递，不依赖系统焦点；支持 Deskflow 场景）。

    流程：点击聊天输入框 → 清空内容 → 输入文本 → 回车发送。
    仅支持文本；文件粘贴依赖剪贴板+系统焦点，请使用 send_message。
    """
    text = str(text)
    if not text.strip():
        return {"ok": False, "code": "ERR_EMPTY", "message": "文本为空"}
    r = _focus_and_clear_input(window_mode=True)
    if not r["ok"]:
        return r
    r = wi.post_text(text, hwnd=hwnd)
    if not r["ok"]:
        return r
    r2 = wi.post_key(wi.VK_RETURN, hwnd=hwnd)
    if not r2["ok"]:
        return r2
    return {"ok": True, "code": "OK",
            "message": f"窗口级输入 {len(text)} 字符并回车发送"}


# ---------------------------------------------------------------------------
# CLI：python my_automation/sender.py --text 你好 | --file 路径 | --send-msg 内容
# ---------------------------------------------------------------------------
def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="my_automation.sender", description="聊天输入")
    ap.add_argument("--text", help="粘贴文本")
    ap.add_argument("--file", action="append", default=[], help="粘贴文件(可多个)")
    ap.add_argument("--send-msg", help="粘贴并回车发送")
    ap.add_argument("--no-restore", action="store_true", help="粘贴后不恢复剪贴板(调试)")
    args = ap.parse_args()

    if args.send_msg:
        r = send_message(args.send_msg)
    elif args.text:
        r = paste_text_to_chat(args.text)
    elif args.file:
        r = paste_files_to_chat(args.file)
    else:
        print("用法: --text 文本 | --file 路径... | --send-msg 内容")
        return
    print("=" * 56)
    print(f"结果: {'成功' if r['ok'] else '失败'}  [错误码: {r['code']}]")
    print(f"说明: {r['message']}")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()