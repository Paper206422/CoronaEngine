"""LANChat 插件入口。

局域网聊天室：在现有 AI 对话面板（AITalkBar）内集成局域网多人文字聊天。
房主开房起 ChatServer，加入方起 ChatClient 连房主。所有跨机传输在 Python
侧完成；前端只通过 cefQuery 调用本插件，消息经 js_call_func 推回前端。

对外暴露给 cefQuery 的方法：
    start_room / stop_room / join_room / leave_room / send_message / get_local_ip
    add_agent / remove_agent / list_agents
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from concurrent.futures import Future
from typing import Optional

from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase

# load_utils.reimport() 用 spec_from_file_location 加载插件模块，
# __package__ 可能未设置，导致 from .server.xxx 相对导入失败。
# 确保完整父包链 plugins → plugins.LANChat 在 sys.modules 中。
import sys as _sys, os as _os, types as _types
_parts = __name__.split('.')[:-1]  # e.g. ['plugins', 'LANChat']
for _i in range(1, len(_parts) + 1):
    _p = '.'.join(_parts[:_i])
    if _p not in _sys.modules:
        _m = _types.ModuleType(_p)
        _m.__path__ = [_os.path.dirname(__file__)] if _i == len(_parts) else []
        _sys.modules[_p] = _m

from .server.chat_server import ChatServer
from .server.chat_client import ChatClient
from .server.protocol import HOST_NICKNAME
from .server.agent_runner import AgentRunner
from .server.summary_service import SummaryService

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8770
# 前端事件名：js_call_func(event_name, [payload]) → __coronaEmit → coronaEventBus
# 前端通过 coronaEventBus.on('lanchat-event', ...) 接收。
FRONTEND_EVENT = "lanchat-event"


class _LoopThread:
    """独立的后台 asyncio 事件循环线程，承载 LANChat 的所有网络 IO。"""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()  # loop 真正 run_forever 后置位
        self._lock = threading.Lock()    # 保护 loop/thread 创建，防 CEF 多线程并发竞态

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def ensure_running(self) -> None:
        # CEF query 来自线程池的多个线程，可能并发调用；加锁确保只起一个 loop
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                loop = self.loop
                self._ready.clear()
                self._thread = threading.Thread(
                    target=self._run, args=(loop,), name="LANChat_EventLoop", daemon=True
                )
                self._thread.start()
                logger.info("[LANChat] 事件循环线程已启动")
        # 等待 loop 真正进入 run_forever，否则 run_coroutine_threadsafe 提交的
        # 协程不会被调度，run_coro 会一直阻塞到超时。
        ok = self._ready.wait(timeout=5.0)
        if not ok:
            logger.error("[LANChat] 事件循环启动超时")

    def run_coro(self, coro, timeout: float = 10.0):
        """在后台循环里运行协程并阻塞等待结果（供同步 cefQuery 调用使用）。

        超时会抛 concurrent.futures.TimeoutError，由调用方转成错误返回，
        避免无限阻塞 CEF query 线程导致前端卡死/重试风暴。
        """
        self.ensure_running()
        logger.info("[LANChat] run_coro 提交协程到事件循环")
        future: Future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        result = future.result(timeout=timeout)
        logger.info("[LANChat] run_coro 协程完成")
        return result

    def run_coro_nowait(self, coro) -> None:
        """在后台循环里运行协程，不等待结果（fire-and-forget）。

        给返回的 future 挂完成回调，记录被吞掉的异常（如广播失败），
        避免静默丢失——否则前端会显示发送成功但消息实际未送达。
        """
        self.ensure_running()
        future: Future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        future.add_done_callback(self._log_future_exception)

    def submit_blocking(self, fn, on_done, swallow_exc: bool = False, on_exc=None) -> None:
        """在后台事件循环的默认线程池里跑阻塞函数 fn，完成后回调 on_done(result)。

        用于 agent 推理 / 摘要这类阻塞调用，避免堵住事件循环。
        swallow_exc=True 时异常不抛、转交 on_exc(e)。
        """
        self.ensure_running()

        async def _wrap():
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(None, fn)
            except Exception as exc:  # noqa: BLE001
                if swallow_exc and on_exc is not None:
                    on_exc(exc)
                    return
                raise
            if on_done is not None:
                on_done(result)

        self.run_coro_nowait(_wrap())

    @staticmethod
    def _log_future_exception(future: Future) -> None:
        try:
            exc = future.exception()
        except Exception:  # noqa: BLE001 - 取消或循环关闭
            return
        if exc is not None:
            logger.error("[LANChat] 后台协程异常: %r", exc)

    def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        # run_forever 开始后立即置位 _ready，通知等待方循环已可调度协程
        loop.call_soon(self._ready.set)
        loop.run_forever()
        loop.close()


def _detect_local_ip() -> str:
    """探测本机在局域网中的 IP（连一个外部地址看本地出口 IP，不真正发包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _make_agent_ai_chat():
    """构造 agent 推理回调 (system, messages)->str，调用本机 AITool/CAIApp。"""
    def ai_chat(system: str, messages: list) -> str:
        from plugins.AITool.main import AITool
        from Quasar.cai.protocol.request import ChatRequest
        convo = "\n".join(messages)
        text = f"{system}\n\n以下是群聊上下文：\n{convo}\n\n请以你的身份回复最新消息。"
        req = ChatRequest.from_text(text=text, metadata={"skip_conversation_store": True})
        chunks = AITool._cai_app.chat(req)
        return "".join(chunks).strip()
    return ai_chat


