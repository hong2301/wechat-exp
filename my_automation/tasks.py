# -*- coding: utf-8 -*-
"""
tasks — 自动化任务编排
=======================
组合微信状态 / 点位 / 输入模块，提供完整的自动化任务方法。

方法：
    open_contact_chat(contact)   打开联系人聊天窗口
       流程：检测登录 → 初始化窗口 → 点击搜索框 → 输入联系人
             → 点击第一联系人 → 点击聊天输入框（到此停止，等待后续发送）

统一返回 {"ok": bool, "code": str, "message": str}
"""
import os
import sys
import time

_SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import wechat_status as ws      # noqa: E402
import points                   # noqa: E402
import wechat_input as wi       # noqa: E402
import sender                   # noqa: E402

# my_tools/ 也在本仓库，验证发送结果时复用其能力（用户已许可跨模块调用）
# 注意：开发边界默认不主动深入 my_tools 内部，仅调用其公开方法。
_MY_TOOLS = os.path.join(os.path.dirname(_SRC_DIR), 'my_tools')
if _MY_TOOLS not in sys.path:
    sys.path.insert(0, _MY_TOOLS)


def _step_ok(code: str, message: str) -> dict:
    return {"ok": True, "code": code, "message": message}


def _step_fail(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message}


def _check_contact_result(before_width: int) -> dict:
    """点击第一联系人后的结果校验（按用户方案）。

    成功：点击到了联系人 —— 主窗口宽度不变 且 无额外可见窗口。
    失败情形（均为“未找到联系人”）：
      1) 微信主窗口宽度发生变化（界面切到了别的页面/布局变化）
      2) 出现独立的「搜一搜」可见窗口
      3) 出现独立的「添加朋友/添加好友」可见窗口
    """
    if not ws.is_wechat_running():
        return _step_fail("ERR_NO_WECHAT", "微信未运行")

    # 情形 1：主窗口宽度变化
    cur_width = ws.get_window_width()
    if before_width and cur_width and cur_width != before_width:
        return _step_fail(
            "ERR_CONTACT_NOT_FOUND",
            f"点击第一联系人后微信主窗口宽度变化"
            f"({before_width}px → {cur_width}px)——未找到该联系人")

    # 情形 2/3：出现额外可见窗口（搜一搜 / 添加朋友等）
    extras = ws.extra_visible_windows()
    if extras:
        titles = "; ".join(f"{t or '(无标题)'}" for _h, t in extras)
        return _step_fail(
            "ERR_CONTACT_NOT_FOUND",
            f"点击第一联系人后出现额外可见窗口(共 {len(extras)} 个: {titles})"
            f"——未找到该联系人")

    # 情形 4：主窗口内嵌入了搜一搜渲染页（无独立窗口、宽度可能不变）
    if ws.has_embedded_page():
        return _step_fail(
            "ERR_CONTACT_NOT_FOUND",
            "点击第一联系人后微信主窗口内嵌入了搜一搜页面"
            "——未找到该联系人")

    return _step_ok("OK", "已点击到联系人（宽度未变 / 无额外窗口 / 无嵌入页）")


def _cleanup_contact_fail(window_mode=False) -> list:
    """未找到联系人后的收尾动作：关闭搜一搜 / 添加朋友等窗口。

    - 独立可见窗口（搜一搜 / 添加朋友）：直接 WM_CLOSE
    - 嵌入式搜一搜：先点击点位4（搜一搜窗口分离按钮）再触发关闭
    返回收尾日志列表。
    """
    import time as _t
    logs = []

    _click = wi.post_click if window_mode else wi.mouse_click

    # 1) 独立可见窗口：直接关闭
    extras = ws.extra_visible_windows()
    for h, t in extras:
        ws._close_window(h)
        logs.append(f"关闭独立窗口「{t or '(无标题)'}」")

    # 2) 嵌入式搜一搜：点击点位4（分离按钮）后关闭
    if ws.has_embedded_page():
        pt = points.get_point("search_split_button")
        if not pt:
            logs.append("缺少点位4(search_split_button)，嵌入式搜一搜无法关闭")
        else:
            for _i in range(3):
                _click(pt["x"], pt["y"])
                logs.append(f"点击搜一搜窗口分离按钮(点位4) ({pt['x']},{pt['y']})")
                _t.sleep(0.8)
                # 分离后可能出现独立窗口，关闭它
                for h, t in ws.extra_visible_windows():
                    ws._close_window(h)
                    logs.append(f"关闭分离出的窗口「{t or '(无标题)'}」")
                if not ws.has_embedded_page():
                    break
            if ws.has_embedded_page():
                logs.append("⚠ 嵌入页仍未关闭（多次点击点位4无效）")

    return logs


