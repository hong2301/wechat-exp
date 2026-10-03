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
        if not u32.SetClipboardData(CF_HDROP, h):
            k32.GlobalFree(h)
            return False
        wi.mark_clipboard_private(u32)   # 不进 Win+V 历史/不参与同步
        return True
    finally:
        u32.CloseClipboard()


class _ClipboardBackup:
    """备份/恢复剪贴板（枚举全部格式，raw 复制；失败格式自动跳过）。"""

    def __init__(self):
        self.items = []      # [(fmt, bytes)]

    def save(self):
        u32 = _user32()
        k32 = _kernel32()
        k32.GlobalSize.restype = ctypes.c_size_t
        k32.GlobalSize.argtypes = [ctypes.c_void_p]
        self.items = []
        if not u32.OpenClipboard(None):
            return
        try:
            fmt = 0
            while True:
                fmt = u32.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                if fmt in (0,):
                    continue
                h = u32.GetClipboardData(fmt)
                if not h:
                    continue
                try:
                    size = k32.GlobalSize(h)
                    if not size:
                        continue
                    p = k32.GlobalLock(h)
                    if not p:
                        continue
                    try:
                        raw = ctypes.string_at(p, size)
                    finally:
                        k32.GlobalUnlock(h)
                    self.items.append((fmt, raw))
                except Exception:
                    continue
        finally:
            u32.CloseClipboard()

    def restore(self):
        """把备份内容完整写回剪贴板（用户原内容回归，含图片等格式）。"""
        u32 = _user32()
        k32 = _kernel32()
        if not self.items:
            # 原本就没有内容：清空
            try:
                u32.OpenClipboard(None)
                u32.EmptyClipboard()
                u32.CloseClipboard()
            except Exception:
                pass
            return
        try:
            if not u32.OpenClipboard(None):
                return
            try:
                u32.EmptyClipboard()
                for fmt, raw in self.items:
                    try:
                        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
                        if not h:
                            continue
                        p = k32.GlobalLock(h)
                        if not p:
                            k32.GlobalFree(h)
                            continue
                        try:
                            ctypes.memmove(p, raw, len(raw))
                        finally:
                            k32.GlobalUnlock(h)
                        if not u32.SetClipboardData(fmt, h):
                            k32.GlobalFree(h)
                    except Exception:
                        continue
            finally:
                u32.CloseClipboard()
        except Exception:
            pass


def _paste_from_clipboard():
    """Ctrl+V 粘贴（当前剪贴板内容 → 焦点窗口）。"""
    wi.ctrl_key("V")
    time.sleep(0.3)


# ---------------------------------------------------------------------------
# 对外方法
# ---------------------------------------------------------------------------
def _focus_and_clear_input(window_mode=True) -> dict:
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
    r = _focus_and_clear_input(window_mode=True)
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
        time.sleep(0.2)          # 尽快恢复，缩短剪贴板被 Deskflow 同步的窗口
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


def _enum_top_windows():
    """枚举系统全部顶层窗口 [(hwnd, title, class, visible), ...]。"""
    u32 = _user32()
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    out = []

    def cb(h, lp):
        try:
            t = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(h, t, 512)
            c = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(h, c, 256)
            out.append((h, t.value, c.value, bool(u32.IsWindowVisible(h))))
        except Exception:
            pass
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def _find_dialog_child(dialog, want_class=None, want_id=None,
                       want_text_contains=None, visible_only=True):
    """在对话框内查找子控件（按类名 / 控件 ID / 文本包含）。返回 hwnd 或 None。"""
    u32 = _user32()
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    found = []

    def cb(h, lp):
        try:
            if visible_only and not u32.IsWindowVisible(h):
                return True
            c = ctypes.create_unicode_buffer(128)
            u32.GetClassNameW(h, c, 128)
            if want_class and c.value != want_class:
                return True
            if want_id is not None and u32.GetDlgCtrlID(h) != want_id:
                return True
            if want_text_contains is not None:
                t = ctypes.create_unicode_buffer(256)
                u32.GetWindowTextW(h, t, 256)
                if want_text_contains not in t.value:
                    return True
            found.append(h)
        except Exception:
            pass
        return True

    u32.EnumChildWindows(wt.HWND(dialog), WNDENUMPROC(cb), 0)
    return found[0] if found else None


