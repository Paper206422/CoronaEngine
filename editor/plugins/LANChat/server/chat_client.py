"""WebSocket 客户端（加入方）。

职责：
- 连接房主的 WebSocket 服务，发送 join 完成握手。
- 持续接收服务器消息，经 on_event 回调推给本机前端。
- 发送聊天消息 / 离开通知。
- 断线自动重连（P2）：指数退避重连 + 重新 join 补发历史。

运行模型：在加入方插件的后台事件循环线程中运行。connect() 完成首次握手后
启动单一 _main_loop() supervisor，在其内循环 连接→接收→重连→连接→接收，
消除 P2 初版的递归自调度与双 recv_loop 重叠窗口。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from . import protocol
from .protocol import MsgType

logger = logging.getLogger(__name__)

# 接收到服务器消息时的回调：参数为前端事件 dict（已含 channel 标记）
EventCallback = Callable[[dict], None]

# 重连参数
_RECONNECT_MAX_ATTEMPTS = 6
_RECONNECT_BASE_DELAY = 0.5  # 秒，指数退避起点
_RECONNECT_MAX_DELAY = 8.0   # 秒，单次退避上限


class ChatClient:
    """加入方 WebSocket 客户端，支持断线自动重连。

    生命周期由一个 _main_loop() supervisor 统一管理：
    连接 → 接收消息 →（断线）→ 重连 → 连接 → … 直到主动退出或重连耗尽。
    """

    def __init__(
        self,
        ip: str,
        port: int,
        room: str,
        password: str,
        nickname: str,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.ip = ip
        self.port = port
        self.room = room
        self.password = password
        self.nickname = nickname
        self._on_event = on_event
        self._ws: Optional[ClientConnection] = None
        self._main_task: Optional[asyncio.Task] = None
        self._final_name: str = nickname
        self._closing = False  # 主动离开标记，区分用户离开 vs 服务器断开

        # owner 侧：agent 执行器 + 本机持有的 agent（agent_id -> {"name","persona"}）
        self._agent_runner = None
        self._agents_owned: dict = {}
        self._loop_runner = None  # 提交阻塞推理的线程池（main.py 注入）

    @property
    def final_name(self) -> str:
        return self._final_name

    # ---- 生命周期 -------------------------------------------------------
    async def connect(self) -> dict:
        """首次连接并完成 join 握手，成功后启动 _main_loop supervisor。

        Returns:
            {"ok": True, "members": [...], "history": [...], "you": "..."}
            或 {"ok": False, "code": "..."}。
        """
        result = await self._try_join()
        if result.get("ok"):
            # 启动唯一 supervisor task，取代 P1 的 _recv_loop 自递归
            self._main_task = asyncio.create_task(self._main_loop())
        return result

    async def disconnect(self) -> None:
        """主动离开房间（停止 supervisor 并关闭连接）。"""
        self._closing = True
        # 尝试向服务器发 leave 通知
        if self._ws is not None:
            try:
                await self._ws.send(
                    json.dumps(protocol.build_leave(self._final_name), ensure_ascii=False)
                )
            except websockets.ConnectionClosed:
                pass
        # 取消 supervisor，中断任何正在进行的重连 sleep
        if self._main_task is not None:
            self._main_task.cancel()
            self._main_task = None
        await self._close_ws()

    async def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    # ---- 收发 -----------------------------------------------------------
    async def send_message(self, text: str) -> None:
        """发送一条聊天消息。ws 为 None（重连间隔期）时静默跳过。"""
        if self._ws is None or not text:
            return
        try:
            await self._ws.send(
                json.dumps(
                    protocol.build_client_message(self._final_name, text),
                    ensure_ascii=False,
                )
            )
        except websockets.ConnectionClosed:
            pass  # 连接已断，交给 supervisor 触发重连

    # ---- supervisor -----------------------------------------------------
    async def _main_loop(self) -> None:
        """单一 supervisor：连接 + 接收 + 重连，消除递归自调度。"""
        while not self._closing:
            try:
                await self._recv_loop()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("[LANChat] _main_loop 异常")

            if self._closing:
                break

            # recv_loop 退出 + 非主动离开 → 进入重连
            self._emit(protocol.build_frontend_event("reconnecting"))
            await self._close_ws()

            if not await self._retry_join_loop():
                break

        if not self._closing:
            self._emit(protocol.build_frontend_event("room_closed"))

    async def _recv_loop(self) -> None:
        """纯消息接收：线上有一个已通过 join 握手的 ws 连接。"""
        assert self._ws is not None
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            self._handle(msg)
        # async for 正常退出或 ConnectionClosed → 回到 supervisor

    async def _retry_join_loop(self) -> bool:
        """指数退避重连 + join，成功 True，失败（耗尽或被拒）False。"""
        delay = _RECONNECT_BASE_DELAY
        for attempt in range(1, _RECONNECT_MAX_ATTEMPTS + 1):
            if self._closing:
                return False
            try:
                await asyncio.sleep(delay)
                result = await self._try_join()
                if result.get("ok"):
                    logger.info("[LANChat] 重连成功（第 %d 次）", attempt)
                    self._emit(
                        protocol.build_frontend_event(
                            "reconnected",
                            members=result.get("members", []),
                            history=result.get("history", []),
                            you=result.get("you", self._final_name),
                        )
                    )
                    # 补登记本机所有 agent（重连后房主名册可能已清掉）
                    for aid, info in list(self._agents_owned.items()):
                        try:
                            await self._ws.send(json.dumps(
                                protocol.build_agent_register(
                                    name=info["name"], persona=info["persona"],
                                    owner=self._final_name, agent_id=aid),
                                ensure_ascii=False))
                        except Exception:  # noqa: BLE001
                            pass
                    return True
                # join 被拒（房间已关 / 密码变更）→ 不再重试
                logger.info("[LANChat] 重连后 join 被拒: %s", result.get("code"))
                return False
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.info("[LANChat] 重连第 %d 次失败: %s", attempt, exc)
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
        return False

    async def _try_join(self) -> dict:
        """建立 WebSocket 连接并完成一次 join 握手（首连与重连共用）。"""
        uri = f"ws://{self.ip}:{self.port}"
        self._ws = await websockets.connect(uri)
        await self._ws.send(
            json.dumps(
                protocol.build_join(self.room, self.password, self.nickname),
                ensure_ascii=False,
            )
        )
        raw = await self._ws.recv()
        msg = json.loads(raw)
        if msg.get("type") == MsgType.JOINED:
            self._final_name = msg.get("you") or self.nickname
            return {
                "ok": True,
                "members": msg.get("members", []),
                "history": msg.get("history", []),
                "you": self._final_name,
            }
        if msg.get("type") == MsgType.ERROR:
            await self._close_ws()
            return {"ok": False, "code": msg.get("code", protocol.ErrorCode.BAD_REQUEST)}
        await self._close_ws()
        return {"ok": False, "code": protocol.ErrorCode.BAD_REQUEST}

    # ---- 消息处理 -------------------------------------------------------
    def _handle(self, msg: dict) -> None:
        """把服务器消息映射为前端事件。"""
        mtype = msg.get("type")
        if mtype == MsgType.MESSAGE:
            self._emit(
                protocol.build_frontend_event(
                    "message",
                    **{"from": msg.get("from"), "text": msg.get("text"), "ts": msg.get("ts")},
                )
            )
        elif mtype == MsgType.MEMBER_UPDATE:
            self._emit(protocol.build_frontend_event("member_update", members=msg.get("members", [])))
        elif mtype == MsgType.ERROR:
            self._emit(protocol.build_frontend_event("error", code=msg.get("code")))
        elif mtype == MsgType.AGENT_TRIGGER:
            if self._loop_runner is not None:
                self._loop_runner.run_coro_nowait(self._handle_agent_trigger(msg))
            else:
                # 测试/降级：直接 schedule（在 asyncio.run 下可用）
                asyncio.get_event_loop().create_task(self._handle_agent_trigger(msg))
        elif mtype == MsgType.PONG:
            pass

    # ---- agent（owner 侧）-----------------------------------------------
    async def _handle_agent_trigger(self, msg: dict) -> None:
        """收到房主派活：本机推理后回交 agent_reply。"""
        agent_id = msg.get("agent_id", "")
        trigger_id = msg.get("trigger_id", "")
        # 优先用触发里带的 persona（房主权威，避免 agent_id 重分配导致本地查不到）；
        # 兜底用本地登记的人设。
        persona = msg.get("persona") or self._agents_owned.get(agent_id, {}).get("persona", "")
        try:
            if self._agent_runner is None:
                raise RuntimeError("no agent runner")
            text = await self._run_agent_blocking(
                persona, msg.get("history", {}), msg.get("trigger_msg", {})
            )
            await self._send_agent_reply(
                protocol.build_agent_reply(agent_id, trigger_id, text=text)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LANChat] agent 推理失败")
            await self._send_agent_reply(
                protocol.build_agent_reply(agent_id, trigger_id, error=str(exc))
            )

    async def _run_agent_blocking(self, persona: str, history: dict, trigger_msg: dict) -> str:
        """把阻塞的 runner.run 丢到默认线程池执行。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._agent_runner.run, persona, history, trigger_msg
        )

    async def _send_agent_reply(self, message: dict) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(message, ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass

    async def register_agent(self, agent_id: str, name: str, persona: str) -> None:
        """owner 向房主登记 agent，并在本机记下 name+persona 供后续推理/重连补登记。"""
        self._agents_owned[agent_id] = {"name": name, "persona": persona}
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(
                protocol.build_agent_register(name=name, persona=persona,
                                              owner=self._final_name, agent_id=agent_id),
                ensure_ascii=False,
            ))
        except websockets.ConnectionClosed:
            pass

    async def remove_agent(self, agent_id: str) -> None:
        self._agents_owned.pop(agent_id, None)
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(protocol.build_agent_remove(agent_id),
                                           ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass

    def _emit(self, event: dict) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:  # noqa: BLE001
            logger.exception("[LANChat] ChatClient on_event 回调异常")
