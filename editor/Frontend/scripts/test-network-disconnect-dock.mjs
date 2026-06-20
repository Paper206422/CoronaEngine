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
const assertNotIncludes = (source, needle, message) => {
  if (source.includes(needle)) fail(message);
};

const networkPanel = read('src/views/sidebar/Network.vue');
const roomPanel = read('src/views/sidebar/lanchat/RoomPanel.vue');
const useDockPanel = read('src/composables/useDockPanel.js');
const cefBridge = read('../../src/systems/ui/cef/cef_query_bridge.cpp');
const networkSystem = read('../../src/systems/network/network_system.cpp');
const networkFileTransfer = read('../../include/corona/systems/network/file_transfer.h');
const networkProtocolTests = read('../../src/systems/network/tests/test_network_protocol.cpp');
const legacyLanChat = read('../../editor/plugins/LANChat/main.py');
const actorCore = read('../../editor/CoronaCore/core/entities/actor.py');
const sceneCore = read('../../editor/CoronaCore/core/entities/scene.py');
const actorBroadcastTests = read('../../editor/CoronaCore/tests/test_actor_network_broadcast.py');

assertIncludes(
  networkPanel,
  "import { useDockPanel } from '@/composables/useDockPanel.js'",
  'Network panel must use the shared dock composable'
);
assertIncludes(
  networkPanel,
  'const { closePanel: closeDockPanel, isDocked } = useDockPanel()',
  'Network panel must derive isDocked from DockPanel injection'
);
assertIncludes(
  networkPanel,
  'closeDockPanel();',
  'Network panel close button must close its dock/external panel'
);
assertIncludes(
  networkPanel,
  'extraClass="bg-[#84A65B]"',
  'Network floating titlebar must use the standard dock titlebar color'
);
assertNotIncludes(
  networkPanel,
  'extraClass="bg-[#4a9eff]"',
  'Network floating titlebar must not use the old blue titlebar color'
);
assertNotIncludes(
  networkPanel,
  'const isDocked = ref(true)',
  'Network panel must not hard-code itself as docked'
);
assertNotIncludes(
  networkPanel,
  "import { useDockStore } from '@/stores/dockStore'",
  'Network panel must not bypass the dock composable'
);
assertIncludes(
  networkPanel,
  'const CONNECT_TIMEOUT_MS = 5000',
  'Network panel must define a handshake timeout for manual connections'
);
assertIncludes(
  networkPanel,
  'const connectionAttemptStartedAt = ref(0)',
  'Network panel must track manual connection attempts across polling'
);
assertIncludes(
  networkPanel,
  'const localIp = ref',
  'Network panel must track the current local IP address'
);
assertIncludes(
  networkPanel,
  'localIp.value = info.local_ip',
  'Network panel must consume the backend local_ip field'
);
assertIncludes(
  networkPanel,
  '本机 IP',
  'Network panel must show the current local IP address'
);
assertIncludes(
  networkPanel,
  'const listenPort = Number(info.listen_port || 0)',
  'Network panel must consume the backend listen_port field'
);
assertIncludes(
  networkPanel,
  'port.value = listenPort',
  'Network panel must show the active backend listen_port'
);
assertIncludes(
  networkPanel,
  "connectStatus.value = 'connected'",
  'Network panel must only mark manual connections connected after peer count confirms a handshake'
);
assertIncludes(
  networkPanel,
  "connectStatus.value = '无法连接到房主'",
  'Network panel must surface handshake timeouts as unreachable host errors'
);
assertIncludes(
  networkPanel,
  "connectStatus.value = 'connecting'",
  'Network manual connect must enter a waiting-for-handshake state'
);
assertNotIncludes(
  networkPanel,
  "connectStatus.value = 'success'",
  'Network manual connect must not mark a submitted request as a successful connection'
);
assertIncludes(
  networkPanel,
  '已连接用户数',
  'Network panel must not imply placeholder peer rows contain real identities'
);
assertIncludes(
  cefBridge,
  'payload["local_ip"] = detect_local_ipv4()',
  'Network bridge must expose the current local IPv4 address'
);

