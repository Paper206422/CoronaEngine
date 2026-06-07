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
        <input v-model="form.room" placeholder="房间号" :class="inputCls" />
        <input v-model="form.password" placeholder="密码（可选）" :class="inputCls" />
        <button class="w-full py-2 rounded bg-[#84A65B] text-white text-sm" @click="onCreate">
          创建并进入
        </button>
      </div>

      <!-- 加入房间 -->
      <div v-else class="space-y-3">
        <input v-model="form.ip" placeholder="房主 IP（如 192.168.1.5）" :class="inputCls" />
        <input v-model.number="form.port" placeholder="端口（默认 8770）" :class="inputCls" />
        <input v-model="form.room" placeholder="房间号" :class="inputCls" />
        <input v-model="form.password" placeholder="密码（可选）" :class="inputCls" />
        <input v-model="form.nickname" placeholder="你的昵称" :class="inputCls" />
        <button class="w-full py-2 rounded bg-[#84A65B] text-white text-sm" @click="onJoin">
          加入
        </button>
      </div>

      <div v-if="s.error" class="text-red-400 text-xs">{{ errorText }}</div>
    </div>

    <!-- 已进房：聊天界面 -->
    <div v-else class="flex flex-col h-full">
      <!-- 房间信息条 -->
      <div class="flex items-center justify-between px-3 py-2 bg-[#3a3a3a]/70 text-xs">
        <span>
          房间 <b>{{ s.room }}</b>
          <template v-if="s.role === 'host'"> · {{ s.ip }}:{{ s.port }}</template>
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
        连接已断开，正在重连…
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
            </div>
          </div>

          <!-- 输入区 -->
          <div class="p-2 border-t border-gray-600 flex gap-2">
            <div class="relative flex-1">
              <input
                v-model="draft"
                :class="inputCls"
                :disabled="s.connection === 'reconnecting'"
                :placeholder="s.connection === 'reconnecting' ? '重连中…' : '输入消息，回车发送'"
                @input="onDraftInput"
                @keyup.enter="onSend"
              />
              <div
                v-if="mentionCandidates.length"
                class="absolute bottom-full left-0 mb-1 w-full bg-[#2a2a2a] border border-gray-600 rounded max-h-32 overflow-y-auto z-10"
              >
                <div
                  v-for="(c, i) in mentionCandidates"
                  :key="i"
                  class="px-2 py-1 text-sm text-gray-200 hover:bg-[#84A65B]/40 cursor-pointer"
                  @click="pickMention(c)"
                >
                  {{ c.isAgent ? '🤖 ' : '' }}{{ c.name }}
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
          :my-nickname="s.nickname"
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
          <input v-model="agentForm.name" placeholder="助手名字（如 小策）" :class="inputCls" />
          <textarea
            v-model="agentForm.persona"
            placeholder="人设提示词（可选，如：你是资深关卡策划）"
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
import MemberList from './MemberList.vue';

const s = lanchat.state;
const lobbyTab = ref('create');
const draft = ref('');
const showAddAgent = ref(false);
const agentForm = reactive({ name: '', persona: '' });
const mentionCandidates = ref([]);
const msgRef = ref(null);

const form = reactive({
  room: '',
  password: '',
  ip: '',
  port: 8770,
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
};
const errorText = computed(() => ERROR_TEXT[s.error] || s.error || '');

async function onCreate() {
  if (!form.room.trim()) return;
  await lanchat.openRoom({
    room: form.room.trim(),
    password: form.password,
    port: form.port || 8770,
  });
}

async function onJoin() {
  if (!form.ip.trim() || !form.room.trim()) return;
  await lanchat.joinRoom({
    ip: form.ip.trim(),
    port: form.port || 8770,
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

async function onSend() {
  const text = draft.value;
  draft.value = '';
  mentionCandidates.value = [];
  await lanchat.sendMessage(text);
}

async function onAddAgent() {
  if (!agentForm.name.trim()) return;
  await lanchat.addAgent({ name: agentForm.name.trim(), persona: agentForm.persona });
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
    return;
  }
  const prefix = text.slice(at + 1);
  if (prefix.includes(' ')) {
    mentionCandidates.value = [];
    return;
  }
  const members = s.members.map((m) => ({ name: m, isAgent: false }));
  const agents = s.agents.map((a) => ({ name: a.name, isAgent: true }));
  mentionCandidates.value = [...members, ...agents].filter((c) =>
    c.name.toLowerCase().startsWith(prefix.toLowerCase())
  );
}

function pickMention(c) {
  const text = draft.value;
  const at = text.lastIndexOf('@');
  draft.value = text.slice(0, at) + '@' + c.name + ' ';
  mentionCandidates.value = [];
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
