<template>
  <div class="flex-1 min-h-0 w-full rounded-lg overflow-hidden relative bg-[#282828]/90 flex flex-col text-white font-sans">
    <DockTitleBar
      v-if="!isDocked"
      title="网络协作"
      extraClass="bg-[#4a9eff]"
      routePath="/Network"
      @close="closeFloat"
    />

    <div class="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4 text-xs">
      <!-- ═══ 会话控制 ═══ -->
      <div class="space-y-3">
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">实例名称</label>
          <input
            v-model="instanceName"
            type="text"
            maxlength="31"
            placeholder="输入名称..."
            class="bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-white focus:border-[#4a9eff] focus:outline-none"
          />
        </div>

        <div class="flex flex-col gap-1">
          <label class="text-gray-400">端口 (UDP)</label>
          <input
            v-model.number="port"
            type="number"
            min="1024"
            max="65535"
            class="bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-white w-24 focus:border-[#4a9eff] focus:outline-none"
          />
        </div>

        <div class="flex gap-2">
          <button
            v-if="!sessionActive"
            @click="startHostSession"
            class="px-4 py-1.5 bg-[#4a9eff] hover:bg-[#3a8eef] rounded text-white font-medium transition-colors"
          >
            创建房间
          </button>
          <button
            v-else
            @click="stopSession"
            class="px-4 py-1.5 bg-red-600 hover:bg-red-500 rounded text-white font-medium transition-colors"
          >
            停止会话
          </button>
        </div>

        <div v-if="sessionActive" class="flex items-center gap-2 text-green-400">
          <span class="w-2 h-2 rounded-full bg-green-400 animate-pulse"></span>
          会话运行中 — {{ roleLabel }} — 端口 {{ port }}
        </div>
        <div v-if="sessionActive && sessionRole === 'client' && hostAddress" class="text-gray-400">
          房主：{{ hostAddress }}:{{ hostPort }}
        </div>
        <div v-if="errorMsg" class="text-red-400">{{ errorMsg }}</div>
      </div>

      <!-- ═══ 手动连接 ═══ -->
      <div class="border-t border-gray-700 pt-4 space-y-3">
        <span class="text-gray-400">手动连接</span>
        <div class="flex flex-col gap-1">
          <label class="text-gray-500">IP 地址</label>
          <input
            v-model="remoteIp"
            type="text"
            placeholder="192.168.1.100"
            class="bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-white focus:border-[#4a9eff] focus:outline-none"
          />
        </div>
        <div class="flex gap-2">
          <div class="flex flex-col gap-1 flex-1">
            <label class="text-gray-500">端口</label>
            <input
              v-model.number="remotePort"
              type="number"
              min="1024"
              max="65535"
              class="bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-white w-24 focus:border-[#4a9eff] focus:outline-none"
            />
          </div>
          <div class="flex flex-col gap-1 flex-1">
            <label class="text-gray-500">对方名称</label>
            <input
              v-model="remotePeerName"
              type="text"
              placeholder="可选"
              class="bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-white focus:border-[#4a9eff] focus:outline-none"
            />
          </div>
        </div>
        <button
          @click="doConnectToPeer"
          :disabled="!remoteIp.trim() || connectStatus === 'connecting'"
          class="px-4 py-1.5 bg-[#84A65B] hover:bg-[#6f8d4a] rounded text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          加入房间
        </button>
        <div v-if="connectStatus === 'connecting'" class="text-yellow-400 text-xs">正在连接...</div>
        <div v-else-if="connectStatus === 'success'" class="text-green-400 text-xs">连接请求已发送</div>
        <div v-else-if="connectStatus" class="text-red-400 text-xs">{{ connectStatus }}</div>
      </div>

      <!-- ═══ Peer 列表 ═══ -->
      <div class="border-t border-gray-700 pt-4">
        <div class="flex items-center justify-between mb-2">
          <span class="text-gray-400">在线用户</span>
          <span class="text-gray-500 tabular-nums">{{ peers.length }}</span>
        </div>

        <div v-if="peers.length === 0" class="text-gray-500 italic">
          {{ sessionActive ? '等待其他用户加入...' : '创建房间或输入房主 IP 加入' }}
        </div>

        <div v-else class="space-y-1">
          <div
            v-for="peer in peers"
            :key="peer.name"
            class="flex items-center gap-2 px-2 py-1 bg-[#1e1e1e] rounded"
          >
            <span class="w-2 h-2 rounded-full bg-green-400"></span>
            <span class="text-gray-300 truncate">{{ peer.name }}</span>
            <span class="text-gray-600 text-[10px] ml-auto">{{ peer.id }}</span>
          </div>
        </div>
      </div>

      <!-- ═══ 文件同步状态 ═══ -->
      <div v-if="fileStatus" class="border-t border-gray-700 pt-3">
        <div v-if="fileStatus.type === 'transferring'" class="text-yellow-400 text-xs">
          正在接收文件: {{ fileStatus.path }} ({{ Math.round(fileStatus.progress * 100) }}%)
        </div>
        <div v-else-if="fileStatus.type === 'success'" class="text-green-400 text-xs">
          文件同步完成: {{ fileStatus.path }}
        </div>
        <div v-else-if="fileStatus.type === 'error'" class="text-red-400 text-xs">
          文件同步失败: {{ fileStatus.path }}
        </div>
      </div>

      <!-- ═══ 远程 Actor 日志 ═══ -->
      <div v-if="remoteActorLog" class="border-t border-gray-700 pt-3 text-green-400 text-xs">
        {{ remoteActorLog }}
      </div>

      <!-- ═══ 说明 ═══ -->
      <div class="border-t border-gray-700 pt-3 text-gray-500 leading-relaxed">
        <p class="mb-1 font-medium text-gray-400">使用说明</p>
        <ul class="list-disc list-inside space-y-1">
          <li>房主点击"创建房间"，客户端输入房主 IP 后点击"加入房间"</li>
          <li>两端端口需要一致，默认使用 27960/UDP</li>
          <li>同时编辑同一物体时，最后写入者胜出 (LWW)</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';
