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


class MessageMonitor:
    """微信新消息监控器。"""

    def __init__(self, db_storage=None):
        self.src = None
        self.key = None
        self.last_ts = 0            # 上次已见的最大 create_time
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
    def _fetch_new(self, max_rows=200):
        """解密并扫描 create_time > last_ts 的新消息。返回消息列表（升序）。

        每表按时间**降序**取最新 max_rows 条再合并，避免升序+LIMIT 截断
        只留下最旧的记录（首轮会把整库历史当作"新消息"）。
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
                rows = []
                for tbl in tables:
                    try:
                        rows += conn.execute(
                            f"SELECT local_id, local_type, real_sender_id, "
                            f"create_time, origin_source, message_content "
                            f"FROM [{tbl}] WHERE create_time > ? "
                            f"ORDER BY create_time DESC LIMIT {max_rows}",
                            (self.last_ts,)).fetchall()
                    except sqlite3.Error:
                        continue
                rows.sort(key=lambda r: r[3] or 0)
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
    @staticmethod
    def _format(row):
        local_id, ltype, sender_id, ctime, origin, raw = row
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
                cond = "real_sender_id = ?"
                params = [sender_id]
                if before_ts:
                    cond += " AND create_time < ?"
                    params.append(int(before_ts))
                rows = []
                for tbl in tables:
                    try:
                        rows += conn.execute(
                            f"SELECT local_id, local_type, real_sender_id, "
                            f"create_time, origin_source, message_content "
                            f"FROM [{tbl}] WHERE {cond} "
                            f"ORDER BY create_time DESC LIMIT {limit}",
                            params).fetchall()
                    except sqlite3.Error:
                        continue
                rows.sort(key=lambda r: r[3] or 0)
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
    def baseline(self) -> int:
        """初始基准：记录当前库内**最新**消息时间，作为"已见"起点。

        直接对每个 Msg_ 表取 MAX(create_time)，不再依赖被 LIMIT 截断
        的样本（旧实现取最早 200 条中的最大值，基线过旧导致首轮
        把整库历史当"新消息"轰出）。
        """
        if not self.src or not self.key:
            return 0
        tmp = tempfile.mktemp(suffix='.db')
        try:
            decrypt_database(self.src, tmp, self.key)
            conn = sqlite3.connect(tmp)
            try:
                mx = 0
                for r in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name LIKE 'Msg_%'"):
                    try:
                        v = conn.execute(
                            f"SELECT MAX(create_time) FROM [{r[0]}]").fetchone()[0]
                        mx = max(mx, v or 0)
                    except sqlite3.Error:
                        continue
                self.last_ts = mx
            finally:
                conn.close()
        except Exception:
            pass
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return self.last_ts

    # ------------------------------------------------------------------
    def poll_once(self):
        """轮询一次，返回本轮新消息列表。"""
        self.stats["scans"] += 1
        rows = self._fetch_new()
        out = []
        for r in rows:
            out.append(self._format(r))
        if rows:
            self.last_ts = max((r[3] or 0) for r in rows)
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
        print(f"监控已启动 | 库: {os.path.basename(self.src)} | "
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