"""模拟"另一台机器"加入正在运行的引擎房间。

独立进程，真实 ChatClient 连到引擎里运行的 ChatServer，验证：
连接 → join 握手 → 收到成员/历史 → 发一条消息 → 收房主/其他人消息。

用法（在 editor 目录下跑）：
    python plugins/LANChat/join_probe.py --ip 192.168.0.75 --room 房间号 --password 密码 --nick 测试客户端

参数都有默认值，按你开房时填的改。Ctrl+C 退出。
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Windows 终端默认 GBK，强制 stdout 用 UTF-8 避免中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 让脚本能 import plugins.LANChat.server.*
EDITOR_ROOT = Path(__file__).resolve().parents[2]  # -> editor/
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))

from plugins.LANChat.server.chat_client import ChatClient


def _on_event(event: dict) -> None:
    """ChatClient 推来的前端事件，直接打印（flush 确保实时可见）。"""
    ev = event.get("event")
    if ev == "message":
        print(f"  [消息] {event.get('from')}: {event.get('text')}", flush=True)
    elif ev == "member_update":
        print(f"  [成员变更] {event.get('members')}", flush=True)
    elif ev == "agent_roster":
        print(f"  [AI助手名册] {event.get('agents')}", flush=True)
    elif ev == "reconnecting":
        print("  [连接断开，正在重连…]", flush=True)
    elif ev == "reconnected":
        print(f"  [重连成功] 成员={event.get('members')}", flush=True)
    elif ev == "room_closed":
        print("  [房间已关闭]", flush=True)
    elif ev == "error":
        print(f"  [错误] {event.get('code')}", flush=True)
    else:
        print(f"  [事件] {event}", flush=True)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ip", default="127.0.0.1", help="房主 IP（本机自连用 127.0.0.1）")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--room", default="", help="房间号（必须和开房时一致）")
    p.add_argument("--password", default="", help="密码（开房没设就留空）")
    p.add_argument("--nick", default="测试客户端")
    args = p.parse_args()

    print(f"==> 连接 {args.ip}:{args.port} 房间='{args.room}' 昵称='{args.nick}'")
    client = ChatClient(
        ip=args.ip, port=args.port, room=args.room,
        password=args.password, nickname=args.nick, on_event=_on_event,
    )
    result = await client.connect()
    if not result.get("ok"):
        print(f"==> 加入失败：{result.get('code') or result}")
        return

    print(f"==> 加入成功！我的昵称={result.get('you')} "
          f"当前成员={result.get('members')} 历史条数={len(result.get('history', []))}")
    if result.get("history"):
        print("==> 历史消息：")
        for m in result["history"]:
            print(f"     {m.get('from')}: {m.get('text')}")

    # 发一条测试消息（房主端应能看到）
    await asyncio.sleep(0.5)
    test_text = f"你好，我是 {args.nick}，从另一个进程加入了"
    print(f"==> 发送测试消息：{test_text}")
    await client.send_message(test_text)

    # 持续接收 30 秒，期间你在引擎里发消息这边能收到
    print("==> 保持连接 30 秒，接收消息中（你可以在引擎里发消息看这里是否收到）…")
    try:
        await asyncio.sleep(30)
    except asyncio.CancelledError:
        pass
    finally:
        print("==> 离开房间")
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n==> 已退出")
