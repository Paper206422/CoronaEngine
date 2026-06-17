/**
 * 局域网聊天室状态（轻量 composable，单例 reactive store）。
 *
 * 项目未使用 Pinia，这里用 Vue reactive 提供一个模块级单例，行为类似 store：
 * - 持有连接态、房间信息、成员、消息列表。
 * - 提供 open/join/leave/send 等动作（封装 lanChatService 调用）。
 * - 暴露 handleEvent(event) 供 AITalkBar 的 receiveAIMessageChunk 在
 *   channel === 'lanchat' 时分流调用，更新本 store。
 *
 * 不直接监听 window 回调；由 AITalkBar 统一分流，避免与 AI 流式回调争用。
 */
import { reactive, readonly } from 'vue';
import { lanChatService } from '../utils/bridge.js';

// 连接状态机：idle（未进房）-> hosting/joined（在房）
const ROLE = { NONE: 'none', HOST: 'host', GUEST: 'guest' };

// 房主在房间内的显示昵称。必须与 C++ LANChat 快速通道保持一致；
// 房主消息由 NetworkSystem 用该名盖章，前端据此判定 self（消息气泡右对齐）。
const HOST_NICKNAME = '房主';

const state = reactive({
  role: ROLE.NONE, // none / host / guest
  inRoom: false,
  connection: 'idle', // idle / connecting / syncing / connected / reconnecting
  room: '', // 房间号
  ip: '', // 房主显示用：本机 IP；加入方：房主 IP
  port: 8770,
  peerId: '',
  nickname: '',
  members: [], // string[]
  memberDetails: [], // [{ member_id, nickname, status }]
  messages: [], // { message_id, sender_id, room_id, seq, from, text, ts, self }
  error: '', // 最近一次错误码/信息
  agents: [], // [{agent_id, name, owner}] 来自房主 agent_roster，不含 persona
  myAgents: [], // 我添加的 agent 本地草稿 [{agent_id, name, persona}]，用于显示"我的"
});

function _resetRoom() {
  state.role = ROLE.NONE;
  state.inRoom = false;
  state.connection = 'idle';
  state.room = '';
  state.ip = '';
  state.peerId = '';
  state.nickname = '';
  state.members = [];
  state.memberDetails = [];
  state.messages = [];
  state.error = '';
  state.agents = [];
  state.myAgents = [];
}

function resetAfterJoinFailure(code) {
  _resetRoom();
  state.error = code || 'JOIN_FAILED';
}

function isConnected() {
  return state.inRoom && state.connection === 'connected';
}

function isJoining() {
  return state.role === ROLE.GUEST && !state.inRoom && (
    state.connection === 'connecting' || state.connection === 'syncing'
  );
}

function messageSortKey(message) {
  const seq = Number(message.seq || 0);
  return seq > 0 ? seq : Number.MAX_SAFE_INTEGER;
}

function sortMessages() {
  state.messages.sort((a, b) => {
    const seqDiff = messageSortKey(a) - messageSortKey(b);
    if (seqDiff !== 0) return seqDiff;
    return String(a.message_id || '').localeCompare(String(b.message_id || ''));
  });
}

function messageSelf(msg, fallback = false) {
  if (msg.sender_id && state.peerId) {
    return msg.sender_id === state.peerId;
  }
  return fallback;
}

function parseMetadata(msg = {}) {
  if (msg.metadata && typeof msg.metadata === 'object') return msg.metadata;
  const raw = msg.metadata_json || '';
  if (!raw || typeof raw !== 'string') return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (e) {
    return {};
  }
}

function normalizeMessage(msg, self = false) {
  return {
    message_id: msg.message_id || '',
    sender_id: msg.sender_id || '',
    room_id: msg.room_id || state.room || '',
    seq: msg.seq || 0,
    from: msg.from || '?',
    text: msg.text || '',
    ts: msg.ts || Math.floor(Date.now() / 1000),
    sender_type: msg.sender_type || 'user',
    message_kind: msg.message_kind || 'chat',
    target_agent_id: msg.target_agent_id || '',
    source_user_id: msg.source_user_id || '',
    correlation_id: msg.correlation_id || '',
    metadata_json: msg.metadata_json || '',
    metadata: parseMetadata(msg),
    self: messageSelf(msg, self),
  };
}

