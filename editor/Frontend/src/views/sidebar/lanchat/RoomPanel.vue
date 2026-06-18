<template>
  <div class="lanchat-panel relative flex flex-col h-full text-gray-100">
    <!-- 未进房：大厅（开房 / 加入） -->
    <div v-if="!s.inRoom" class="flex-1 overflow-y-auto p-4 space-y-4">
      <!-- tab 切换 -->
      <div class="flex gap-2">
        <button
          class="flex-1 py-2 rounded text-sm"
          :class="lobbyTab === 'create' ? 'bg-[#84A65B] text-white' : 'bg-[#3a3a3a]/60'"
          @click="lobbyTab = 'create'"
        >
          创建房间
        </button>
        <button
          class="flex-1 py-2 rounded text-sm"
          :class="lobbyTab === 'join' ? 'bg-[#84A65B] text-white' : 'bg-[#3a3a3a]/60'"
          @click="lobbyTab = 'join'"
        >
          加入房间
        </button>
      </div>

      <!-- 创建房间 -->
      <div v-if="lobbyTab === 'create'" class="space-y-3">
        <div class="grid grid-cols-2 gap-2">
          <button
            class="py-2 rounded text-sm"
            :class="roomMode === 'multi' ? 'bg-[#84A65B] text-white' : 'bg-[#3a3a3a]/60'"
            @click="roomMode = 'multi'"
          >
            多人
          </button>
          <button
            class="py-2 rounded text-sm"
            :class="roomMode === 'single' ? 'bg-[#84A65B] text-white' : 'bg-[#3a3a3a]/60'"
            @click="roomMode = 'single'"
          >
            单人
          </button>
        </div>
        <input v-model="form.room" placeholder="房间号" :class="inputCls" />
        <input v-model="form.password" placeholder="密码（可选）" :class="inputCls" />
        <button class="w-full py-2 rounded bg-[#84A65B] text-white text-sm" @click="onCreate">
          创建并进入
        </button>
      </div>

      <!-- 加入房间 -->
      <div v-else class="space-y-3">
        <input v-model="form.ip" placeholder="房主 IP（如 192.168.1.5）" :class="inputCls" :disabled="isJoining" />
        <input v-model.number="form.port" placeholder="房主端口" :class="inputCls" :disabled="isJoining" />
        <input v-model="form.room" placeholder="房间号" :class="inputCls" :disabled="isJoining" />
        <input v-model="form.password" placeholder="密码（可选）" :class="inputCls" :disabled="isJoining" />
        <input v-model="form.nickname" placeholder="你的昵称" :class="inputCls" :disabled="isJoining" />
        <button
          class="w-full py-2 rounded bg-[#84A65B] text-white text-sm disabled:opacity-50"
          :disabled="isJoining"
          @click="onJoin"
        >
          {{ isJoining ? joinStatusText : '加入' }}
        </button>
        <div v-if="isJoining" class="text-[#B8D58D] text-xs">{{ joinStatusText }}</div>
      </div>

      <div v-if="s.error" class="text-red-400 text-xs">{{ errorText }}</div>
    </div>

    <!-- 已进房：聊天界面 -->
    <div v-else class="flex flex-col h-full">
      <!-- 房间信息条 -->
      <div class="flex items-center justify-between px-3 py-2 bg-[#3a3a3a]/70 text-xs">
        <span>
          房间 <b>{{ s.room }}</b>
          <template v-if="s.role === 'host' && s.mode === 'multi'"> · {{ s.ip }}:{{ s.port }}</template>
        </span>
        <button
          class="px-2 py-0.5 rounded bg-[#84A65B]/80 text-white mr-1"
          title="添加 AI 助手"
          @click="showAddAgent = true"
        >
          ＋助手
        </button>
        <button class="px-2 py-0.5 rounded bg-red-500/80 text-white" @click="onLeave">
          {{ s.role === 'host' ? '关闭房间' : '离开' }}
        </button>
      </div>

      <!-- 重连提示条 -->
      <div
        v-if="s.connection === 'reconnecting'"
        class="px-3 py-1 bg-yellow-500/20 text-yellow-300 text-xs flex items-center gap-2"
      >
        <span class="inline-block w-2 h-2 rounded-full bg-yellow-400 animate-pulse"></span>
        连接已断开
      </div>

      <div
        v-if="currentDisclosure"
        class="px-3 py-2 border-b border-gray-700 bg-[#242424] text-xs"
      >
        <div class="flex items-center justify-between gap-2">
          <div class="min-w-0">
            <div class="text-[#B8D58D] font-medium truncate">{{ currentDisclosure.stage || '协作状态' }}</div>
            <div class="text-gray-300 leading-snug mt-0.5">{{ currentDisclosure.public_message }}</div>
            <div v-if="resourceDiagnosisText" class="text-gray-400 leading-snug mt-1">
              {{ resourceDiagnosisText }}
            </div>
          </div>
          <div class="shrink-0 text-gray-300 tabular-nums">{{ currentDisclosure.progress }}%</div>
        </div>
        <div class="mt-2 h-1.5 rounded bg-[#3a3a3a] overflow-hidden">
          <div
            class="h-full bg-[#84A65B]"
            :style="{ width: `${currentDisclosure.progress}%` }"
          ></div>
        </div>
        <div v-if="currentDisclosure.available_actions.length" class="mt-2 flex flex-wrap gap-1">
          <template
            v-for="action in currentDisclosure.available_actions"
            :key="action"
          >
            <button
              v-if="isDisclosureActionSendable(action)"
              class="px-2 py-0.5 rounded bg-[#3a3a3a] text-gray-200 hover:bg-[#84A65B]/70"
              @click="sendDisclosureAction(action)"
            >
              {{ disclosureActionLabel(action) }}
            </button>
            <span
              v-else
              class="px-2 py-0.5 rounded bg-[#3a3a3a] text-gray-200"
            >
              {{ disclosureActionLabel(action) }}
            </span>
          </template>
        </div>
        <div
          v-if="currentDisclosure.requires_confirmation && currentDisclosure.proposal_id && !lanchat.isProposalHandled(currentDisclosure.proposal_id) && s.role === 'host'"
          class="mt-2 flex gap-1"
        >
          <button
            class="px-2 py-0.5 rounded bg-[#84A65B] text-white text-[11px]"
            @click="sendGmDecision(currentDisclosure.proposal_id, 'confirm')"
          >
            确认
          </button>
          <button
            class="px-2 py-0.5 rounded bg-[#3a3a3a] text-gray-100 text-[11px]"
            @click="sendGmDecision(currentDisclosure.proposal_id, 'reject')"
          >
            拒绝
          </button>
        </div>
      </div>

      <div class="flex flex-1 min-h-0">
        <!-- 消息区 -->
        <div class="flex-1 flex flex-col min-h-0">
          <div ref="msgRef" class="flex-1 overflow-y-auto p-3 space-y-2">
            <div
              v-for="(m, idx) in s.messages"
              :key="idx"
              class="flex flex-col"
              :class="m.self ? 'items-end' : 'items-start'"
            >
              <span class="text-[10px] text-gray-400">{{ m.from }}</span>
              <div
                class="px-3 py-1.5 rounded-lg text-sm max-w-[80%] break-words"
                :class="m.self ? 'bg-[#84A65B] text-white' : 'bg-[#E8E8E8]/90 text-gray-800'"
              >
                {{ m.text }}
              </div>
              <div
                v-if="isGmProposalActionable(m) && s.role === 'host'"
                class="mt-1 flex gap-1"
              >
                <button
                  class="px-2 py-0.5 rounded bg-[#84A65B] text-white text-[11px]"
                  @click="sendGmDecision(gmProposalId(m), 'confirm')"
                >
                  确认
                </button>
                <button
                  class="px-2 py-0.5 rounded bg-[#3a3a3a] text-gray-100 text-[11px]"
                  @click="sendGmDecision(gmProposalId(m), 'reject')"
                >
                  拒绝
                </button>
              </div>
            </div>
          </div>

          <!-- 输入区 -->
          <div class="p-2 border-t border-gray-600 flex gap-2">
            <div class="relative flex-1">
              <input
                ref="draftInput"
                v-model="draft"
                :class="inputCls"
                :disabled="s.connection === 'reconnecting'"
                :placeholder="s.connection === 'reconnecting' ? '连接已断开' : '输入消息，回车发送'"
                @input="onDraftInput"
                @keydown="onDraftKeydown"
              />
              <div
                v-if="mentionCandidates.length"
                class="absolute bottom-full left-0 mb-1 w-full bg-[#2a2a2a] border border-gray-600 rounded max-h-32 overflow-y-auto z-10"
              >
                <div
                  v-for="(c, i) in mentionCandidates"
                  :key="i"
                  class="px-2 py-1 text-sm text-gray-200 cursor-pointer"
                  :class="i === mentionActiveIndex ? 'bg-[#84A65B]/60 text-white' : 'hover:bg-[#84A65B]/40'"
                  @mousedown.prevent
                  @click="pickMention(c)"
                >
                  {{ c.isGM ? '🎲 ' : (c.isAgent ? '🤖 ' : '') }}{{ c.name }}<span v-if="c.hint" class="text-[10px] text-gray-400 ml-1">{{ c.hint }}</span>
                </div>
              </div>
            </div>
            <button
              class="px-4 rounded bg-[#84A65B] text-white text-sm disabled:opacity-50"
              :disabled="s.connection === 'reconnecting'"
              @click="onSend"
            >
              发送
            </button>
          </div>
        </div>

        <!-- 成员区 -->
        <div class="w-28 border-l border-gray-600 py-2 overflow-y-auto">
        <MemberList
          :members="s.members"
          :agents="s.agents"
          :peer-id="s.peerId"
          @remove-agent="onRemoveAgent"
        />
        </div>
      </div>

      <div v-if="s.error" class="text-red-400 text-xs px-3 py-1">{{ errorText }}</div>

      <!-- 添加 AI 助手弹窗 -->
      <div
        v-if="showAddAgent"
        class="absolute inset-0 bg-black/50 flex items-center justify-center z-10"
        @click.self="showAddAgent = false"
      >
	        <div class="bg-[#2a2a2a] p-4 rounded w-72 space-y-3">
	          <div class="text-sm text-gray-200">添加 AI 助手</div>
	          <div class="space-y-2">
	            <div class="text-[11px] text-gray-400">快速模板</div>
		            <div class="grid grid-cols-3 gap-1.5">
		              <button
		                v-for="role in roleTemplates"
		                :key="role.key"
	                class="px-2 py-1 rounded bg-[#3a3a3a] text-xs text-gray-200 hover:bg-[#84A65B]/70"
	                :title="role.hint"
	                @click="selectRoleTemplate(role)"
	              >
		                {{ role.name }}
		              </button>
		            </div>
		            <div class="flex gap-1.5 pt-1">
		              <button
		                v-for="bundle in roleTemplateBundles"
		                :key="bundle.key"
		                class="flex-1 px-2 py-1 rounded bg-[#42543b] text-xs text-gray-100 hover:bg-[#84A65B]/80"
		                :title="bundle.hint"
		                @click="addRoleTemplateBundle(bundle)"
		              >
		                {{ bundle.name }}
		              </button>
		            </div>
		          </div>
	          <input v-model="agentForm.name" placeholder="助手名字（如 小策）" :class="inputCls" />
	          <textarea
	            v-model="agentForm.persona"
	            placeholder="人设提示词（可选，也可直接写自定义角色）"
	            rows="3"
	            :class="inputCls"
	          ></textarea>
          <div class="flex gap-2">
            <button class="flex-1 py-1.5 rounded bg-[#3a3a3a] text-gray-200 text-sm" @click="showAddAgent = false">取消</button>
            <button class="flex-1 py-1.5 rounded bg-[#84A65B] text-white text-sm" @click="onAddAgent">添加</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, computed, nextTick, watch } from 'vue';
