# -*- coding: utf-8 -*-
"""
monitor — 微信新消息监控模块
=============================
每秒解密解析微信数据库，检测并上报新收到的消息。

原理：
    - 每次轮询解密 message_0.db（92KB 级别，毫秒级）
    - 扫描全部 Msg_* 分片表，取 create_time 大于“上次已见时间”的行
    - 消息内容 zstd 解压后上报（时间 / 发送侧 / 类型 / 内容）

⚠️ 注意：微信数据库约 5~10s 才 checkpoint，新消息有 ~10s 延迟可见。

方法：
    watch(interval=1.0, on_message=None, run_seconds=None, stop_event=None)
        interval       轮询间隔秒数（默认 1）
        on_message     回调 fn(msg_dict)；None 时打印
        run_seconds    None=直到 stop_event 置位/Ctrl+C
        stop_event     threading.Event；置位则退出
"""
import os
import sqlite3
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from engine.config_file import get_db_keys                  # noqa: E402
from backup.decryptor import resolve_key_for                # noqa: E402
from engine.decrypt import decrypt_database                 # noqa: E402
from engine.services.message.decode import decompress_content  # noqa: E402
from engine.services.sender_model import load_name2id       # noqa: E402


def _resolve_sender(rowid, n2id: dict):
    """分片内 sender_id(数字 rowid) → wxid；未命中返回原始数字。"""
    if n2id:
        wxid = n2id.get(int(rowid))
        if wxid:
            return wxid
    return rowid


def _is_wxid(s):
    """是否可发送目标的微信 id（wxid_ / 服务号 / 群）。纯数字视为未解析。"""
    s = str(s or '')
    return bool(s.startswith('wxid_') or '@' in s or s.startswith('gh_'))


