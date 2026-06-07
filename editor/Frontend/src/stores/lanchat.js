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

// 房主在房间内的显示昵称。必须与 Python 端 protocol.HOST_NICKNAME 保持一致——
// 房主消息由服务器用该名盖章，前端据此判定 self（消息气泡右对齐）。
const HOST_NICKNAME = '房主';

const state = reactive({
  role: ROLE.NONE, // none / host / guest
  inRoom: false,
  connection: 'idle', // idle / connected / reconnecting
  room: '', // 房间号
  ip: '', // 房主显示用：本机 IP；加入方：房主 IP
  port: 8770,
  nickname: '',
  members: [], // string[]
  messages: [], // { from, text, ts, self }
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
  state.nickname = '';
  state.members = [];
  state.messages = [];
  state.error = '';
  state.agents = [];
  state.myAgents = [];
}

function _pushMessage(msg, self = false) {
  state.messages.push({
    from: msg.from || '?',
    text: msg.text || '',
    ts: msg.ts || Math.floor(Date.now() / 1000),
    self,
  });
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
    state.nickname = HOST_NICKNAME;
    state.members = [HOST_NICKNAME];
    state.messages = [];
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
    state.inRoom = true;
    state.connection = 'connected';
    state.room = room;
    state.ip = ip;
    state.port = port;
    // 服务器去重后的最终昵称（如 Alice -> Alice-2）
    state.nickname = res.you || nickname;
    state.members = res.members || [];
    state.messages = (res.history || []).map((m) => ({
      from: m.from,
      text: m.text,
      ts: m.ts,
      self: false,
    }));
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
async function sendMessage(text) {
  const trimmed = (text || '').trim();
  if (!trimmed || !state.inRoom) return;
  await lanChatService.sendMessage(trimmed);
}

/** 添加 AI 助手。{ name, persona } */
async function addAgent({ name, persona }) {
  state.error = '';
  let res;
  try {
    res = await lanChatService.addAgent({ name, persona });
  } catch (e) {
    state.error = 'ADD_AGENT_FAILED';
    return { ok: false, error: 'ADD_AGENT_FAILED' };
  }
  if (res && res.ok) {
    state.myAgents.push({ agent_id: res.agent_id, name: res.name || name, persona });
  } else {
    state.error = (res && res.error) || 'ADD_AGENT_FAILED';
  }
  return res;
}

/** 移除 AI 助手。 */
async function removeAgent(agentId) {
  state.error = '';
  try {
    await lanChatService.removeAgent(agentId);
  } catch (e) {
    state.error = 'REMOVE_AGENT_FAILED';
    return { ok: false };
  }
  state.myAgents = state.myAgents.filter((a) => a.agent_id !== agentId);
  return { ok: true };
}

// ---- 事件分流（由 AITalkBar 调用）----------------------------------------

/**
 * 处理来自 Python 的聊天室事件（channel === 'lanchat'）。
 * @param {object} event - { channel, event, from, text, ts, members, history, code }
 */
function handleEvent(event) {
  if (!event || event.channel !== 'lanchat') return;
  switch (event.event) {
    case 'message':
      _pushMessage(event, event.from === state.nickname);
      break;
    case 'member_update':
      state.members = event.members || [];
      break;
    case 'agent_roster':
      state.agents = event.agents || [];
      break;
    case 'joined':
      state.members = event.members || [];
      if (Array.isArray(event.history)) {
        state.messages = event.history.map((m) => ({
          from: m.from,
          text: m.text,
          ts: m.ts,
          self: false,
        }));
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
      state.members = event.members || state.members;
      if (Array.isArray(event.history)) {
        state.messages = event.history.map((m) => ({
          from: m.from,
          text: m.text,
          ts: m.ts,
          self: false,
        }));
      }
      break;
    case 'room_closed':
      state.error = 'ROOM_CLOSED';
      _resetRoom();
      break;
    case 'error':
      state.error = event.code || 'ERROR';
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
};

export default lanchat;