import lanchat from '../../../stores/lanchat.js';
import {
  buildGmDecisionMessage,
  buildGmDisclosureActionMessage,
  buildManualGmMessageOptions,
  buildParticipantDisclosureDraft,
} from '../../../stores/lanchatDisclosure.js';
import MemberList from './MemberList.vue';

const s = lanchat.state;
const lobbyTab = ref('create');
const roomMode = ref('multi');
const draft = ref('');
const showAddAgent = ref(false);
const agentForm = reactive({ name: '', persona: '' });
const mentionCandidates = ref([]);
const mentionActiveIndex = ref(0);
const msgRef = ref(null);
const draftInput = ref(null);

const roleTemplates = [
  {
    key: 'elder',
    name: '长者',
    persona: '长者',
    hint: '沉稳、传统、实用、安全、秩序感',
  },
  {
    key: 'little_girl',
    name: '小女孩',
    persona: '小女孩',
    hint: '明亮、可爱、装饰性强、童趣、柔和颜色',
  },
  {
    key: 'bandit',
    name: '山贼',
    persona: '山贼',
    hint: '粗犷、木质、营地感、防御性、战利品',
  },
  {
    key: 'scholar',
    name: '学者',
    persona: '学者',
    hint: '书籍、秩序、研究工具、安静区域',
  },
  {
    key: 'merchant',
    name: '商人',
    persona: '商人',
    hint: '摊位、货物、展示、交易动线',
  },
];