function upsertMessage(msg, self = false) {
  const normalized = normalizeMessage(msg, self);
  const existing = normalized.message_id
    ? state.messages.find((m) => m.message_id === normalized.message_id)
    : null;
  if (existing) {
    Object.assign(existing, normalized);
  } else {
    state.messages.push(normalized);
  }
  sortMessages();
}

function applyHistorySnapshot(history = [], replace = false) {
  if (!Array.isArray(history)) return;
  if (replace) state.messages = [];
  for (const message of history) {
    upsertMessage(message, messageSelf(message, message.from === state.nickname));
  }
}

function normalizeMembers(payload = {}) {
  const memberDetails = Array.isArray(payload.member_details)
    ? payload.member_details
        .map((m) => ({
          member_id: m.member_id || m.id || '',
          nickname: m.nickname || m.name || '',
          status: m.status || 'online',
        }))
        .filter((m) => m.nickname)
    : [];
  const members = memberDetails.length
    ? memberDetails.map((m) => m.nickname)
    : (Array.isArray(payload.members) ? payload.members : [])
        .map((m) => (typeof m === 'string' ? m : (m.nickname || m.name || '')))
        .filter(Boolean);
  return { members, memberDetails };
}

function applyMemberSnapshot(payload = {}) {
  if (payload.peer_id) state.peerId = payload.peer_id;
  const normalized = normalizeMembers(payload);
  state.members = normalized.members;
  state.memberDetails = normalized.memberDetails;
}

function upsertAgent(agent = {}) {
  const agentId = agent.agent_id || agent.id || '';
  const name = agent.name || agent.agent_name || '';
  if (!agentId || !name) return;
  const normalized = {
    agent_id: agentId,
    name,
    owner: agent.owner || agent.owner_id || state.peerId || '',
    persona: agent.persona || '',
  };
  const existing = state.agents.find((item) => item.agent_id === agentId);
  if (existing) {
    Object.assign(existing, normalized);
  } else {
    state.agents.push(normalized);
  }
}

function removeAgentFromRoster(agentId) {
  state.agents = state.agents.filter((a) => a.agent_id !== agentId);
}

// ---- 动作 -----------------------------------------------------------------

/** 房主开房。返回 { ok, ip, port } 或 { ok:false, error }。 */
async function openRoom({ room, password, port }) {
  state.error = '';
  const res = await lanChatService.startRoom({ room, password, port });
  if (res && res.ok) {
    state.role = ROLE.HOST;
    state.inRoom = true;
    state.connection = 'connected';
    state.room = room;
    state.ip = res.ip;
    state.port = res.port;
    state.peerId = res.peer_id || '';
    state.nickname = HOST_NICKNAME;
    applyMemberSnapshot(res);
    if (!state.members.length) state.members = [HOST_NICKNAME];
    state.messages = [];
    state.agents = res.agents || [];
  } else {
    state.error = (res && res.error) || 'START_FAILED';
  }
  return res;
}

/** 房主关房。 */
async function closeRoom() {
  await lanChatService.stopRoom();
  _resetRoom();
}

/** 加入方加入房间。 */
async function joinRoom({ ip, port, room, password, nickname }) {
  state.error = '';
  const res = await lanChatService.joinRoom({ ip, port, room, password, nickname });
  if (res && res.ok) {
    state.role = ROLE.GUEST;
    state.inRoom = false;
    state.connection = 'connecting';
    state.room = room;
    state.ip = ip;
    state.port = port;
    state.peerId = res.peer_id || '';
    // 服务器去重后的最终昵称（如 Alice -> Alice-2）
    state.nickname = res.you || nickname;
    applyMemberSnapshot(res);
    applyHistorySnapshot(res.history || [], true);
    state.agents = res.agents || [];
  } else {
    state.error = (res && res.code) || (res && res.error) || 'JOIN_FAILED';
  }
  return res;
}

/** 加入方离开房间。 */
async function leaveRoom() {
  await lanChatService.leaveRoom();
  _resetRoom();
}

/** 发送一条消息。本地不乐观插入，统一由服务器广播回显，保证顺序与去重一致。 */
async function sendMessage(text, options = {}) {
  const trimmed = (text || '').trim();
  if (!trimmed || !state.inRoom) return;
  if (!isConnected()) {
    state.error = state.connection === 'syncing' ? 'SYNCING' : 'CONNECTING';
    return { ok: false, error: state.error };
  }
  const res = await lanChatService.sendMessage(trimmed, options);
  if (res && res.ok === false) {
    state.error = res.error || 'SEND_FAILED';
    if (state.error === 'CONNECTING') {
      state.connection = 'connecting';
    }
  } else {
    state.error = '';
  }
}