import { Bridge, networkService } from '@/utils/bridge';
import { useDockStore } from '@/stores/dockStore';
import { coronaEventBus } from '@/utils/eventBus';

const dock = useDockStore();
const isDocked = ref(true);
const instanceName = ref('');
const port = ref(27960);
const sessionActive = ref(false);
const sessionRole = ref('none');
const hostAddress = ref('');
const hostPort = ref(0);
const errorMsg = ref('');
const peers = ref([]);

const remoteIp = ref('');
const remotePort = ref(27960);
const remotePeerName = ref('');
const connectStatus = ref(''); // '' | 'connecting' | 'success' | error
const fileStatus = ref(null); // null | { type: 'transferring'|'success'|'error', path, progress? }
const remoteActorLog = ref(''); // latest remote actor creation log

let pollTimer = null;
const ownershipClaimTimes = new Map();

const roleLabel = computed(() => {
  if (sessionRole.value === 'host') return '房主';
  if (sessionRole.value === 'client') return '客户端';
  return '未加入';
});

function applySessionInfo(info) {
  if (!info) return;
  sessionActive.value = Boolean(info.active ?? sessionActive.value);
  sessionRole.value = info.role || sessionRole.value || 'none';
  hostAddress.value = info.host_address || '';
  hostPort.value = info.host_port || 0;
}

async function ensureProjectRoot() {
  try {
    const mod = await import('@/utils/bridge');
    const raw = await mod.projectSettingsService.getActiveProjectInfo();
    const info = raw?.data || raw || {};
    const projPath = info?.project_path || '';
    if (projPath) {
      await networkService.setProjectRoot(projPath);
    }
  } catch (_) {
    /* best effort */
  }
}

async function startSessionAsRole(role) {
  errorMsg.value = '';
  try {
    await ensureProjectRoot();
    const res = await networkService.startSession(instanceName.value, 0, port.value, role);
    if (res && res.ok) {
      applySessionInfo(res);
      startPolling();
      return true;
    } else {
      errorMsg.value = (res && res.error) || '启动失败';
      return false;
    }
  } catch (e) {
    errorMsg.value = e.message;
    return false;
  }
}

async function startHostSession() {
  return startSessionAsRole('host');
}

async function stopSession() {
  errorMsg.value = '';
  try {
    await networkService.stopSession();
    sessionActive.value = false;
    sessionRole.value = 'none';
    hostAddress.value = '';
    hostPort.value = 0;
    peers.value = [];
    stopPolling();
  } catch (e) {
    errorMsg.value = e.message;
  }
}