const roleTemplateBundles = [
  {
    key: 'night_market_validation',
    name: '夜市验证组',
    hint: '一键添加长者、商人、小女孩、山贼，适合今晚多人/多 Agent 验证',
    roles: ['elder', 'merchant', 'little_girl', 'bandit'],
  },
];

const form = reactive({
  room: '',
  password: '',
  ip: '',
  port: 27960,
  nickname: '',
});

const inputCls =
  'w-full px-3 py-2 rounded bg-[#2a2a2a] border border-gray-600 text-sm text-gray-100 outline-none focus:border-[#84A65B]';

const ERROR_TEXT = {
  WRONG_PASSWORD: '密码错误',
  ROOM_NOT_FOUND: '房间不存在',
  ROOM_FULL: '房间已满',
  NAME_TAKEN: '昵称已被占用',
  ROOM_CLOSED: '房间已关闭',
  START_FAILED: '开房失败',
  JOIN_FAILED: '加入失败',
  HOST_UNREACHABLE: '无法连接到房主',
  ROOM_MISMATCH: '房间号不匹配',
  JOIN_TIMEOUT: '加入超时',
  CONNECTING: '连接尚未完成',
  SYNCING: '正在同步房间',
};
const errorText = computed(() => ERROR_TEXT[s.error] || s.error || '');
const isJoining = computed(() => lanchat.isJoining());
const joinStatusText = computed(() => (s.connection === 'syncing' ? '正在同步房间…' : '正在连接房主…'));
const currentDisclosure = computed(() => {
  const items = s.disclosures || [];
  if (!items.length) return null;
  if (s.role === 'host') {
    const pending = [...items].reverse().find((item) => (
      item.requires_confirmation &&
      item.proposal_id &&
      !lanchat.isProposalHandled(item.proposal_id)
    ));
    if (pending) return pending;
  }
  return items[items.length - 1];
});
const resourceDiagnosisText = computed(() => {
  if (!currentDisclosure.value || currentDisclosure.value.stage !== '资源调度') return '';
  return resourceDiagnosisLabel(currentDisclosure.value.metadata?.diagnosis);
});