def _clear_search_box(window_mode=False) -> dict:
    """输入前清空搜索框（点击后 Ctrl+A + Delete）。"""
    pt = points.get_point("search_box")
    if not pt:
        return _step_fail("ERR_NO_POINT", "缺少点位 search_box")
    if window_mode:
        wi.post_click(pt["x"], pt["y"])
        r = wi.post_clear()
    else:
        wi.mouse_click(pt["x"], pt["y"], wait_after=0.2)
        r = wi.clear_input()
    if not r["ok"]:
        return _step_fail("ERR_CLEAR", f"清空搜索框失败: {r['message']}")
    return _step_ok("OK", "搜索框已清空")


def open_contact_chat(contact: str, use_paste=False, wait_search=0.8,
                      clear_first=True, window_mode=True) -> dict:
    """打开指定联系人的聊天窗口（任务）。

    流程：
        1. 检测微信是否登录
        2. 初始化微信窗口（前置 + 左半屏）
        3. 点击点位1 search_box（搜索框）
        4. 输入联系人名称
        5. 输入后回车打开第一联系人（第一项默认选中，无需点位2）
        6. 点击点位3 chat_input（聊天输入框）→ 停止

    参数：
        contact      联系人名称 / 备注 / 关键词（输入到搜索框的内容）
        use_paste    True 时用剪贴板粘贴，False 用 SendInput 逐字符输入
        wait_search  输入后等待搜索结果出现的秒数

    返回: {"ok", "code", "message"}
    """
    if not contact or not str(contact).strip():
        return _step_fail("ERR_NO_CONTACT", "未提供联系人名称")

    # 1) 检测登录
    if not ws.is_logged_in():
        return _step_fail("ERR_NOT_LOGGED_IN",
                          "微信未登录（请先登录微信后重试）")

    # 2) 初始化微信窗口
    r = ws.init_wechat_window()
    if not r["ok"]:
        return _step_fail("ERR_WINDOW_INIT",
                          f"微信窗口初始化失败: {r['message']}")

    # 3) 点击搜索框（点位1），并先清空内容（避免上次残留）
    r = _clear_search_box(window_mode=window_mode)
    if not r["ok"]:
        return r

    # 4) 输入联系人
    if window_mode:
        r = wi.post_text(contact)
    else:
        r = (wi.paste_text(contact) if use_paste else wi.type_text(contact))
    if not r["ok"]:
        return _step_fail("ERR_INPUT", f"输入联系人失败: {r['message']}")
    time.sleep(wait_search)   # 等待搜索结果出现

    # 5) 打开第一联系人：输入后第一项默认选中，直接回车（无需点位2）
    before_width = ws.get_window_width()   # 记录回车前主窗口宽度
    if window_mode:
        r = wi.post_key(wi.VK_RETURN)      # 窗口级回车
    else:
        r = wi.key_press(wi.VK_RETURN)     # 系统级回车
    if not r["ok"]:
        return _step_fail("ERR_CLICK",
                          f"回车打开联系人失败: {r['message']}")
    time.sleep(0.8)

    # 5b) 校验结果：宽度变化 / 搜一搜 / 添加朋友 → 未找到联系人
    r = _check_contact_result(before_width)
    if not r["ok"]:
        # 收尾：关闭搜一搜（嵌入式先点点位4）/ 添加朋友等窗口
        cleanup_logs = _cleanup_contact_fail(window_mode=window_mode)
        r["message"] += (
            "\n    [收尾] " + "; ".join(cleanup_logs) if cleanup_logs
            else "\n    [收尾] 无需清理")
        return r

    # 6) 点击聊天输入框（点位3）→ 停止（回到主窗口）
    pt = points.get_point("chat_input")
    if not pt:
        return _step_fail("ERR_NO_POINT",
                          "缺少点位 chat_input，请先运行点位采集")
    if window_mode:
        r = wi.post_click(pt["x"], pt["y"])   # 默认主窗口
    else:
        r = wi.mouse_click(pt["x"], pt["y"], wait_after=0.3)
    time.sleep(0.3)
    if not r["ok"]:
        return _step_fail("ERR_CLICK", f"点击聊天输入框失败: {r['message']}")

    return _step_ok("OK",
                    f"已打开联系人「{contact}」的聊天窗口（搜索框已输入，"
                    f"已定位到聊天输入框，等待发送）")