/** 添加 AI 助手。{ name, persona } */
async function addAgent({ name, persona }) {
  state.error = '';
  if (!isConnected()) {
    state.error = state.connection === 'syncing' ? 'SYNCING' : 'CONNECTING';
    return { ok: false, error: state.error };
  }
  let res;
  try {
    res = await lanChatService.addAgent({ name, persona });
  } catch (e) {
    state.error = 'ADD_AGENT_FAILED';
    return { ok: false, error: 'ADD_AGENT_FAILED' };
  }
  if (res && res.ok) {
    const added = { agent_id: res.agent_id, name: res.name || name, persona, owner: state.peerId };
    state.myAgents.push(added);
    upsertAgent(added);
  } else {
    state.error = (res && res.error) || 'ADD_AGENT_FAILED';
  }
  return res;
}

/** 移除 AI 助手。 */
async function removeAgent(agentId) {
  state.error = '';
  if (!isConnected()) {
    state.error = state.connection === 'syncing' ? 'SYNCING' : 'CONNECTING';
    return { ok: false };
  }
  try {
    await lanChatService.removeAgent(agentId);
  } catch (e) {
    state.error = 'REMOVE_AGENT_FAILED';
    return { ok: false };
  }
  state.myAgents = state.myAgents.filter((a) => a.agent_id !== agentId);
  removeAgentFromRoster(agentId);
  return { ok: true };
}

// ---- 事件分流（由 AITalkBar 调用）----------------------------------------

/**
 * 处理来自 C++ NetworkSystem 的聊天室事件（channel === 'lanchat'）。
 * @param {object} event - { channel, event, from, text, ts, members, history, code }
 */
function handleEvent(event) {
  if (!event || event.channel !== 'lanchat') return;
  switch (event.event) {
    case 'message':
      upsertMessage(event, event.from === state.nickname);
      break;
    case 'member_update':
      applyMemberSnapshot(event);
      if (state.role === ROLE.GUEST && state.connection === 'connecting') {
        state.connection = 'syncing';
        state.error = '';
      }
      break;
    case 'history_snapshot':
      applyHistorySnapshot(event.history || [], true);
      if (state.role === ROLE.GUEST && (state.connection === 'connecting' || state.connection === 'syncing')) {
        state.inRoom = true;
        state.connection = 'connected';
        state.error = '';
      }
      break;
    case 'agent_roster':
      state.agents = event.agents || [];
      break;
    case 'joined':
      applyMemberSnapshot(event);
      if (Array.isArray(event.history)) {
        applyHistorySnapshot(event.history, true);
      }
      break;
    case 'reconnecting':
      // 连接断开，正在自动重连：保留消息，仅切换状态供 UI 提示
      state.connection = 'reconnecting';
      state.error = '';
      break;
    case 'reconnected':
      // 重连成功：用服务器最新状态校正成员/历史与最终昵称
      state.connection = 'connected';
      state.error = '';
      if (event.you) state.nickname = event.you;
      applyMemberSnapshot({
        ...event,
        members: event.members || state.members,
        member_details: event.member_details || state.memberDetails,
      });
      if (Array.isArray(event.history)) {
        applyHistorySnapshot(event.history, true);
      }
      break;
    case 'room_closed':
      _resetRoom();
      state.error = 'ROOM_CLOSED';
      break;
    case 'error':
      state.error = event.code || 'ERROR';
      if (
        event.code === 'ROOM_NOT_FOUND' ||
        event.code === 'ROOM_MISMATCH' ||
        event.code === 'JOIN_TIMEOUT' ||
        event.code === 'HOST_UNREACHABLE'
      ) {
        resetAfterJoinFailure(event.code);
        break;
      }
      if (event.code === 'RECONNECT_FAILED' || event.code === 'RECONNECT_REJECTED') {
        state.connection = 'idle';
        state.inRoom = false;
      }
      break;
    default:
      break;
  }
}

export const lanchat = {
  state: readonly(state),
  ROLE,
  openRoom,
  closeRoom,
  joinRoom,
  leaveRoom,
  sendMessage,
  addAgent,
  removeAgent,
  handleEvent,
  isJoining,
};

export default lanchat;