async function onCreate() {
  if (!form.room.trim()) return;
  await lanchat.openRoom({
    room: form.room.trim(),
    password: form.password,
    port: form.port || 27960,
    mode: roomMode.value,
  });
}

async function onJoin() {
  if (!form.ip.trim() || !form.room.trim()) return;
  await lanchat.joinRoom({
    ip: form.ip.trim(),
    port: form.port || 27960,
    room: form.room.trim(),
    password: form.password,
    nickname: form.nickname.trim() || '用户',
  });
}

async function onLeave() {
  if (s.role === 'host') {
    await lanchat.closeRoom();
  } else {
    await lanchat.leaveRoom();
  }
}

function onSend() {
  const text = draft.value;
  if (!text.trim()) return;
  draft.value = '';
  mentionCandidates.value = [];
  mentionActiveIndex.value = 0;
  lanchat.sendMessage(text, messageOptionsForText(text)).catch((error) => {
    console.warn('[LANChat] send message failed', error);
  });
}

function gmProposalId(message) {
  if (message?.correlation_id && message?.message_kind === 'gm_proposal') {
    return String(message.correlation_id);
  }
  const text = String(message?.text || '');
  if (!text.includes('GM 提案')) return '';
  const match = text.match(/\bgm-\d+\b/i);
  return match ? match[0] : '';
}

