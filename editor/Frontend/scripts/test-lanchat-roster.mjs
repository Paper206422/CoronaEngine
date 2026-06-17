import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(join(root, path), 'utf8');
const fail = (message) => {
  throw new Error(message);
};
const assertIncludes = (source, needle, message) => {
  if (!source.includes(needle)) fail(message);
};

const store = read('src/stores/lanchat.js');
const roomPanel = read('src/views/sidebar/lanchat/RoomPanel.vue');
const memberList = read('src/views/sidebar/lanchat/MemberList.vue');
const networkSystem = read('../../src/systems/network/network_system.cpp');

assertIncludes(store, 'peerId:', 'lanchat store must track local peerId');
assertIncludes(store, 'memberDetails:', 'lanchat store must track memberDetails');
assertIncludes(store, 'normalizeMembers', 'lanchat store must normalize member snapshots');
assertIncludes(store, 'upsertMessage', 'lanchat store must upsert messages by message_id');
assertIncludes(store, 'sortMessages', 'lanchat store must sort messages by authoritative sequence');
assertIncludes(store, "case 'history_snapshot'", 'lanchat store must consume LANChat history snapshots');
assertIncludes(store, 'resetAfterJoinFailure', 'lanchat store must clear fake rooms after join failure');
assertIncludes(store, "event.code === 'ROOM_NOT_FOUND'", 'lanchat store must handle missing LANChat room errors');
assertIncludes(store, "event.code === 'JOIN_TIMEOUT'", 'lanchat store must handle LANChat join timeout errors');
assertIncludes(store, 'function isJoining', 'lanchat store must expose pending join state');
assertIncludes(store, "case 'history_snapshot':", 'history snapshot must be the join success signal');
assertIncludes(store, 'msg.sender_id === state.peerId', 'lanchat store must prefer peerId for self messages');
assertIncludes(store, 'state.agents = res.agents || []', 'joinRoom must initialize agent roster');
assertIncludes(store, 'event.member_details', 'member_update must consume member_details');
assertIncludes(store, 'function upsertAgent', 'lanchat store must support local agent roster upsert');
assertIncludes(store, 'upsertAgent(added)', 'addAgent must make new agents immediately mentionable');
assertIncludes(store, 'removeAgentFromRoster(agentId)', 'removeAgent must clear local mention roster optimistically');
assertIncludes(store, 'sender_type:', 'lanchat store must preserve LANChat message v2 sender_type');
assertIncludes(store, 'message_kind:', 'lanchat store must preserve LANChat message v2 message_kind');
assertIncludes(store, 'correlation_id:', 'lanchat store must preserve LANChat message v2 correlation_id');
assertIncludes(store, 'metadata: parseMetadata(msg)', 'lanchat store must parse LANChat message v2 metadata');

assertIncludes(roomPanel, 'member.member_id !== s.peerId', 'mention candidates must filter local member_id');
assertIncludes(roomPanel, 'a.name, isAgent: true', 'mention candidates must include agents');
assertIncludes(roomPanel, ':peer-id="s.peerId"', 'MemberList must receive stable peerId');
assertIncludes(roomPanel, 'isJoining', 'RoomPanel must render pending join state');
assertIncludes(roomPanel, ':disabled="isJoining"', 'RoomPanel must disable join controls while pending');
assertIncludes(roomPanel, 'JOIN_TIMEOUT', 'RoomPanel must display join timeout errors');
assertIncludes(roomPanel, 'HOST_UNREACHABLE', 'RoomPanel must display unreachable host errors');
assertIncludes(roomPanel, 'function gmProposalId', 'RoomPanel must detect GM proposal ids');
assertIncludes(roomPanel, "message?.message_kind === 'gm_proposal'", 'RoomPanel must prefer LANChat v2 gm_proposal messages');
assertIncludes(roomPanel, 'String(message.correlation_id)', 'RoomPanel must use correlation_id as GM proposal id');
assertIncludes(roomPanel, "s.role === 'host'", 'RoomPanel must only show GM confirmation controls to host');
assertIncludes(roomPanel, 'function sendGmDecision', 'RoomPanel must send structured GM decisions');
assertIncludes(roomPanel, "message_kind: 'confirmation'", 'GM confirmation buttons must send structured confirmation');
assertIncludes(roomPanel, 'correlation_id: proposalId', 'GM confirmation must preserve proposal correlation_id');

assertIncludes(memberList, 'peerId', 'MemberList must accept peerId prop');
assertIncludes(memberList, 'a.owner === peerId', 'agent remove visibility must compare owner to peerId');

assertIncludes(networkSystem, 'if (impl_->session_role != SessionRole::Host) return;', 'clients must not process LANChat join packets');
assertIncludes(networkSystem, 'MessageType::CHAT_HISTORY_SNAPSHOT', 'NetworkSystem must handle LANChat history snapshots');
assertIncludes(networkSystem, 'MessageType::CHAT_JOIN_REJECT', 'NetworkSystem must handle LANChat join rejection');
assertIncludes(networkSystem, 'lanchat_join_pending', 'NetworkSystem must track pending LANChat joins');
assertIncludes(networkSystem, 'JOIN_TIMEOUT', 'NetworkSystem must emit LANChat join timeout errors');
assertIncludes(networkSystem, 'ROOM_NOT_FOUND', 'NetworkSystem must reject joins when no LANChat room is open');
assertIncludes(networkSystem, 'send_to_first_peer(impl_->peer_manager, packet)', 'clients must send LANChat packets to host instead of broadcasting loops');
assertIncludes(networkSystem, 'result = impl_->lanchat.record_message', 'host must assign authoritative LANChat message sequence');
assertIncludes(networkSystem, 'result = impl_->lanchat.apply_remote_message', 'clients must only apply authoritative LANChat messages');
assertIncludes(networkSystem, 'skipped history snapshot', 'missing join peer must not fall back to broadcasting history');
const chatJoinBranch = networkSystem.slice(
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_JOIN) {'),
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_JOIN_REJECT) {'),
);
if (chatJoinBranch.includes('impl_->lanchat.open_room(')) {
  fail('CHAT_JOIN handling must not implicitly create a LANChat room');
}
const joinRoomStart = store.indexOf('async function joinRoom');
const sendMessageStart = store.indexOf('async function sendMessage');
const joinRoomBody = store.slice(joinRoomStart, sendMessageStart);
if (joinRoomBody.includes('state.inRoom = true')) {
  fail('joinRoom must not mark the user in-room before history_snapshot');
}
const historySnapshotStart = store.indexOf("case 'history_snapshot':");
const agentRosterStart = store.indexOf("case 'agent_roster':");
const historySnapshotBranch = store.slice(historySnapshotStart, agentRosterStart);
if (!historySnapshotBranch.includes('state.inRoom = true')) {
  fail('history_snapshot must mark the user in-room');
}

console.log('LANChat roster constraints OK');