class MessageMonitor:
    """微信新消息监控器。"""

    def __init__(self, db_storage=None):
        self.src = None
        self.key = None
        self.last_ts = 0            # 上次已见的最大 create_time（兼容保留）
        self.window_seconds = 600   # 扫描窗口：最近 N 秒内的消息
        self._wal_stat = {'size': 0, 'mtime': 0}
        self._seen = set()          # 已上报消息去重 (tbl, local_id)
        self._seen_lim = 5000       # 去重集合上限（避免无限增长）
        self.stats = {"scans": 0, "new_messages": 0, "errors": 0}

        if db_storage is None:
            import wechat_status as ws
            db_storage = ws.get_active_data_dir()
        if db_storage:
            src = os.path.join(db_storage, 'message', 'message_0.db')
            if os.path.isfile(src):
                self.src = src
                self.key = resolve_key_for(src, get_db_keys())

    # ------------------------------------------------------------------
    def wal_changed(self):
        """检测 message_0.db-wal 是否变化（新消息写入但尚未 checkpoint 进主库）。

        返回 (changed, wal_size)；WAL 增长=有消息到来但暂不可读（等 checkpoint）。
        """
        if not self.src:
            return False, 0
        try:
            st = os.stat(self.src + '-wal')
            sz, mt = st.st_size, st.st_mtime
        except OSError:
            return False, 0
        changed = (sz != self._wal_stat['size'] or mt != self._wal_stat['mtime'])
        self._wal_stat = {'size': sz, 'mtime': mt}
        return changed, sz

    # ------------------------------------------------------------------
    def _fetch_new(self, max_rows=200):
        """解密并扫描【窗口内】create_time > now-window_seconds 的消息。

        返回 [(tbl, row), ...]（升序），由调用方用 (tbl, local_id) 去重。
        """
        if not self.src or not self.key:
            return []
        win_begin = time.time() - self.window_seconds
        tmp = tempfile.mktemp(suffix='.db')
        try:
            decrypt_database(self.src, tmp, self.key)
            conn = sqlite3.connect(tmp)
            try:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'Msg_%'")]
                rows = []
                for tbl in tables:
                    try:
                        n2id = load_name2id(conn)   # 分片级 rowid→wxid
                        for r in conn.execute(
                                f"SELECT local_id, server_id, local_type, real_sender_id, "
                                f"create_time, origin_source, message_content "
                                f"FROM [{tbl}] WHERE create_time > ? "
                                f"ORDER BY create_time DESC LIMIT {max_rows}",
                                (int(win_begin),)):
                            r = list(r)
                            r[2] = _resolve_sender(r[2], n2id)
                            rows.append((tbl, tuple(r)))
                    except sqlite3.Error:
                        continue
                rows.sort(key=lambda x: x[1][3] or 0)
                return rows[:max_rows]
            finally:
                conn.close()
        except Exception:
            self.stats["errors"] += 1
            return []
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    @staticmethod
    def _format(row):
        local_id, server_id, ltype, sender_id, ctime, origin, raw = row
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
        base = (ltype & 0xFFFF) if isinstance(ltype, int) else ltype
        from engine.constants import MSG_TYPES_CN
        return {
            "local_id": local_id,
            "msg_id": str(server_id or local_id),
            "timestamp": int(ctime or 0),
            "time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ctime or 0)),
            "sender_id": sender_id,
            "side": "我" if origin == 1 else "对方",
            "type": base,
            "type_name": MSG_TYPES_CN.get(base, f"类型{base}"),
            "content": str(raw or "")[:500],
        }

    # ------------------------------------------------------------------
    def load_history_for(self, sender_id, limit=10, before_ts=None):
        """拉取某发送者的最近历史消息（含我/对方），升序返回。

        用于 AI 上下文构建（多轮对话）。sender_id 为消息里的 real_sender_id。
        """
        if not self.src or not self.key:
            return []
        tmp = tempfile.mktemp(suffix='.db')
        try:
            decrypt_database(self.src, tmp, self.key)
            conn = sqlite3.connect(tmp)
            try:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'Msg_%'")]
                # real_sender_id 是分片内行号，先全量拉最近若干行，解析出 wxid 后过滤
                limit2 = min(max(limit * 6, 120), 2000)
                rows = []
                for tbl in tables:
                    try:
                        n2id = load_name2id(conn)
                        for r in conn.execute(
                                f"SELECT local_id, server_id, local_type, real_sender_id, "
                                f"create_time, origin_source, message_content "
                                f"FROM [{tbl}] ORDER BY create_time DESC LIMIT {limit2}"):
                            r = list(r)
                            r[2] = _resolve_sender(r[2], n2id)
                            if r[2] == sender_id:
                                if before_ts and (r[3] or 0) >= int(before_ts):
                                    continue
                                rows.append(tuple(r))
                    except sqlite3.Error:
                        continue
                rows.sort(key=lambda r: r[3] or 0, reverse=True)
                return [self._format(r) for r in rows[:limit]]
            finally:
                conn.close()
        except Exception:
            return []
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------------
    def search_messages(self, keyword, limit=5):
        """按关键词搜索消息（内容解压后匹配，跨所有 Msg 分片）。

        用于“跟当前联系人聊天时，检索其他联系人相关消息并加入上下文”。
        返回消息列表（含 sender_id / side / time / content 截断）。
        """
        kw = str(keyword or '').strip()
        if not kw or not self.src or not self.key:
            return []
        tmp = tempfile.mktemp(suffix='.db')
        try:
            decrypt_database(self.src, tmp, self.key)
            conn = sqlite3.connect(tmp)
            try:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'Msg_%'")]
                hits = []
                for tbl in tables:
                    try:
                        rows = conn.execute(
                            f"SELECT local_id, server_id, local_type, real_sender_id, "
                            f"create_time, origin_source, message_content "
                            f"FROM [{tbl}] ORDER BY create_time DESC LIMIT 500"
                        ).fetchall()
                    except sqlite3.Error:
                        continue
                    n2id = load_name2id(conn)
                    for row in rows:
                        content = row[5]
                        if isinstance(content, bytes):
                            try:
                                content = decompress_content(content)
                            except Exception:
                                continue
                        if isinstance(content, bytes):
                            try:
                                content = content.decode('utf-8', errors='replace')
                            except Exception:
                                content = ''
                        if kw in str(content or ''):
                            r2 = list(row)
                            r2[2] = _resolve_sender(r2[2], n2id)
                            hits.append((tuple(r2), str(content or '')))
                hits.sort(key=lambda r: r[0][3] or 0, reverse=True)
                out = []
                for row, content in hits[:limit]:
                    m = self._format(row)
                    m['content'] = content[:300]
                    out.append(m)
                return out
            finally:
                conn.close()
        except Exception:
            return []
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------------
    def baseline(self) -> int:
        """初始基准：清空去重集合，从当前窗口开始监控（不预上报历史）。"""
        self._seen = set()
        self.last_ts = 0
        return self.last_ts

    # ------------------------------------------------------------------
    def poll_once(self):
        """轮询一次，返回本轮【新】消息列表（窗口内、未上报过）。"""
        self.stats["scans"] += 1
        rows = self._fetch_new()
        out = []
        for tbl, r in rows:
            # 唯一标识：server_id（无则 local_id），跨重启稳定
            key = str(r[1] or r[0])
            if key in self._seen:
                continue
            self._seen.add(key)
            out.append(self._format(r))
        if len(self._seen) > self._seen_lim:
            self._seen = set(list(self._seen)[-self._seen_lim:])
        if rows:
            self.last_ts = max((r[3] or 0) for _t, r in rows)
        self.stats["new_messages"] += len(out)
        return out

    # ------------------------------------------------------------------
    def watch(self, interval=1.0, on_message=None, run_seconds=None,
              stop_event=None):
        """持续监控。on_message(msg) 回调；None 时打印。"""
        if on_message is None:
            def on_message(m):
                print(f"[新消息] {m['time']} {m['side']:4s} "
                      f"{m['type_name']:4s} {m['content'][:120]}")

        if not self.src or not self.key:
            print("监控器初始化失败：未找到微信数据库或密钥")
            return self.stats

        base = self.baseline()
        # 预热：把窗口内已有消息标记为已见（启动不把历史当新消息上报）
        try:
            self.poll_once()
        except Exception:
            pass
        print(f"监控已启动 | 库: {os.path.basename(self.src)} | "
              f"扫描窗口: 最近 {self.window_seconds}s | "
              f"基准时间: {time.strftime('%H:%M:%S', time.localtime(base))} | "
              f"轮询间隔 {interval}s")

        t0 = time.time()
        try:
            while True:
                msgs = self.poll_once()
                for m in msgs:
                    on_message(m)
                if stop_event is not None and stop_event.is_set():
                    break
                if run_seconds is not None and time.time() - t0 >= run_seconds:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        print(f"监控结束 | 共扫描 {self.stats['scans']} 次 | "
              f"新消息 {self.stats['new_messages']} 条 | "
              f"错误 {self.stats['errors']} 次")
        return self.stats


def watch(interval=1.0, on_message=None, run_seconds=None, stop_event=None,
          db_storage=None) -> dict:
    """便捷入口。"""
    return MessageMonitor(db_storage).watch(
        interval=interval, on_message=on_message,
        run_seconds=run_seconds, stop_event=stop_event)


# ---------------------------------------------------------------------------
# CLI：python my_automation/monitor.py [--seconds N] [--interval S]
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(prog="my_automation.monitor",
                                 description="监控微信新消息（每秒解析数据库）")
    ap.add_argument("--seconds", type=int, default=None, help="运行秒数(默认持续直到Ctrl+C)")
    ap.add_argument("--interval", type=float, default=1.0, help="轮询间隔秒数(默认1)")
    args = ap.parse_args()
    watch(interval=args.interval, run_seconds=args.seconds)


if __name__ == "__main__":
    main()