def _verify_sent_local(db_storage: str, content: str,
                       db_begin: float = None, db_end: float = None,
                       debug=False):
    """解密 message 库并查找内容匹配且时间在 [db_begin, db_end] 内的消息。

    返回 (匹配消息 dict 或 None, 库内最新消息时间 or 0)。
    说明：微信 4.x 消息在 message/message_0.db 的多个 Msg_* 分片表中，
    消息内容可能 zstd 压缩；此处解密后逐个分片扫描。
    """
    import sqlite3
    import tempfile
    from engine.config_file import get_db_keys
    from backup.decryptor import resolve_key_for
    from engine.decrypt import decrypt_database
    from engine.services.message.decode import decompress_content

    content_like = str(content).strip()
    if not content_like:
        return None, 0

    src = os.path.join(db_storage, 'message', 'message_0.db')
    if not os.path.isfile(src):
        print(f"    ⚠ 未找到消息库: {src}")
        return None, 0
    keys = get_db_keys()
    key = resolve_key_for(src, keys)
    if not key:
        print(f"    ⚠ 无密钥，无法解密 {src}")
        return None, 0

    tmp = tempfile.mktemp(suffix='.db')
    try:
        print(f"    🔄 解密 {os.path.basename(src)} 查验...")
        try:
            decrypt_database(src, tmp, key)
        except Exception as e:
            print(f"    ⚠ 解密失败: {e}")
            return None, 0
        conn = sqlite3.connect(tmp)
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
            if db_begin is None:
                db_begin = time.time() - 5
            if db_end is None:
                db_end = time.time() + 5
            max_ct = 0
            for tbl in tables:
                try:
                    mx = conn.execute(f'SELECT MAX(create_time) FROM [{tbl}]').fetchone()[0]
                    max_ct = max(max_ct, int(mx or 0))
                except sqlite3.Error:
                    pass
            for tbl in tables:
                try:
                    rows = conn.execute(
                        f"SELECT local_id, local_type, real_sender_id, create_time, "
                        f"status, message_content FROM [{tbl}] "
                        f"WHERE create_time >= ? AND create_time <= ?",
                        (int(db_begin), int(db_end))).fetchall()
                except sqlite3.Error:
                    continue
                for local_id, ltype, sid, ctime, status, raw in rows:
                    if isinstance(raw, bytes):
                        try:
                            raw = decompress_content(raw)
                        except Exception:
                            pass
                    if isinstance(raw, bytes):
                        try:
                            raw = raw.decode('utf-8', errors='replace')
                        except Exception:
                            raw = ''
                    raw = str(raw or '')
                    if content_like in raw:
                        conn.close()
                        return ({"local_id": local_id, "type": ltype,
                                 "timestamp": int(ctime or 0), "content": raw[:200]},
                                max_ct)
        finally:
            conn.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return None, max_ct