function isGmProposalActionable(message) {
  const proposalId = gmProposalId(message);
  return Boolean(proposalId && !lanchat.isProposalHandled(proposalId));
}

async function sendGmDecision(proposalId, decision) {
  const message = buildGmDecisionMessage(proposalId, decision);
  if (!message) return;
  await lanchat.sendMessage(message.text, message.options);
  lanchat.markProposalHandled(proposalId);
  lanchat.dismissDisclosureByProposal(proposalId);
}

function isDisclosureActionSendable(action) {
  return Boolean(
    buildGmDisclosureActionMessage(action) ||
    buildParticipantDisclosureDraft(action, currentDisclosure.value)
  );
}

async function sendDisclosureAction(action) {
  const message = buildGmDisclosureActionMessage(action);
  if (message) {
    await lanchat.sendMessage(message.text, message.options);
    return;
  }
  const draftText = buildParticipantDisclosureDraft(action, currentDisclosure.value);
  if (!draftText) return;
  draft.value = draftText;
  mentionCandidates.value = [];
  mentionActiveIndex.value = 0;
  await nextTick();
  draftInput.value?.focus?.();
}

async function onAddAgent() {
  if (!agentForm.name.trim()) return;
  await lanchat.addAgent({ name: agentForm.name.trim(), persona: agentForm.persona });
  agentForm.name = '';
  agentForm.persona = '';
  showAddAgent.value = false;
}

function selectRoleTemplate(role) {
  agentForm.name = role.name;
  agentForm.persona = role.persona;
}

async function addRoleTemplateBundle(bundle) {
  const keys = Array.isArray(bundle?.roles) ? bundle.roles : [];
  for (const key of keys) {
    const role = roleTemplates.find((item) => item.key === key);
    if (!role) continue;
    await lanchat.addAgent({ name: role.name, persona: role.persona });
  }
  agentForm.name = '';
  agentForm.persona = '';
  showAddAgent.value = false;
}

async function onRemoveAgent(agentId) {
  await lanchat.removeAgent(agentId);
}