def _make_summary_ai_chat():
    """构造摘要回调 (prompt)->str，调用本机 AITool/CAIApp。"""
    def ai_chat(prompt: str) -> str:
        from plugins.AITool.main import AITool
        from Quasar.cai.protocol.request import ChatRequest
        req = ChatRequest.from_text(text=prompt, metadata={"skip_conversation_store": True})
        chunks = AITool._cai_app.chat(req)
        return "".join(chunks).strip()
    return ai_chat


@PluginBase.register_web("LANChat")
class LANChat(PluginBase):
    """局域网聊天室插件。房主与加入方共用本插件，运行态不同。"""

    _loop_thread = _LoopThread()
    _server: Optional[ChatServer] = None
    _client: Optional[ChatClient] = None
    _state_lock = threading.Lock()  # 串行化开房/关房/加入/离开，防 CEF 多线程并发重入
    # ---- 前端推送 -------------------------------------------------------
    @classmethod
    def _push_to_frontend(cls, event: dict) -> None:
        """把事件经 js_call_func 推给前端。

        js_call_func(event_name, args) → window.__coronaEmit(event_name, ...args)
        → coronaEventBus.emit。前端 coronaEventBus.on('lanchat-event') 接收。
        """
        try:
            CoronaEditor.js_call_func(FRONTEND_EVENT, [event])
        except Exception:  # noqa: BLE001
            logger.exception("[LANChat] 推送前端失败")

    # ---- 房主：开房 / 关房 ----------------------------------------------
    @classmethod
    def start_room(cls, payload: dict) -> dict:
        """房主开房，起 WebSocket 服务。

        Args:
            payload: {"room": str, "password": str, "port": int(可选)}
        Returns:
            {"ok": True, "ip": ..., "port": ...} 或 {"ok": False, "error": ...}
        """
        # CEF query 来自线程池多线程，前端超时重发会并发重入；非阻塞抢锁，
        # 抢不到说明已有一次开房在进行中，直接告知忙，避免重复起服务/卡死。
        print("[LANChat] start_room ENTERED", flush=True)
        if not cls._state_lock.acquire(blocking=False):
            return {"ok": False, "error": "BUSY"}
        try:
            if cls._server is not None:
                return {"ok": False, "error": "ROOM_ALREADY_OPEN"}
            room = str(payload.get("room", "")).strip()
            if not room:
                return {"ok": False, "error": "ROOM_REQUIRED"}
            password = str(payload.get("password", ""))
            port = int(payload.get("port", DEFAULT_PORT))

            server = ChatServer(
                room_id=room,
                password=password,
                host="0.0.0.0",
                port=port,
                on_local_event=cls._push_to_frontend,
            )
            # 先设 _server 再异步启动——调用方立即返回，不再阻塞 CEF 线程。
            cls._server = server
            server._summary_service = SummaryService(ai_chat=_make_summary_ai_chat())
            server._agent_runner = AgentRunner(ai_chat=_make_agent_ai_chat())
            server._loop_runner = cls._loop_thread
            ip = _detect_local_ip()
            cls._loop_thread.run_coro_nowait(server.start())
            result = {"ok": True, "ip": ip, "port": port, "room": room}
            print(f"[LANChat] start_room RETURNING {result}", flush=True)
            return result
        except Exception as exc:
            print(f"[LANChat] start_room EXCEPTION {exc}", flush=True)
            return {"ok": False, "error": str(exc)}
        finally:
            cls._state_lock.release()

    @classmethod
    def stop_room(cls, payload: dict | None = None) -> dict:
        """房主关房，停 WebSocket 服务。

        无论 stop() 是否超时/抛错，都把 _server 置 None——否则半开连接导致
        wait_closed 超时后状态锁死，之后永远无法再开房。
        """
        if cls._server is None:
            return {"ok": True}
        server = cls._server
        cls._server = None  # 先置空，确保即使 stop 超时也能重新开房
        try:
            cls._loop_thread.run_coro(server.stop())
            logger.info("[LANChat] 房间已关闭")
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LANChat] stop_room 失败（状态已重置）")
            return {"ok": False, "error": str(exc)}

    # ---- 加入方：加入 / 离开 --------------------------------------------
    @classmethod
    def join_room(cls, payload: dict) -> dict:
        """加入房间，起 WebSocket 客户端连房主。

        Args:
            payload: {"ip", "port", "room", "password", "nickname"}
        Returns:
            {"ok": True, "members": [...], "history": [...]} 或 {"ok": False, "code": ...}
        """
        if not cls._state_lock.acquire(blocking=False):
            return {"ok": False, "error": "BUSY"}
        try:
            if cls._client is not None:
                return {"ok": False, "error": "ALREADY_IN_ROOM"}
            ip = str(payload.get("ip", "")).strip()
            room = str(payload.get("room", "")).strip()
            if not ip or not room:
                return {"ok": False, "error": "IP_AND_ROOM_REQUIRED"}
            port = int(payload.get("port", DEFAULT_PORT))
            password = str(payload.get("password", ""))
            nickname = str(payload.get("nickname", "")).strip() or "用户"

            client = ChatClient(
                ip=ip,
                port=port,
                room=room,
                password=password,
                nickname=nickname,
                on_event=cls._push_to_frontend,
            )
            result = cls._loop_thread.run_coro(client.connect())
            if result.get("ok"):
                cls._client = client
                client._agent_runner = AgentRunner(ai_chat=_make_agent_ai_chat())
                client._loop_runner = cls._loop_thread
                logger.info("[LANChat] 已加入房间 room=%s @ %s:%s", room, ip, port)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LANChat] join_room 失败")
            return {"ok": False, "error": str(exc)}
        finally:
            cls._state_lock.release()

    @classmethod
    def leave_room(cls, payload: dict | None = None) -> dict:
        """加入方离开房间。

        无论 disconnect() 是否超时/抛错，都把 _client 置 None——否则状态锁死
        后无法再次加入房间。
        """
        if cls._client is None:
            return {"ok": True}
        client = cls._client
        cls._client = None  # 先置空，确保即使 disconnect 超时也能重新加入
        try:
            cls._loop_thread.run_coro(client.disconnect())
            logger.info("[LANChat] 已离开房间")
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LANChat] leave_room 失败（状态已重置）")
            return {"ok": False, "error": str(exc)}

    # ---- 收发消息 -------------------------------------------------------
    @classmethod
    def send_message(cls, payload: dict) -> dict:
        """发送一条聊天消息。房主走 server 广播，加入方走 client 发往房主。"""
        try:
            text = str(payload.get("text", ""))
            if not text:
                return {"ok": False, "error": "EMPTY_TEXT"}

            if cls._server is not None:
                # 房主：直接在 server 端盖章、记录、广播（含本机前端）
                room = cls._server.room
                stamped = cls._server.room_manager.stamp_and_record(room, HOST_NICKNAME, text)
                cls._loop_thread.run_coro_nowait(cls._server._broadcast(stamped))
                return {"ok": True}
            if cls._client is not None:
                cls._loop_thread.run_coro_nowait(cls._client.send_message(text))
                return {"ok": True}
            return {"ok": False, "error": "NOT_IN_ROOM"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LANChat] send_message 失败")
            return {"ok": False, "error": str(exc)}

    # ---- agent 管理 -----------------------------------------------------
    @classmethod
    def add_agent(cls, payload: dict) -> dict:
        """添加一个 AI 助手到当前房间。

        payload: {"name": str, "persona": str}
        房主：直接进本地名册并广播；guest：经 client 登记。
        """
        try:
            name = str(payload.get("name", "")).strip()
            if not name:
                return {"ok": False, "error": "NAME_REQUIRED"}
            persona = str(payload.get("persona", ""))
            if cls._server is not None:
                agent = cls._server.room.add_agent(name, persona, HOST_NICKNAME)
                cls._loop_thread.run_coro_nowait(cls._server._broadcast_roster())
                return {"ok": True, "agent_id": agent.agent_id, "name": agent.name}
            if cls._client is not None:
                import uuid as _uuid
                agent_id = f"agent-{_uuid.uuid4().hex[:8]}"
                cls._loop_thread.run_coro_nowait(
                    cls._client.register_agent(agent_id, name, persona))
                return {"ok": True, "agent_id": agent_id, "name": name}
            return {"ok": False, "error": "NOT_IN_ROOM"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LANChat] add_agent 失败")
            return {"ok": False, "error": str(exc)}

    @classmethod
    def remove_agent(cls, payload: dict) -> dict:
        """移除一个 AI 助手。payload: {"agent_id": str}"""
        try:
            agent_id = str(payload.get("agent_id", ""))
            if cls._server is not None:
                cls._server.room.remove_agent(agent_id)
                cls._loop_thread.run_coro_nowait(cls._server._broadcast_roster())
                return {"ok": True}
            if cls._client is not None:
                cls._loop_thread.run_coro_nowait(cls._client.remove_agent(agent_id))
                return {"ok": True}
            return {"ok": False, "error": "NOT_IN_ROOM"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[LANChat] remove_agent 失败")
            return {"ok": False, "error": str(exc)}

    @classmethod
    def list_agents(cls, payload: dict | None = None) -> dict:
        """列出当前房间 agent 名册（房主侧权威；guest 侧靠 agent_roster 事件维护前端）。"""
        if cls._server is not None:
            return {"ok": True, "agents": cls._server.room.agent_roster()}
        return {"ok": True, "agents": []}

    # ---- 工具 -----------------------------------------------------------
    @classmethod
    def get_local_ip(cls, payload: dict | None = None) -> dict:
        """返回本机局域网 IP。"""
        return {"ok": True, "ip": _detect_local_ip(), "port": DEFAULT_PORT}

    @classmethod
    def cleanup(cls) -> None:
        """插件清理：关房 / 离房。两者独立尝试，互不影响。"""
        if cls._server is not None:
            server = cls._server
            cls._server = None
            try:
                cls._loop_thread.run_coro(server.stop())
            except Exception:  # noqa: BLE001
                logger.exception("[LANChat] cleanup stop_room 异常")
        if cls._client is not None:
            client = cls._client
            cls._client = None
            try:
                cls._loop_thread.run_coro(client.disconnect())
            except Exception:  # noqa: BLE001
                logger.exception("[LANChat] cleanup leave_room 异常")
