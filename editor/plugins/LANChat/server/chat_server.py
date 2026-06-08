"""WebSocket 服务端（房主侧）。

职责：
- 在指定端口起 websockets 服务。
- 处理 join / message / leave / ping 消息。
- 通过 RoomManager 管理房间状态。
- 广播消息给房间内所有连接。
- 通过 on_local_event 回调把消息推给房主本机前端（经 js_call_func）。

运行模型：服务在房主插件的后台事件循环线程中运行，所有 handler 在该单一
事件循环内串行执行，RoomManager 无需额外加锁。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Awaitable, Callable, Optional

import websockets
from websockets.asyncio.server import ServerConnection

from . import protocol
from .protocol import MsgType
from .room_manager import Agent, RoomManager, Room

logger = logging.getLogger(__name__)

# 房主本机事件回调签名：接收一个前端事件 dict（已含 channel 标记）
LocalEventCallback = Callable[[dict], None]

# ═══════════════════════════════════════════════════════════════════════════
# 场景指令关键词（与 cai_extensions.agent.agent_adapter 保持一致）
# ═══════════════════════════════════════════════════════════════════════════

_SCENE_KEYWORDS = [
    (r"(?:加个?|添加|放个?|增加|创建|新[增建]|导入)", "添加物体"),
    (r"(?:删[掉除]|移除|去掉|清除)", "删除物体"),
    (r"(?:把|将).{1,10}(?:移[动到]?|挪[动到]?)", "移动物体"),
    (r"(?:放大|缩小|变大|变小|旋转|改成?|调整|修改)", "修改物体"),
    (r"(?:布置|摆放|排列|安排|设计|规划|装饰|重新布置)", "布置场景"),
    (r"(?:灯光|光照|照明|氛围|环境光|光源|灯带|霓虹)", "调整灯光"),
    (r"(?:绿植|植物|盆栽|花|绿化)", "添加绿植"),
]

# 隐式指令模式：未 @ 也能触发 agent 的场景/生成类指令
import re as _re_module
_IMPLICIT_COMMAND_PATTERNS = [
    r"生成.{0,6}(?:3d|3D|模型|物体|场景)",
    r"(?:开始|帮我|请|麻烦).{0,4}(?:生成|制作|创建|布置|搭建|建模)",
    r"(?:加个?|添加|放个?|删[掉除]|移除).{1,20}",
    r"把.{1,15}(?:移|挪|放大|缩小|旋转|调整)",
    r"(?:布置|装饰|设计).{0,15}(?:场景|房间|卧室|客厅|酒吧)",
    r"^/(?:sc_agent|scene_agent)\b",
    r"执行.{0,10}(?:指令|操作|清单|方案)",
    # 场景组合类
    r"(?:按|根据|依据).{0,10}清单",
    r"清单.{0,6}(?:生成|布置|组合|导入|放|搭建)",
    r"(?:组合|搭建|布置|生成).{0,8}(?:整个|这个|场景|房间|卧室|客厅)",
    r"把.{0,12}(?:都|全部|所有).{0,8}(?:生成|放|布置|导入|建模)",
    r"一键(?:生成|布置|组合)",
]


def _is_implicit_agent_command(text: str) -> bool:
    """判断消息是否为可隐式触发 agent 的场景/生成指令（无需 @）。"""
    t = (text or "").strip()
    if not t or len(t) < 3:
        return False
    for pat in _IMPLICIT_COMMAND_PATTERNS:
        if _re_module.search(pat, t):
            return True
    return False


# 从 agent 回复中提取混元/3D 生成模型目录（用于生成完成后自动导入引擎）
_MODEL_DIR_PATTERNS = [
    r"(models[/\\]hunyuan_\d{8}_\d{6})",
    r"(models[/\\][A-Za-z0-9_\-]+[/\\]?)",
    r"目录[：:]\s*[`\"]?([^\s`\"]+)",
]


def _extract_model_dirs(text: str) -> list[str]:
    """从 agent 回复文本中提取 3D 模型目录路径（去重，保序）。"""
    if not text:
        return []
    seen: set[str] = set()
    dirs: list[str] = []
    for pat in _MODEL_DIR_PATTERNS:
        for m in _re_module.finditer(pat, text):
            raw = (m.group(1) or "").strip().rstrip("/\\")
            # 只接受看起来像 hunyuan/模型目录的路径
            if not raw or "hunyuan" not in raw.lower() and "models" not in raw.lower():
                continue
            if raw not in seen:
                seen.add(raw)
                dirs.append(raw)
    return dirs


def _extract_scene_instructions(batch: list[dict]) -> list[str]:
    """从一批聊天消息中提取可能的场景操作指令。

    返回去重后的指令描述列表（最多5条），供自动摘要后询问用户。
    """
    import re
    seen: set[str] = set()
    instructions: list[str] = []

    for msg in batch:
        text = (msg.get("text", "") or "").strip()
        if not text or len(text) < 2:
            continue
        for pattern, label in _SCENE_KEYWORDS:
            m = re.search(pattern, text)
            if m:
                # 用匹配到的原文 + 标签生成可读描述
                snippet = text[:60].replace("\n", " ")
                key = f"{label}:{snippet}"
                if key not in seen:
                    seen.add(key)
                    instructions.append(f"「{snippet}…」→ {label}")
                    if len(instructions) >= 5:
                        return instructions
                break  # 一条消息只归属一种类型

    return instructions


class ChatServer:
    """房主侧 WebSocket 服务端。"""

    def __init__(
        self,
        room_id: str,
        password: str = "",
        host: str = "0.0.0.0",
        port: int = 8770,
        on_local_event: Optional[LocalEventCallback] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.room_manager = RoomManager()
        self.room: Room = self.room_manager.create_room(room_id, password)
        self._on_local_event = on_local_event
        self._server: Optional[websockets.asyncio.server.Server] = None
        # owner 侧 agent 执行 / 房主侧摘要：由 main.py 注入（测试时可为 None）
        self._agent_runner = None      # AgentRunner（房主自有 agent 本地直跑用）
        self._summary_service = None   # SummaryService（房主摘要用）
        self._loop_runner = None       # 提交阻塞任务的线程池（main.py 注入）
        self._pending_triggers: dict[str, str] = {}  # trigger_id -> agent_id（对账防重）

    # ---- 生命周期 -------------------------------------------------------
    async def start(self) -> None:
        """启动 WebSocket 服务。"""
        self._server = await websockets.serve(self._handler, self.host, self.port)
        logger.info(
            "[LANChat] ChatServer 启动 room=%s host=%s port=%s",
            self.room.room_id,
            self.host,
            self.port,
        )

    async def stop(self) -> None:
        """停止服务，关闭所有连接。"""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.room_manager.close_room()
        logger.info("[LANChat] ChatServer 已停止")

    # ---- 连接处理 -------------------------------------------------------
    async def _handler(self, ws: ServerConnection) -> None:
        """单个客户端连接的生命周期。"""
        try:
            async for raw in ws:
                await self._dispatch(ws, raw)
        except websockets.ConnectionClosed:
            pass
        except Exception:  # noqa: BLE001 - handler 不应让异常杀掉连接循环
            logger.exception("[LANChat] handler 处理异常")
        finally:
            await self._on_disconnect(ws)

    async def _dispatch(self, ws: ServerConnection, raw: str | bytes) -> None:
        """解析并分发一条消息。"""
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._send(ws, protocol.build_error(protocol.ErrorCode.BAD_REQUEST))
            return

        msg_type = msg.get("type")
        if msg_type == MsgType.JOIN:
            await self._on_join(ws, msg)
        elif msg_type == MsgType.MESSAGE:
            await self._on_message(ws, msg)
        elif msg_type == MsgType.LEAVE:
            await self._on_disconnect(ws)
        elif msg_type == MsgType.AGENT_REGISTER:
            await self._on_agent_register(ws, msg)
        elif msg_type == MsgType.AGENT_REMOVE:
            await self._on_agent_remove(ws, msg)
        elif msg_type == MsgType.AGENT_REPLY:
            await self._on_agent_reply(ws, msg)
        elif msg_type == MsgType.PING:
            await self._send(ws, protocol.build_pong())
        else:
            await self._send(ws, protocol.build_error(protocol.ErrorCode.BAD_REQUEST))

    async def _on_join(self, ws: ServerConnection, msg: dict) -> None:
        """处理加入请求。"""
        room_id = msg.get("room", "")
        if room_id != self.room.room_id:
            await self._send(ws, protocol.build_error(protocol.ErrorCode.ROOM_NOT_FOUND))
            return

        result = self.room.try_join(
            ws,
            password=msg.get("password", ""),
            nickname=msg.get("nickname", "用户"),
        )
        if not result.ok:
            await self._send(ws, protocol.build_error(result.error or protocol.ErrorCode.BAD_REQUEST))
            return

        # 给新成员下发 joined（成员 + 历史 + 本人最终昵称）
        await self._send(
            ws,
            protocol.build_joined(
                self.room.member_names(),
                self.room.history_snapshot(),
                you=result.final_name,
            ),
        )
        # 广播成员变更给其他人
        await self._broadcast(
            protocol.build_member_update(self.room.member_names()),
            exclude=ws,
        )
        logger.info("[LANChat] %s 加入房间 %s", result.final_name, self.room.room_id)

    async def _on_message(self, ws: ServerConnection, msg: dict) -> None:
        """处理聊天消息：盖章、记录、广播，然后做 @ 解析与 agent 派发。"""
        sender = self.room.name_of(ws)
        if sender is None:
            await self._send(ws, protocol.build_error(protocol.ErrorCode.BAD_REQUEST))
            return
        text = msg.get("text", "")
        if not text:
            return
        stamped = self.room_manager.stamp_and_record(self.room, sender, text)
        await self._broadcast(stamped)
        # 人类消息触发 @ 派发（agent 回复不会走到这里，故无连锁）
        await self._dispatch_mentions(stamped)
        # 历史越界则异步压缩（不阻塞）
        self._maybe_compress()

    # ---- agent 编排 -----------------------------------------------------
    async def _on_agent_register(self, ws: ServerConnection, msg: dict) -> None:
        """owner 登记 agent。owner 必须是房内成员。"""
        owner = self.room.name_of(ws)
        if owner is None:
            await self._send(ws, protocol.build_error(protocol.ErrorCode.BAD_REQUEST))
            return
        self.room.add_agent(
            name=msg.get("name", "助手"),
            persona=msg.get("persona", ""),
            owner=owner,
        )
        await self._broadcast_roster()

    async def _on_agent_remove(self, ws: ServerConnection, msg: dict) -> None:
        """owner 注销自己的 agent。"""
        owner = self.room.name_of(ws)
        agent = self.room.get_agent(msg.get("agent_id", ""))
        if agent is not None and agent.owner == owner:
            self.room.remove_agent(agent.agent_id)
            await self._broadcast_roster()

    async def _broadcast_roster(self) -> None:
        """广播 agent 名册变更给全群（含房主本机前端）。"""
        await self._broadcast(protocol.build_agent_roster(self.room.agent_roster()))

    async def _on_agent_reply(self, ws: ServerConnection | None, msg: dict) -> None:
        """owner 回交 agent 结果：对账 trigger_id → 广播（from=agent名）。"""
        trigger_id = msg.get("trigger_id", "")
        agent_id = self._pending_triggers.pop(trigger_id, None)
        logger.info("[LANChat] _on_agent_reply: trigger_id=%s, agent_id=%s", trigger_id, agent_id)
        if agent_id is None or agent_id != msg.get("agent_id"):
            logger.warning("[LANChat] _on_agent_reply: agent_id mismatch or unknown trigger")
            return  # 未知/重复 trigger，丢弃防串话
        agent = self.room.get_agent(agent_id)
        name = agent.name if agent is not None else "助手"
        error = msg.get("error")
        if error:
            logger.warning("[LANChat] _on_agent_reply: error=%s", error)
            await self._broadcast(protocol.build_message("系统", f"🤖 {name} 暂时无法回复"))
            return
        text = msg.get("text", "")
        logger.info("[LANChat] _on_agent_reply: got text from %s, length=%d", name, len(text))
        if not text:
            logger.warning("[LANChat] _on_agent_reply: empty text, skipping")
            return
        # agent 回复入历史并广播；不再做 @ 解析（杜绝 agent↔agent 连锁）
        stamped = self.room_manager.stamp_and_record(self.room, name, text)
        logger.info("[LANChat] _on_agent_reply: broadcasting reply: %r", text[:100])
        await self._broadcast(stamped)
        self._maybe_compress()

        # 自动导入：回复中若含 3D 模型目录，后台等待模型就绪后导入引擎
        model_dirs = _extract_model_dirs(text)
        if model_dirs:
            logger.info("[LANChat] _on_agent_reply: detected model dirs %s, auto-import", model_dirs)
            self._auto_import_models(model_dirs, name)

    def _auto_import_models(self, model_dirs: list[str], agent_name: str) -> None:
        """后台等待 3D 模型文件就绪后导入引擎场景，完成后广播结果。"""
        if self._loop_runner is None:
            return

        def _job():
            from .scene_import_helper import import_model_dirs_blocking
            return import_model_dirs_blocking(model_dirs)

        def _on_done(result):
            if result and result.get("imported"):
                names = "、".join(result["imported"])
                msg = f"🎉 已将生成的 3D 模型导入场景：{names}"
            elif result and result.get("error"):
                msg = f"⚠️ 模型导入失败：{result['error']}"
            else:
                msg = "⚠️ 模型文件未就绪或导入失败"
            self._loop_runner.run_coro_nowait(
                self._broadcast(self.room_manager.stamp_and_record(self.room, "系统", msg))
            )

        def _on_exc(exc):
            logger.warning("[LANChat] auto-import 异常: %s", exc, exc_info=True)
            self._loop_runner.run_coro_nowait(
                self._broadcast(self.room_manager.stamp_and_record(
                    self.room, "系统", f"⚠️ 模型导入出错：{exc}"))
            )

        self._loop_runner.submit_blocking(_job, _on_done, swallow_exc=True, on_exc=_on_exc)

    async def _dispatch_mentions(self, stamped: dict) -> None:
        """解析消息中的 @agent，对每个命中 agent 派发触发。

        增强：消息未显式 @ 但属于场景/生成指令时，自动派发给房间内第一个 agent
        （便于承接前面 AI 生成的物品清单，直接说"生成3d模型"即可）。
        """
        text = stamped.get("text", "")
        mentions = self.room.resolve_mentions(text)
        # 无显式 @ 但是场景指令 → fallback 到第一个 agent
        if not mentions and _is_implicit_agent_command(text):
            roster = self.room.agent_roster()
            if roster:
                first_id = roster[0]["agent_id"]
                mentions = [first_id]
                logger.info("[LANChat] 隐式指令派发: text=%r → agent %s", text, first_id)
        logger.info("[LANChat] _dispatch_mentions: text=%r, mentions=%s", text, mentions)
        for agent_id in mentions:
            agent = self.room.get_agent(agent_id)
            if agent is None:
                logger.warning("[LANChat] agent_id %s not found", agent_id)
                continue
            trigger_id = uuid.uuid4().hex
            self._pending_triggers[trigger_id] = agent_id
            view = self.room.history_view()
            logger.info("[LANChat] dispatching agent %s (owner=%s, HOST=%s)", agent.name, agent.owner, protocol.HOST_NICKNAME)
            if agent.owner == protocol.HOST_NICKNAME:
                logger.info("[LANChat] running local agent %s", agent.name)
                self._run_local_agent(agent, trigger_id, view, stamped)
            else:
                conn = self._connection_of(agent.owner)
                if conn is None:
                    self._pending_triggers.pop(trigger_id, None)
                    await self._broadcast(
                        protocol.build_message("系统", f"🤖 {agent.name} 当前离线")
                    )
                    continue
                await self._send(conn, protocol.build_agent_trigger(
                    agent_id=agent.agent_id,
                    trigger_id=trigger_id,
                    summary=view["summary"],
                    recent=view["recent"],
                    trigger_msg=stamped,
                    persona=agent.persona,
                ))

    def _connection_of(self, nickname: str) -> ServerConnection | None:
        """按昵称找成员连接（用于把 trigger 发给特定 owner）。"""
        for conn in self.room.connections():
            if self.room.name_of(conn) == nickname:
                return conn
        return None

    def _run_local_agent(self, agent: Agent, trigger_id: str, view: dict, stamped: dict) -> dict | None:
        """房主自有 agent：丢线程池跑，完成后经 run_coro_nowait 把结果
        当 agent_reply 处理。异步调度，不阻塞；调用方不等待回复。"""
        if self._agent_runner is None or self._loop_runner is None:
            logger.warning("[LANChat] _run_local_agent: agent_runner or loop_runner is None")
            self._pending_triggers.pop(trigger_id, None)
            return

        logger.info("[LANChat] _run_local_agent: submitting job for agent %s", agent.name)
        def _job():
            logger.info("[LANChat] _job: running agent inference for %s", agent.name)
            return self._agent_runner.run(agent.persona, view, stamped)

        def _on_done(text):
            reply = protocol.build_agent_reply(agent.agent_id, trigger_id, text=text)
            self._loop_runner.run_coro_nowait(self._on_agent_reply(None, reply))

        def _on_exc(exc):
            # 推理抛异常时回交 error，确保群聊收到提示而非静默卡住
            logger.warning("[LANChat] local agent %s 推理异常: %s", agent.name, exc, exc_info=True)
            reply = protocol.build_agent_reply(agent.agent_id, trigger_id, error=str(exc))
            self._loop_runner.run_coro_nowait(self._on_agent_reply(None, reply))

        self._loop_runner.submit_blocking(_job, _on_done, swallow_exc=True, on_exc=_on_exc)

    def _maybe_compress(self) -> None:
        """历史越界则把最老一批丢后台压缩；不阻塞。失败退化为文本截断。

        关键：take_compress_batch 会加 _compressing 锁，因此必须保证
        apply_summary（成功）或 append_summary_fallback（失败）总会被调用，
        否则锁永久卡死且 batch 丢失。用 swallow_exc + on_exc 兜底。

        增强：摘要成功后自动扫描对话中的场景指令，询问用户是否需要执行。
        """
        if self._summary_service is None or self._loop_runner is None:
            return
        batch = self.room.take_compress_batch()
        if not batch:
            return
        prev = self.room.history_view()["summary"]

        def _job():
            return asyncio.run(self._summary_service.compress(prev, batch))

        def _on_done(result):
            if result is None:
                self.room.append_summary_fallback(batch)
            else:
                self.room.apply_summary(result)
                # 扫描对话中的场景指令
                instructions = _extract_scene_instructions(batch)
                if instructions:
                    # 有场景指令 → 询问用户是否需要执行
                    self._loop_runner.run_coro_nowait(
                        self._ask_execute_instructions(instructions)
                    )
                else:
                    # 无场景指令 → 把摘要广播到聊天室
                    self._loop_runner.run_coro_nowait(
                        self._broadcast_summary(result)
                    )

        self._loop_runner.submit_blocking(
            _job, _on_done,
            swallow_exc=True,
            on_exc=lambda e: self.room.append_summary_fallback(batch),
        )

    async def _ask_execute_instructions(self, instructions: list[str]) -> None:
        """摘要后广播：询问用户是否需要执行历史中的场景指令。"""
        if not instructions:
            return
        items = "\n".join(f"  • {i}" for i in instructions[:5])
        tip = (
            f"📋 自动摘要完成！检测到讨论中可能包含以下场景指令：\n"
            f"{items}\n\n"
            f"需要我执行吗？直接 @我 并回复「执行」或指定某一条即可。"
        )
        stamped = self.room_manager.stamp_and_record(self.room, "系统", tip)
        await self._broadcast(stamped)

    async def _broadcast_summary(self, summary: str) -> None:
        """摘要完成后广播到聊天室（无场景指令时的静默总结）。"""
        if not summary or not summary.strip():
            return
        text = f"📋 聊天自动总结：\n{summary.strip()}"
        stamped = self.room_manager.stamp_and_record(self.room, "系统", text)
        await self._broadcast(stamped)

    async def _on_disconnect(self, ws: ServerConnection) -> None:
        """连接断开：移除成员及其名下 agent，广播成员与名册变更。"""
        name = self.room.remove(ws)
        if name is None:
            return
        logger.info("[LANChat] %s 离开房间 %s", name, self.room.room_id)
        removed_agents = self.room.remove_agents_of_owner(name)
        for tid, aid in list(self._pending_triggers.items()):
            if aid in set(removed_agents):
                self._pending_triggers.pop(tid, None)
        await self._broadcast(protocol.build_member_update(self.room.member_names()))
        if removed_agents:
            await self._broadcast_roster()

    # ---- 发送/广播 ------------------------------------------------------
    async def _send(self, ws: ServerConnection, message: dict) -> None:
        """向单个连接发送消息。"""
        try:
            await ws.send(json.dumps(message, ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass

    async def _broadcast(self, message: dict, exclude: Any = None) -> None:
        """广播给房间内所有连接，并发发送避免单慢客户端饥饿全房间。

        每个发送独立 5 秒超时；慢/断的连接不阻塞其他客户端。
        """
        payload = json.dumps(message, ensure_ascii=False)

        async def _send_one(conn: ServerConnection) -> None:
            try:
                await asyncio.wait_for(conn.send(payload), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("[LANChat] broadcast 发送超时，跳过连接")
            except websockets.ConnectionClosed:
                pass

        tasks = [
            asyncio.create_task(_send_one(conn))
            for conn in self.room.connections()
            if conn is not exclude
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # 推给房主本机前端（房主不通过 WS 连自己）
        self._emit_local(message)

    def _emit_local(self, message: dict) -> None:
        """把 WS 消息转换为前端事件并经回调推给本机前端。"""
        if self._on_local_event is None:
            return
        event = _to_frontend_event(message)
        if event is not None:
            try:
                self._on_local_event(event)
            except Exception:  # noqa: BLE001
                logger.exception("[LANChat] on_local_event 回调异常")


def _to_frontend_event(message: dict) -> Optional[dict]:
    """把跨机 WS 消息映射为前端事件信封（房主本机推送用）。"""
    mtype = message.get("type")
    if mtype == MsgType.MESSAGE:
        return protocol.build_frontend_event(
            "message",
            **{"from": message.get("from"), "text": message.get("text"), "ts": message.get("ts")},
        )
    if mtype == MsgType.MEMBER_UPDATE:
        return protocol.build_frontend_event("member_update", members=message.get("members", []))
    if mtype == MsgType.AGENT_ROSTER:
        return protocol.build_frontend_event("agent_roster", agents=message.get("agents", []))
    if mtype == MsgType.JOINED:
        return protocol.build_frontend_event(
            "joined",
            members=message.get("members", []),
            history=message.get("history", []),
        )
    if mtype == MsgType.ERROR:
        return protocol.build_frontend_event("error", code=message.get("code"))
    return None