function onDraftInput() {
  const text = draft.value;
  const at = text.lastIndexOf('@');
  if (at === -1) {
    mentionCandidates.value = [];
    mentionActiveIndex.value = 0;
    return;
  }
  const prefix = text.slice(at + 1);
  if (prefix.includes(' ')) {
    mentionCandidates.value = [];
    mentionActiveIndex.value = 0;
    return;
  }
  const members = (s.memberDetails.length
    ? s.memberDetails
        .filter((member) => member.member_id !== s.peerId)
        .map((member) => ({ name: member.nickname, isAgent: false }))
    : s.members
        .filter((name) => name !== s.nickname)
        .map((name) => ({ name, isAgent: false })));
  const gm = [{ name: 'GM', isAgent: true, isGM: true, hint: '主持 / 仲裁' }];
  const agents = s.agents
    .filter((a) => String(a.name || '').toLowerCase() !== 'gm')
    .map((a) => ({ name: a.name, isAgent: true }));
  mentionCandidates.value = [...gm, ...members, ...agents].filter((c) =>
    c.name.toLowerCase().startsWith(prefix.toLowerCase())
  );
  if (mentionCandidates.value.length) {
    mentionActiveIndex.value = Math.min(mentionActiveIndex.value, mentionCandidates.value.length - 1);
  } else {
    mentionActiveIndex.value = 0;
  }
}

function pickMention(c) {
  const text = draft.value;
  const at = text.lastIndexOf('@');
  draft.value = text.slice(0, at) + '@' + c.name + ' ';
  mentionCandidates.value = [];
  mentionActiveIndex.value = 0;
}

function messageOptionsForText(text) {
  const trimmed = String(text || '').trim();
  if (/^@GM(?:\s|$)/i.test(trimmed)) {
    return buildManualGmMessageOptions(s.role);
  }
  return {};
}

function disclosureActionLabel(action) {
  return {
    confirm_plan: '确认方案',
    request_clarification: '继续澄清',
    pause_discussion: '暂停讨论',
    pause_after_batch: '批次后暂停',
    add_intervention: '补充介入',
    request_review: '请求审查',
    approve_final: '确认结果',
    request_repair: '要求修复',
    continue_generation: '继续生成',
    add_note: '补充想法',
    request_add: '请求新增',
    request_modify: '请求调整',
    report_issue: '报告问题',
    propose_seed_plan: '整理方案',
    resolve_conflict: '仲裁冲突',
    control_pace: '控制节奏',
    execute_constraints: '执行约束',
    report_blocker: '报告阻塞',
    confirm_conflict_resolution: '确认仲裁',
    reject_conflict_resolution: '拒绝仲裁',
  }[action] || '查看状态';
}

function resourceDiagnosisLabel(diagnosis) {
  if (!diagnosis || typeof diagnosis !== 'object') return '';
  const state = String(diagnosis.state || '');
  const reasons = Array.isArray(diagnosis.reasons)
    ? diagnosis.reasons.map((item) => String(item))
    : [];
  if (state === 'stopped' || reasons.includes('scheduler_stopped')) {
    return '资源状态：生成已停止，需要重新开始后续生成。';
  }
  if (state === 'paused' || reasons.includes('paused_sessions')) {
    return '资源状态：已暂停，等待房主继续或取消。';
  }
  if (state === 'saturated' || reasons.includes('queue_at_capacity') || reasons.includes('recent_queue_full')) {
    return '资源状态：队列拥堵，系统会先处理已排队任务。';
  }
  if (state === 'strained' || reasons.includes('queue_near_capacity') || reasons.includes('import_stage_busy')) {
    return '资源状态：负载较高，建议先等待当前批次完成。';
  }
  if (state === 'active') {
    return '资源状态：正在处理生成任务。';
  }
  return '';
}

function onDraftKeydown(e) {
  if (mentionCandidates.value.length) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      mentionActiveIndex.value = (mentionActiveIndex.value + 1) % mentionCandidates.value.length;
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      mentionActiveIndex.value =
        (mentionActiveIndex.value - 1 + mentionCandidates.value.length) % mentionCandidates.value.length;
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      pickMention(mentionCandidates.value[mentionActiveIndex.value] || mentionCandidates.value[0]);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      mentionCandidates.value = [];
      mentionActiveIndex.value = 0;
      return;
    }
  }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    onSend();
  }
}

// 新消息自动滚到底
watch(
  () => s.messages.length,
  async () => {
    await nextTick();
    if (msgRef.value) msgRef.value.scrollTop = msgRef.value.scrollHeight;
  }
);
</script>