async function pollPeers() {
  try {
    const res = await networkService.getPeerCount();
    applySessionInfo(res);
    if (res && res.peer_count !== undefined) {
      const count = res.peer_count;
      if (peers.value.length < count) {
        while (peers.value.length < count) {
          peers.value.push({
            name: `Peer ${peers.value.length + 1}`,
            id: '...',
          });
        }
      } else while (peers.value.length > count) {
        peers.value.pop();
      }
    }

    // Poll for pending remote actor creation (file transfer completed)
    try {
      const pending = await networkService.pollPendingActorCreate();
      if (pending && pending.has_pending) {
        // Pause sync, create actor, then resume
        await networkService.setSyncPaused(true);
        try {
          pending.actor_data = pending.actor_data || {};
          pending.actor_data.actor_guid = pending.actor_guid || '';
          pending.actor_data._suppress_network_broadcast = true;
          // Call Python SceneTools.create_actor_internal
          const created = await Bridge.callCEF('SceneTools', 'create_actor_internal',
            [pending.scene_name, pending.model_path, 'model', pending.actor_data]
          );
          const createdData = unwrapCefResult(created);
          await registerActorIdentityFromData(createdData?.actor || createdData, false);
        } finally {
          await networkService.setSyncPaused(false);
        }
      }
    } catch (_) { /* best effort — actor creation polling is secondary */ }
  } catch (e) {
    // ignore polling errors
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollPeers, 2000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function doConnectToPeer() {
  connectStatus.value = 'connecting';
  try {
    if (!sessionActive.value) {
      const started = await startSessionAsRole('client');
      if (!started) {
        connectStatus.value = errorMsg.value || '本地会话启动失败';
        return;
      }
    }
    const peerName = remotePeerName.value || remoteIp.value;
    const res = await networkService.connectToPeer(remoteIp.value, remotePort.value, peerName);
    if (res && res.ok) {
      applySessionInfo(res);
      connectStatus.value = 'success';
      setTimeout(() => { connectStatus.value = ''; }, 3000);
    } else {
      connectStatus.value = (res && res.error) || '连接失败';
    }
  } catch (e) {
    connectStatus.value = e.message;
  }
}

function hashString(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + ch;
    hash |= 0;
  }
  return hash >>> 0;
}

function closeFloat() {
  // handled by DockLayout
}

function unwrapCefResult(res) {
  return res && res.data !== undefined ? res.data : res;
}

async function registerActorIdentityFromData(actorData, locallyOwned = true) {
  if (!sessionActive.value || !actorData) return;
  const actorGuid = actorData.actor_guid || '';
  const actorHandle = actorData.handle || '';
  if (!actorGuid || !actorHandle) return;
  try {
    await networkService.registerActorIdentity(actorGuid, actorHandle, locallyOwned);
  } catch (_) {
    /* best effort — identity mapping is an optimization anchor */
  }
}

onMounted(() => {
  // Try to auto-fill a default name
  if (!instanceName.value) {
    instanceName.value = 'Editor-' + Math.random().toString(36).slice(2, 8);
  }

  // Listen for actor-sync-broadcast from Python (Actor creation triggered locally,
  // needs to be forwarded to remote peers)
  coronaEventBus.on('actor-sync-broadcast', (actorData) => {
    if (!sessionActive.value) return;
    const modelPath = actorData.path || actorData.model || '';
    if (!modelPath) return;
    // Get scene name from the actor's parent scene if available
    const sceneName = actorData.scene || 'Scene/default.scene';
    const actorGuid = actorData.actor_guid ||
      `actor-${hashString(`${sceneName}|${modelPath}|${actorData.name || ''}`)}`;
    actorData.actor_guid = actorGuid;
    registerActorIdentityFromData(actorData);
    networkService.broadcastActorCreate(actorGuid, sceneName, modelPath, actorData).catch(() => {});
  });

  coronaEventBus.on('actor-ownership-claim', ({ actor_guid }) => {
    if (!sessionActive.value || !actor_guid) return;
    const now = Date.now();
    const lastClaim = ownershipClaimTimes.get(actor_guid) || 0;
    if (now - lastClaim < 1000) return;
    ownershipClaimTimes.set(actor_guid, now);
    networkService.claimActorOwnership(actor_guid).catch(() => {});
  });

  // Listen for file-sync-status from Python (C++ reports transfer progress)
  coronaEventBus.on('file-sync-status', ({ status, model_path, progress }) => {
    if (status === 'transferring') {
      fileStatus.value = { type: 'transferring', path: model_path, progress };
    } else if (status === 'complete') {
      fileStatus.value = { type: 'success', path: model_path };
      setTimeout(() => { fileStatus.value = null; }, 5000);
    } else if (status === 'error') {
      fileStatus.value = { type: 'error', path: model_path };
      setTimeout(() => { fileStatus.value = null; }, 5000);
    }
  });

  // Listen for import-asset-complete from Python (remote actor created)
  coronaEventBus.on('import-asset-complete', (actorData) => {
    // A remote actor was created (either via file transfer or direct creation).
    // The actor data is available for UI update.
    registerActorIdentityFromData(actorData);
    remoteActorLog.value = `远程 Actor 已创建: ${actorData.name || 'unknown'}`;
    setTimeout(() => { remoteActorLog.value = ''; }, 5000);
  });
});

onUnmounted(() => {
  stopPolling();
  ownershipClaimTimes.clear();
  // Clean up event listeners
  coronaEventBus.off('actor-sync-broadcast');
  coronaEventBus.off('actor-ownership-claim');
  coronaEventBus.off('file-sync-status');
  coronaEventBus.off('import-asset-complete');
});
</script>
