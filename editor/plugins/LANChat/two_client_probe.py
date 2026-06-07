"""双客户端互通测试：两个独立进程都连到引擎里运行的房间，
A 发消息验证 B 能否收到，纯自动、不依赖手动操作时机。

用法（editor 目录下）：
    python plugins/LANChat/two_client_probe.py --ip 192.168.0.75 --room 01 --password 123
"""

import argparse
import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

EDITOR_ROOT = Path(__file__).resolve().parents[2]
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))

from plugins.LANChat.server.chat_client import ChatClient


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ip", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--room", default="01")
    p.add_argument("--password", default="123")
    args = p.parse_args()

    a_got = []   # A 收到的消息
    b_got = []   # B 收到的消息

    client_a = ChatClient(ip=args.ip, port=args.port, room=args.room,
                          password=args.password, nickname="客户端A",
                          on_event=lambda e: a_got.append(e) if e.get("event") == "message" else None)
    client_b = ChatClient(ip=args.ip, port=args.port, room=args.room,
                          password=args.password, nickname="客户端B",
                          on_event=lambda e: b_got.append(e) if e.get("event") == "message" else None)

    ra = await client_a.connect()
    rb = await client_b.connect()
    print(f"A 加入: ok={ra.get('ok')} you={ra.get('you')} members={ra.get('members')}")
    print(f"B 加入: ok={rb.get('ok')} you={rb.get('you')} members={rb.get('members')}")
    if not (ra.get("ok") and rb.get("ok")):
        print("加入失败，终止"); return

    await asyncio.sleep(0.3)

    # A 发消息 → B 应收到
    print("\nA 发送: '这是A发给大家的消息'")
    await client_a.send_message("这是A发给大家的消息")
    await asyncio.sleep(1.0)
    b_texts = [e.get("text") for e in b_got]
    print(f"B 收到的消息: {b_texts}")
    assert any("这是A发给大家的消息" in (t or "") for t in b_texts), "❌ B 没收到 A 的消息"
    print("✅ A→B 方向通")

    # B 发消息 → A 应收到
    print("\nB 发送: '这是B的回复'")
    await client_b.send_message("这是B的回复")
    await asyncio.sleep(1.0)
    a_texts = [e.get("text") for e in a_got]
    print(f"A 收到的消息: {a_texts}")
    assert any("这是B的回复" in (t or "") for t in a_texts), "❌ A 没收到 B 的消息"
    print("✅ B→A 方向通")

    print("\n🎉 双客户端双向互通全部成功——局域网多人聊天链路正常")
    await client_a.disconnect()
    await client_b.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出")