assertIncludes(
  roomPanel,
  '连接已断开',
  'RoomPanel must show a disconnected state without promising reconnect'
);
assertNotIncludes(
  roomPanel,
  '正在重连',
  'RoomPanel must not imply automatic reconnect is implemented'
);
assertNotIncludes(
  roomPanel,
  '重连中',
  'RoomPanel input placeholder must not imply automatic reconnect is implemented'
);
assertIncludes(
  legacyLanChat,
  'not a source of truth for current UI port display',
  'Legacy Python LANChat shim must state that C++/CEF owns current port state'
);
assertIncludes(
  actorCore,
  '_local_model_library_resource_subdir(rel_path)',
  'Actor network broadcast must detect project-local model library paths before reuse'
);
assertIncludes(
  actorCore,
  'prefix = "assets/local_model_library/"',
  'Actor network broadcast must treat local_model_library as an unstable source path'
);
assertIncludes(
  actorCore,
  'prefix = "models/"',
  'Actor network broadcast must treat project models paths as unstable network sources'
);
assertIncludes(
  actorCore,
  'target_subdir=local_model_subdir',
  'Actor network broadcast must copy local model library assets to a stable Resource subdir'
);
assertIncludes(
  actorCore,
  'target_subdir=stable_model_subdir',
  'Actor network broadcast must copy project models assets to a stable Resource subdir'
);
assertIncludes(
  actorCore,
  '_collect_gltf_dependencies',
  'Actor network broadcast must collect GLTF external buffer/image dependencies'
);
assertIncludes(
  actorCore,
  '_collect_common_material_dependencies',
  'Actor network broadcast must collect conservative same-directory material assets for non-OBJ formats'
);
assertIncludes(
  actorCore,
  'map_Kd',
  'Actor network broadcast must parse OBJ MTL texture dependencies'
);
assertIncludes(
  sceneCore,
  'actor-delete-sync-broadcast',
  'Scene actor removal must emit a network delete broadcast'
);
assertIncludes(
  sceneCore,
  '_suppress_network_broadcast',
  'Remote actor removal must suppress delete rebroadcast loops'
);
assertIncludes(
  actorBroadcastTests,
  'test_local_model_library_path_is_copied_to_stable_resource_before_broadcast',
  'Actor network broadcast tests must cover local model library path stabilization'
);
assertIncludes(
  actorBroadcastTests,
  'Resource/local_model_library/models/书桌_6db78152/base.glb',
  'Actor network broadcast test must assert the stable Resource path for AI local models'
);
assertIncludes(
  actorBroadcastTests,
  'test_models_path_is_copied_to_resource_with_obj_dependencies_before_broadcast',
  'Actor network broadcast tests must cover project models path stabilization'
);
assertIncludes(
  actorBroadcastTests,
  'Resource/models/矮桌/base.obj',
  'Actor network broadcast test must assert the stable Resource path for project models'
);
assertIncludes(
  actorBroadcastTests,
  'test_gltf_external_dependencies_are_copied_before_broadcast',
  'Actor network broadcast tests must cover GLTF external resource dependencies'
);
assertIncludes(
  actorBroadcastTests,
  'test_fbx_copies_common_same_directory_material_assets',
  'Actor network broadcast tests must cover non-OBJ conservative material dependencies'
);
assertIncludes(
  actorBroadcastTests,
  'test_scene_remove_actor_emits_delete_sync_broadcast',
  'Actor network broadcast tests must cover local actor delete broadcasts'
);

assertIncludes(
  useDockPanel,
  "'/Network': 'Network'",
  'Network standalone route must map back to the Network panel id'
);

