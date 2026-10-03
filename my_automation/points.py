# -*- coding: utf-8 -*-
"""
points — 点位模块（微信界面坐标配置）
=====================================
存储微信自动化操作需要的界面点位坐标（JSON 配置文件）。

点位清单：
    search_box      搜索框
    chat_input      聊天输入框

方法：
    load_points()                 读取全部点位（dict）
    save_points(points)           保存全部点位（覆盖写 JSON）
    get_point(name)               读取单个点位 (x, y)；未设置返回 None
    get_points()                  读取全部点位（同 load_points）
    capture_one(prompt)           交互式采集单个点位
    capture_all()                 依次采集全部 3 个点位并保存（符合提供的点位才保存）
    clear_points()                清空点位

交互捕获规则（与参考项目一致）：
    左键单击  → 记录当前点击坐标（终端显示）
    左键双击  → 确认该坐标，结束当前点位的采集
    右键单击  → 取消退出（返回 None）

配置文件：points.json（与本模块同目录）。
⚠️ 坐标与屏幕分辨率/个人布局相关，该文件已在 .gitignore，不入库。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import time

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
POINTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'points.json')

# 点位清单（顺序即采集顺序）
# 注：第一联系人不再需要点位——微信搜索后第一项默认选中，直接回车即可打开
POINT_NAMES = {
    'search_box': '搜索框',
    'chat_input': '聊天输入框',
    'search_split_button': '搜一搜窗口分离按钮',
    'file_button': '文件按钮',
}


def _default_points() -> dict:
    return {name: None for name in POINT_NAMES}


# ---------------------------------------------------------------------------
# 存取
# ---------------------------------------------------------------------------
def load_points() -> dict:
    """读取全部点位。文件不存在/损坏时返回默认结构（全 None）。"""
    pts = _default_points()
    try:
        with open(POINTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in pts:
                v = data.get(k)
                if isinstance(v, dict) and 'x' in v and 'y' in v:
                    pts[k] = {'x': int(v['x']), 'y': int(v['y'])}
    except (OSError, ValueError, TypeError):
        pass
    return pts


def save_points(points: dict) -> dict:
    """保存全部点位（覆盖写）。返回 {"ok", "code", "message"}。"""
    for k, v in points.items():
        points[k] = {'x': int(v['x']), 'y': int(v['y'])} if v else None
    try:
        with open(POINTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(points, f, ensure_ascii=False, indent=2)
        return {"ok": True, "code": "OK", "message": f"点位已保存: {POINTS_FILE}"}
    except OSError as e:
        return {"ok": False, "code": "ERR_WRITE", "message": f"保存失败: {e}"}


def get_points() -> dict:
    """读取全部点位。"""
    return load_points()


def get_point(name: str):
    """读取单个点位，返回 {'x': .., 'y': ..}；未设置/未知点位返回 None。"""
    if name not in POINT_NAMES:
        return None
    return load_points().get(name)


def clear_points() -> dict:
    """清空全部点位。"""
    return save_points(_default_points())


# ---------------------------------------------------------------------------
# 交互式采集（GetAsyncKeyState 轮询 + GetCursorPos 取坐标）
# 说明：低层鼠标钩子（WH_MOUSE_LL）在本环境不可靠（回调被静默丢弃），
#       改为键盘状态轮询 —— 已验证可稳定捕获用户点击。
# ---------------------------------------------------------------------------
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37


def _user32():
    u32 = ctypes.windll.user32
    # GetCursorPos / GetAsyncKeyState 无句柄问题，但统一声明签名更稳
    u32.GetCursorPos.restype = ctypes.c_int
    u32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    return u32


def _kernel32():
    return ctypes.windll.kernel32


def _capture_sequence(print_fn=None, poll_s=0.02) -> dict:
    """阻塞完成一个点位的完整手势序列（轮询键盘状态）。

    交互：
        左键单击  → 打印预览坐标（继续监听）
        左键双击  → 确认（取第一次按下的坐标）
        右键单击  → 取消，返回 None

    返回 {"x":.., "y":..} 或 None（右键取消）。
    """
    if print_fn is None:
        print_fn = print
    u32 = _user32()

    dbl_ms = u32.GetDoubleClickTime()
    dbl_cx = u32.GetSystemMetrics(SM_CXDOUBLECLK)
    dbl_cy = u32.GetSystemMetrics(SM_CYDOUBLECLK)

    prev_left = prev_right = False
    last_x = last_y = last_t = None   # 上一次“完整单击”的坐标/时间
    try:
        while True:
            left = bool(u32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            right = bool(u32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)

            # 右键按下沿 → 取消退出
            if right and not prev_right:
                return None

            # 左键按下沿 → 记录坐标 / 双击确认
            if left and not prev_left:
                pt = wt.POINT()
                u32.GetCursorPos(ctypes.byref(pt))
                now = time.monotonic()
                if (last_x is not None
                        and (now - last_t) * 1000 <= dbl_ms
                        and abs(pt.x - last_x) <= dbl_cx
                        and abs(pt.y - last_y) <= dbl_cy):
                    return {"x": last_x, "y": last_y}   # 双击确认：取第一次坐标
                last_x, last_y, last_t = pt.x, pt.y, now
                print_fn(f"    ⚪ 单击记录: ({pt.x}, {pt.y})  —— 双击确认 / 右键取消")

            prev_left, prev_right = left, right
            time.sleep(poll_s)
    except KeyboardInterrupt:
        return None


def capture_one(prompt: str = None, print_fn=None) -> dict:
    """交互式采集单个点位。

    提示用户在目标位置：左键单击预览坐标 → 左键双击确认 → 右键取消。

    返回: {"ok": True, "point": {"x","y"}, ...}
         {"ok": False, "code": "CANCELLED", ...}
    """
    if print_fn is None:
        print_fn = print
    print_fn(f"  定位「{prompt or '点位'}」：把鼠标移到目标位置，"
             f"左键单击预览坐标，双击确认；右键取消")
    pt = _capture_sequence(print_fn=print_fn)
    if pt is None:
        return {"ok": False, "code": "CANCELLED",
                "message": f"「{prompt or '点位'}」被右键取消"}
    print_fn(f"  ✅ 已确认: ({pt['x']}, {pt['y']})")
    return {"ok": True, "point": pt, "message": f"({pt['x']}, {pt['y']})"}


def capture_all() -> dict:
    """依次交互采集全部点位并保存。

    右键取消任意一个点则中断，已采集的点位不保存。
    全部采集完才一次性写出 JSON。

    返回 {"ok", "code", "message", "points"}
    """
    pts = _default_points()
    print("=" * 52)
    print("  点位采集（3 个）：左键单击预览 / 双击确认 / 右键取消")
    print("=" * 52)
    for name, label in POINT_NAMES.items():
        print(f"[{label}]")
        r = capture_one(label)
        if not r["ok"]:
            print(r["message"])
            return {"ok": False, "code": "CANCELLED",
                    "message": f"点位采集中断（{label}）", "points": pts}
        pts[name] = r["point"]

    result = save_points(pts)
    result["points"] = pts
    if result["ok"]:
        print("✓ 全部点位已保存到", POINTS_FILE)
    return result


# ---------------------------------------------------------------------------
# CLI 入口：python my_automation/points.py [show | capture | clear]
# ---------------------------------------------------------------------------
def capture_one_point(name: str) -> dict:
    """仅交互采集单个点位，并与已有点位合并保存。"""
    if name not in POINT_NAMES:
        return {"ok": False, "code": "ERR_UNKNOWN_POINT",
                "message": f"未知点位: {name}（可用: {list(POINT_NAMES)}）"}
    label = POINT_NAMES[name]
    print(f"[{label}] （点位: {name}）")
    r = capture_one(label)
    if not r["ok"]:
        return r
    pts = load_points()
    pts[name] = r["point"]
    result = save_points(pts)
    result["points"] = pts
    if result["ok"]:
        print(f"✓ 点位「{label}」({name}) 已保存: ({r['point']['x']}, {r['point']['y']})")
    return result


def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'show'

    if cmd == 'capture':
        # 支持仅采单个点位: python points.py capture --point search_split_button
        if '--point' in sys.argv:
            i = sys.argv.index('--point')
            if i + 1 < len(sys.argv):
                capture_one_point(sys.argv[i + 1])
                return
        capture_all()
    elif cmd == 'clear':
        print(clear_points())
    elif cmd == 'show':
        pts = load_points()
        print("点位配置:", POINTS_FILE)
        for name, label in POINT_NAMES.items():
            v = pts.get(name)
            print(f"  {label:<8s} ({name}): "
                  + (f"({v['x']}, {v['y']})" if v else "未设置"))
    else:
        print("用法: python my_automation/points.py [show|capture[--point NAME]|clear]")


if __name__ == '__main__':
    main()