def send_file_via_picker(path: str, hwnd=None, wait_picker=5.0,
                         verbose=True) -> dict:
    """通过「文件按钮」+ 文件选择对话框发送文件（全窗口消息，不碰剪贴板）。

    要点（实测）：
      - 对话框：#32770 标题「选择文件」，属微信进程
      - 路径栏：标准 Win32 Edit 控件（id=1148）→ 必须用 WM_SETTEXT
        （Win32 Edit 无输入焦点时不处理 WM_CHAR，与 Chromium 的 WM_CHAR 不同）
      - 「打开」：Button id=1，用 BM_CLICK
    """
    def log(m):
        if verbose:
            print(f"      {m}")

    path = os.path.normpath(os.path.abspath(str(path)))
    if not os.path.exists(path):
        return {"ok": False, "code": "ERR_NO_FILE", "message": f"文件不存在: {path}"}
    if hwnd is None:
        import wechat_status as ws
        hwnd = ws._find_main_hwnd(ws._wechat_pids())
    if not hwnd:
        return {"ok": False, "code": "ERR_NO_WINDOW", "message": "未找到微信主窗口"}

    import points
    pt = points.get_point('file_button')
    if not pt:
        return {"ok": False, "code": "ERR_NO_POINT",
                "message": "缺少点位 file_button（请先采集）"}

    u32 = _user32()
    u32.SendMessageW.restype = ctypes.c_ssize_t
    u32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t,
                                 ctypes.c_ssize_t]

    def _addr(obj):
        """取 ctypes 对象的内存地址（int），供 LPARAM 传递。"""
        return ctypes.cast(obj, ctypes.c_void_p).value or 0

    def _read_text(h):
        buf = ctypes.create_unicode_buffer(1024)
        u32.SendMessageW(h, 0x000D, 1024, _addr(buf))   # WM_GETTEXT
        return buf.value

    # 1) 点击文件按钮
    before = {h for h, _t, _c, v in _enum_top_windows() if v}
    wi.post_click(pt['x'], pt['y'])
    log(f"点击文件按钮 ({pt['x']},{pt['y']})")

    # 2) 等待「选择文件」对话框
    dialog = None
    deadline = time.time() + wait_picker
    while time.time() < deadline:
        time.sleep(0.3)
        cands = [w for w in _enum_top_windows()
                 if w[3] and w[0] not in before and w[2] == '#32770']
        if cands:
            # 优先标题含“选择文件/打开”
            pref = [w for w in cands
                    if '选择文件' in w[1] or '打开' in w[1] or 'Open' in w[1]]
            dialog = (pref or cands)[0][0]
            log(f"对话框: {hex(dialog)} {pref[0][1]!r}" if pref else f"对话框: {hex(dialog)}")
            break
    if not dialog:
        return {"ok": False, "code": "ERR_NO_PICKER",
                "message": "文件选择对话框未出现"}
    time.sleep(0.6)

    # 3) 找 Edit 控件（轮询）
    edit = None
    deadline2 = time.time() + 4.0
    while time.time() < deadline2:
        edit = (_find_dialog_child(dialog, want_id=1148, visible_only=True)
                or _find_dialog_child(dialog, want_class='Edit', visible_only=True))
        if edit:
            break
        time.sleep(0.3)
    if not edit:
        return {"ok": False, "code": "ERR_NO_EDIT",
                "message": "对话框内未找到路径输入框"}
    log(f"路径栏: {hex(edit)}")

    # 4) WM_SETTEXT 写入 + 读回校验（最多 3 次）
    written = False
    for i in range(3):
        cbuf = ctypes.create_unicode_buffer(path)
        u32.SendMessageW(edit, 0x000C, 0, _addr(cbuf))  # WM_SETTEXT
        time.sleep(0.35)
        got = _read_text(edit)
        log(f"写入尝试{i+1}: 读回 {got[:70]!r}")
        if got.strip() == path:
            written = True
            break
    if not written:
        return {"ok": False, "code": "ERR_SET_PATH",
                "message": f"路径未写入对话框（读回: {_read_text(edit)[:60]!r}）"}

    # 5) 点「打开」（轮询）
    btn = None
    deadline3 = time.time() + 2.0
    while time.time() < deadline3:
        btn = (_find_dialog_child(dialog, want_id=1, visible_only=True)
               or _find_dialog_child(dialog, want_class='Button',
                                     want_text_contains='打开', visible_only=True))
        if btn:
            break
        time.sleep(0.2)
    if not btn:
        return {"ok": False, "code": "ERR_NO_BUTTON",
                "message": "对话框内未找到「打开」按钮"}
    u32.SendMessageW(btn, 0x00F5, 0, 0)   # BM_CLICK
    log(f"点击打开按钮 {hex(btn)}")
    time.sleep(1.5)

    # 6) 回微信回车发送
    r = wi.post_key(wi.VK_RETURN, hwnd=hwnd)
    if not r["ok"]:
        return r
    return {"ok": True, "code": "OK",
            "message": f"已通过文件按钮发送: {os.path.basename(path)}"}


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