assertIncludes(
  networkSystem,
  'stop_session_after_peer_disconnect',
  'NetworkSystem must defer session shutdown from peer disconnect callbacks'
);
assertIncludes(
  networkSystem,
  'notify_lanchat_room_closed',
  'NetworkSystem must centralize LANChat room_closed notifications'
);
assertIncludes(
  networkSystem,
  'clear_lanchat_room_state',
  'NetworkSystem must clear LANChat state when host disconnects'
);
assertIncludes(
  networkSystem,
  'is_connected_host_peer',
  'NetworkSystem must identify host disconnects before stopping client sessions'
);
assertIncludes(
  networkSystem,
  'send_to_connected_host_peer',
  'NetworkSystem clients must send LANChat packets to the connected host peer'
);
assertIncludes(
  networkSystem,
  'is_message_from_connected_host',
  'NetworkSystem clients must validate host authority for inbound LANChat state'
);
assertIncludes(
  networkSystem,
  'Utils::path_to_utf8(*full_path)',
  'NetworkSystem FILE_REQUEST errors must log UTF-8 paths for non-ASCII model names'
);
assertIncludes(
  networkFileTransfer,
  '#include <corona/utils/path_utils.h>',
  'Network file transfer path resolution must use the shared UTF-8 path utilities'
);
assertIncludes(
  networkFileTransfer,
  'Utils::utf8_to_path(relative_path)',
  'Network file transfer must decode wire paths as UTF-8 before filesystem access'
);
assertNotIncludes(
  networkFileTransfer,
  'std::filesystem::path rel(relative_path)',
  'Network file transfer must not construct filesystem paths from UTF-8 wire strings as ANSI'
);
assertIncludes(
  networkProtocolTests,
  'test_project_relative_path_uses_utf8_for_non_ascii_segments',
  'Network protocol tests must cover UTF-8 project-relative file transfer paths'
);
assertIncludes(
  networkProtocolTests,
  'Resource/models/绿植/base.obj',
  'Network protocol tests must use a non-ASCII model path regression case'
);
assertIncludes(
  networkSystem,
  'impl_->stop_session_after_peer_disconnect = true',
  'Host disconnect and host leave paths must request deferred session stop'
);
assertIncludes(
  networkSystem,
  'MessageType::ACTOR_DELETE',
  'NetworkSystem must handle actor delete packets'
);
assertIncludes(
  networkSystem,
  'broadcast_actor_delete',
  'NetworkSystem must expose actor delete broadcasts'
);
assertIncludes(
  networkSystem,
  'pending_actor_deletes',
  'NetworkSystem must queue remote actor deletes for frontend polling'
);
assertIncludes(
  networkPanel,
  'pollPendingActorDelete',
  'Network panel must poll and apply remote actor deletes'
);
assertIncludes(
  networkPanel,
  'actor-delete-sync-broadcast',
  'Network panel must forward local actor delete broadcasts to NetworkSystem'
);
assertIncludes(
  networkPanel,
  'remove_actor_internal',
  'Network panel must apply remote actor deletes through an internal no-rebroadcast path'
);
assertIncludes(
  networkProtocolTests,
  'test_actor_delete_carries_scene_guid_and_name',
  'Network protocol tests must cover actor delete packets'
);

const updateStart = networkSystem.indexOf('void NetworkSystem::update()');
const shutdownStart = networkSystem.indexOf('void NetworkSystem::shutdown()');
const updateBody = networkSystem.slice(updateStart, shutdownStart);
assertIncludes(
  updateBody,
  'impl_->stop_session_after_peer_disconnect',
  'NetworkSystem update must consume deferred stop requests'
);
assertIncludes(
  updateBody,
  'stop_session();',
  'NetworkSystem update must stop the session after peer polling completes'
);

const stopSessionStart = networkSystem.indexOf('void NetworkSystem::stop_session()');
const sessionStateStart = networkSystem.indexOf('NetworkSystem::SessionState NetworkSystem::session_state() const');
const stopSessionBody = networkSystem.slice(stopSessionStart, sessionStateStart);
assertIncludes(
  stopSessionBody,
  'notify_lanchat_room_closed();',
  'stop_session must notify the frontend before clearing an open LANChat room'
);
assertIncludes(
  stopSessionBody,
  'clear_lanchat_room_state();',
  'stop_session must clear LANChat state through the shared helper'
);

const disconnectStart = networkSystem.indexOf('void NetworkSystem::on_peer_disconnected');
const dataReceivedStart = networkSystem.indexOf('void NetworkSystem::on_data_received');
const disconnectBody = networkSystem.slice(disconnectStart, dataReceivedStart);
assertIncludes(
  disconnectBody,
  'is_connected_host_peer(info)',
  'Client disconnect handling must only stop when the host peer disconnects'
);
assertIncludes(
  disconnectBody,
  'notify_lanchat_room_closed();',
  'Client host disconnect must notify LANChat room_closed'
);
assertIncludes(
  disconnectBody,
  'clear_lanchat_room_state();',
  'Client host disconnect must clear LANChat state'
);

