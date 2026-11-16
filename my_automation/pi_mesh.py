# -*- coding: utf-8 -*-
"""
pi_mesh — 向 Pi 会话（agent mesh）发送消息
==========================================
通过 remote-pi 的本地 broker 命名管道，把文本作为一条消息送进目标 Pi 会话
（在 Pi 中以新 turn 输入的形式送达）。

用法：
    from pi_mesh import send
    send("你好，这是语音消息", target=r"C:\\Users\\86150\\Desktop\\微信数据@微信数据")

    # CLI
    python my_automation/pi_mesh.py "要发送的文本" [--target 地址] [--name 发送者名]

协议（remote-pi v0.5）：
    管道: \\\\.\\pipe\\remote-pi-broker-local-<user>
    → {"type":"register","name":N,"cwd":C}       (JSONL)
    ← {"type":"register_ack","address_assigned":A,...}
    → {"from":A,"to":TARGET,"id":UUID,"re":null,"body":{...}}
"""
import json
import os
import sys
import time
import uuid


def _pipe_path(user=None):
    user = user or os.environ.get('USERNAME') or os.environ.get('USER') or 'user'
    return rf"\\.\pipe\remote-pi-broker-local-{user}"


def _uuid7():
    """UUID v7（时间有序），与 remote-pi 一致。"""
    ts = int(time.time() * 1000)
    rnd = os.urandom(10)
    b = bytearray(16)
    for i in range(6):
        b[i] = (ts >> (8 * (5 - i))) & 0xFF
    b[6:16] = rnd
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def list_peers(timeout=2.0):
    """探测 broker，返回 peer 地址列表；失败返回 None。"""
    try:
        f = open(_pipe_path(), 'r+b', buffering=0)
        f.write(b'{"type":"list_peers"}\n')
        time.sleep(0.4)
        data = f.read(65536)
        f.close()
        for line in data.decode('utf-8', 'replace').splitlines():
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            body = msg.get('body') or {}
            if body.get('type') == 'list_peers_reply':
                return body.get('peers') or []
    except Exception:
        return None
    return None


def send(text, target, name='voice', cwd=None, body_type='voice',
         timeout=3.0, wait_ack=True):
    """把 text 作为一条 mesh 消息发给 target Pi 会话。

    返回 {"ok", "code", "message", "address", "ack"}
    """
    text = str(text or '').strip()
    if not text:
        return {"ok": False, "code": "ERR_EMPTY", "message": "文本为空"}
    if not target or '@' not in str(target):
        return {"ok": False, "code": "ERR_NO_TARGET",
                "message": f"目标地址无效: {target!r}（应为 <cwd>@<name>）"}
    cwd = cwd or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    try:
        f = open(_pipe_path(), 'r+b', buffering=0)
    except Exception as e:
        return {"ok": False, "code": "ERR_NO_BROKER",
                "message": f"无法连接 broker 管道: {type(e).__name__}: {e}"}

    try:
        # 1) 注册
        f.write((json.dumps({"type": "register", "name": name, "cwd": cwd})
                 + "\n").encode('utf-8'))
        time.sleep(0.3)
        address = None
        try:
            data = f.read(65536)
            for line in data.decode('utf-8', 'replace').splitlines():
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get('type') == 'register_ack':
                    address = msg.get('address_assigned')
                    break
        except Exception:
            pass
        if not address:
            address = f"{cwd}@{name}"

        # 2) 发送 envelope
        env = {"from": address, "to": target, "id": _uuid7(), "re": None,
               "body": {"type": body_type, "text": text}}
        f.write((json.dumps(env, ensure_ascii=False) + "\n").encode('utf-8'))
        time.sleep(0.4)

        ack = None
        if wait_ack:
            try:
                data = f.read(65536)
                for line in data.decode('utf-8', 'replace').splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    msg = json.loads(line)
                    b = msg.get('body') or {}
                    if b.get('type') == 'ack':
                        ack = b.get('status')
                        break
            except Exception:
                pass
    finally:
        try:
            f.close()
        except Exception:
            pass

    return {"ok": True, "code": "OK",
            "message": f"已发送给 {target}" + (f"（ACK: {ack}）" if ack else ""),
            "address": address, "ack": ack}


# ---------------------------------------------------------------------------
# CLI：python my_automation/pi_mesh.py "文本" [--target 地址] [--name 名] [--peers]
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(prog="pi_mesh", description="向 Pi 会话发送消息")
    ap.add_argument("text", nargs="?", help="要发送的文本")
    ap.add_argument("--target", default=r"C:\Users\86150\Desktop\微信数据@微信数据",
                    help="目标 peer 地址")
    ap.add_argument("--name", default="voice", help="发送者名")
    ap.add_argument("--peers", action="store_true", help="仅列出当前 peers")
    a = ap.parse_args()

    if a.peers:
        peers = list_peers()
        print("peers:" if peers else "broker 不可用")
        for p in peers or []:
            print("  ", p)
        return

    if not a.text:
        print("用法: python my_automation/pi_mesh.py \"文本\" [--target 地址]")
        return
    r = send(a.text, a.target, name=a.name)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