def send_and_verify(contact: str, content: str,
                    use_paste=False, wait_search=0.8,
                    verify_backoff=15, save_sql=5,
                    window_mode=True) -> dict:
    """发送消息并验证是否发送成功（完整任务）。

    流程：
        1. open_contact_chat(contact)        打开聊天窗口
        2. sender.send_message(content, send=True)  粘贴 + 回车发送
        3. 重新解密当前账号数据库（获取最新消息，时间范围今天）
        4. 读取本地数据库，按联系人 + 时间(发送前5秒~现在)匹配
        5. 找到“我”发出的、内容匹配、时间在发送后的消息 ⇒ 成功，否则失败

    参数：
        contact         联系人（窗口打开 + 数据库查询均使用）
        content         要发送的内容
        use_paste       输入联系人时是否用剪贴板
        wait_search     搜索等待秒数
        verify_backoff  发送后等待消息落库的秒数（默认5）
        save_sql        保留最近多少秒的验证窗口（默认取发送前5秒~现在）

    返回: {"ok", "code", "message"}
    """
    if not content or not str(content).strip():
        return _step_fail("ERR_NO_CONTENT", "未提供要发送的内容")

    # 1) 打开聊天窗口
    r = open_contact_chat(contact, use_paste=use_paste, wait_search=wait_search,
                          window_mode=window_mode)
    if not r["ok"]:
        return r

    # 2) 发送（窗口模式：PostMessage 直达；常规模式：剪贴板借用+回车）
    send_time = time.time()
    if window_mode:
        if isinstance(content, (list, tuple)) or \
           (isinstance(content, str) and os.path.exists(content)):
            return _step_fail("ERR_SEND",
                              "窗口模式暂不支持文件发送，请用常规模式发送文件")
        r = sender.send_text_window(content)
        if not r["ok"]:
            return _step_fail("ERR_SEND", f"窗口级发送失败: {r['message']}")
    else:
        r = sender.send_message(content, send=True)
        if not r["ok"]:
            return _step_fail("ERR_SEND", f"发送失败: {r['message']}")

    # 3) 轮询验证：发送后立即解析数据库，每秒 1 次。
    #    实测：微信 4.x 消息写入 WAL 后约 8~10s 才 checkpoint 进主库
    #    （“前 5 秒”只是近似），故默认最多轮询 12 次（覆盖 10s+余量）。
    #    查询窗口起点从 send_time-5s 起，每轮递增 1 秒（前5→前6→…→前16）。
    active = ws.get_active_data_dir()
    if not active:
        return _step_fail("ERR_NO_ACTIVE_DIR",
                          "无法确定当前登录账号的数据目录，无法验证")
    max_attempts = 12
    print(f"    ✅ 已发送，开始轮询数据库验证（每秒 1 次，最多 {max_attempts} 次）...")

    matched = None
    for attempt in range(1, max_attempts + 1):
        begin_offset = save_sql + attempt - 1      # 5, 6, 7, ...  （前5秒~前16秒）
        db_begin = send_time - begin_offset
        db_end = send_time + 5                     # 窗口上界留 5s 余量
        print(f"    🔄 第{attempt}/{max_attempts} 次: 查 [{time.strftime('%H:%M:%S', time.localtime(db_begin))} ~ "
              f"{time.strftime('%H:%M:%S', time.localtime(db_end))}]...")
        debug = _verify_sent_local(active, content, db_begin, db_end, debug=True)
        matched, max_ct = debug[0], debug[1]
        if max_ct:
            print(f"        (库最新消息时间: {time.strftime('%H:%M:%S', time.localtime(max_ct))}"
                  f"，落后发送时刻 {int(send_time) - int(max_ct)}s)")
        if matched:
            break
        time.sleep(1)                              # 每秒重试

    if matched:
        t0 = time.strftime("%H:%M:%S", time.localtime(matched["timestamp"]))
        return _step_ok("OK",
                        f"发送验证成功: 「{content}」已于 {t0} 出现在本地数据库"
                        f"（联系人 {contact}），验证耗时 {attempt} 次")
    return _step_fail("ERR_SEND_UNVERIFIED",
                      f"发送未被验证：{max_attempts} 次轮询均未在数据库中"
                      f"（窗口前{save_sql}s 起）找到刚发出的消息（联系人 {contact}）")


# ---------------------------------------------------------------------------
# CLI：python my_automation/tasks.py --contact 张三 [--paste] [--wait 0.8]
#       python my_automation/tasks.py --send --contact 李四 --content 你好
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(prog="my_automation.tasks",
                                 description="微信自动化任务")
    ap.add_argument("--contact", required=True, help="联系人名称/关键词")
    ap.add_argument("--paste", action="store_true", help="用剪贴板粘贴输入")
    ap.add_argument("--wait", type=float, default=0.8, help="搜索等待秒数")
    ap.add_argument("--send", action="store_true",
                    help="发送模式：粘贴内容并回车发送")
    ap.add_argument("--content", help="要发送的内容（--send 时必填）")
    ap.add_argument("--verify", action="store_true",
                    help="发送后读取本地数据库验证是否发送成功")
    ap.add_argument("--window", action="store_true",
                    help="窗口级模式(PostMessage直达，不依赖系统焦点，适合Deskflow)")
    args = ap.parse_args()

    if args.send:
        if not args.content:
            print("发送模式需要 --content 内容")
            raise SystemExit(1)
        if args.verify:
            r = send_and_verify(args.contact, args.content,
                                use_paste=args.paste, wait_search=args.wait,
                                window_mode=args.window)
        else:
            r = open_contact_chat(args.contact, use_paste=args.paste,
                                  wait_search=args.wait,
                                  window_mode=args.window)
            if r["ok"]:
                r = (sender.send_text_window(args.content)
                     if args.window else sender.send_message(args.content))
    else:
        r = open_contact_chat(args.contact, use_paste=args.paste,
                              wait_search=args.wait, window_mode=args.window)
    print("=" * 56)
    print(f"结果: {'成功' if r['ok'] else '失败'}  [错误码: {r['code']}]")
    print(f"说明: {r['message']}")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()