const chatLeaveStart = networkSystem.indexOf('} else if (mt == MessageType::CHAT_LEAVE) {');
const memberUpdateStart = networkSystem.indexOf('} else if (mt == MessageType::CHAT_MEMBER_UPDATE) {');
const chatLeaveBranch = networkSystem.slice(chatLeaveStart, memberUpdateStart);
assertIncludes(
  chatLeaveBranch,
  'is_connected_host_peer(*peer_info)',
  'Client receiving CHAT_LEAVE must verify the sender is the connected host'
);
assertIncludes(
  chatLeaveBranch,
  'impl_->stop_session_after_peer_disconnect = true',
  'Client receiving host CHAT_LEAVE must request deferred network session stop'
);
assertIncludes(
  chatLeaveBranch,
  'clear_lanchat_room_state();',
  'Client receiving host CHAT_LEAVE must clear LANChat state'
);

const sendMessageStart = networkSystem.indexOf('Network::LanChatMessageResult NetworkSystem::lanchat_send_message_ex');
const agentReplyStart = networkSystem.indexOf('Network::LanChatMessageResult NetworkSystem::lanchat_send_agent_reply_ex');
const registerAgentStart = networkSystem.indexOf('Network::LanChatResult NetworkSystem::lanchat_register_agent');
const removeAgentStart = networkSystem.indexOf('Network::LanChatResult NetworkSystem::lanchat_remove_agent');
const lockObjectStart = networkSystem.indexOf('Network::LanChatResult NetworkSystem::lanchat_lock_object');
const clientSendBranches = [
  networkSystem.slice(sendMessageStart, agentReplyStart),
  networkSystem.slice(agentReplyStart, registerAgentStart),
  networkSystem.slice(registerAgentStart, removeAgentStart),
  networkSystem.slice(removeAgentStart, lockObjectStart),
];
for (const branch of clientSendBranches) {
  assertIncludes(
    branch,
    'send_to_connected_host_peer(packet)',
    'Client LANChat outbound paths must target the connected host peer'
  );
  assertNotIncludes(
    branch,
    'send_to_first_peer',
    'Client LANChat outbound paths must not use the first ready peer'
  );
}

const memberUpdateBranch = networkSystem.slice(
  memberUpdateStart,
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_HISTORY_SNAPSHOT ||')
);
assertIncludes(
  memberUpdateBranch,
  'if (impl_->session_role == SessionRole::Client && !is_message_from_connected_host(sender_peer_id)) return;',
  'Clients must only accept member snapshots from the connected host'
);
const historySnapshotBranch = networkSystem.slice(
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_HISTORY_SNAPSHOT ||'),
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_MESSAGE ||')
);
assertIncludes(
  historySnapshotBranch,
  'if (impl_->session_role == SessionRole::Client && !is_message_from_connected_host(sender_peer_id)) return;',
  'Clients must only accept history snapshots from the connected host'
);
const messageBranch = networkSystem.slice(
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_MESSAGE ||'),
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_AGENT_REGISTER) {')
);
assertIncludes(
  messageBranch,
  'if (impl_->session_role == SessionRole::Client && !is_message_from_connected_host(sender_peer_id)) return;',
  'Clients must only accept authoritative chat messages from the connected host'
);
const agentRegisterBranch = networkSystem.slice(
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_AGENT_REGISTER) {'),
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_AGENT_REMOVE) {')
);
assertIncludes(
  agentRegisterBranch,
  'if (impl_->session_role == SessionRole::Client && !is_message_from_connected_host(sender_peer_id)) return;',
  'Clients must only accept agent roster updates from the connected host'
);
const agentRemoveBranch = networkSystem.slice(
  networkSystem.indexOf('} else if (mt == MessageType::CHAT_AGENT_REMOVE) {'),
  networkSystem.indexOf('void NetworkSystem::handle_file_request')
);
assertIncludes(
  agentRemoveBranch,
  'if (impl_->session_role == SessionRole::Client && !is_message_from_connected_host(sender_peer_id)) return;',
  'Clients must only accept agent removals from the connected host'
);

console.log('Network disconnect and dock constraints OK');
