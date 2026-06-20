<template>
  <div class="lanchat-panel relative flex flex-col h-full text-base text-gray-100">
    <!-- 未进房：大厅（开房 / 加入） -->
    <div v-if="!s.inRoom" class="flex-1 overflow-y-auto p-4 space-y-4">
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <div class="text-sm font-medium text-gray-200">历史记录</div>
          <button
            class="px-2 py-1 rounded bg-[#3a3a3a] text-xs text-gray-200 disabled:opacity-50"
            :disabled="s.historyLoading"
            @click="refreshHistoryRooms"
          >
            刷新
          </button>
        </div>
        <div v-if="s.historyError" class="text-red-400 text-xs">{{ s.historyError }}</div>
        <div v-if="s.historyLoading && !s.historyRooms.length" class="text-gray-400 text-sm">
          正在加载历史记录…
        </div>
        <div v-else-if="!s.historyRooms.length" class="text-gray-500 text-sm">
          暂无历史记录
        </div>
        <div v-else class="space-y-1">
          <button
            v-for="room in s.historyRooms"
            :key="room.room_id"
            class="w-full text-left px-3 py-2 rounded bg-[#2a2a2a] border border-gray-700 hover:border-[#84A65B] transition-colors"
            :class="s.selectedHistoryRoom?.room_id === room.room_id ? 'border-[#84A65B]' : ''"
            @click="loadHistoryRoom(room)"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-gray-100 truncate">{{ historyRoomTitle(room) }}</span>
              <span class="text-xs text-gray-500 shrink-0">{{ formatHistoryTime(room.last_ts) }}</span>
            </div>
            <div class="mt-1 text-xs text-gray-400 truncate">
              {{ room.message_count || 0 }} 条 · {{ room.last_sender_name || '未知' }}：{{ room.last_text || '' }}
            </div>
          </button>
        </div>
        <div
          v-if="s.selectedHistoryRoom"
          class="mt-3 border-t border-gray-700 pt-3 space-y-2"
        >
          <div class="flex items-center justify-between">
            <div class="text-sm text-[#B8D58D] truncate">
              {{ historyRoomTitle(s.selectedHistoryRoom) }}
            </div>
            <div class="text-xs text-gray-500">{{ s.messages.length }} 条</div>
          </div>
          <button
            class="w-full py-2 rounded bg-[#84A65B] text-white text-sm disabled:opacity-50"
            :disabled="s.historyLoading"
            @click="continueHistoryAsSingle"
          >
            作为单人聊天室继续
          </button>
          <div class="max-h-56 overflow-y-auto space-y-2 pr-1">
            <div
              v-for="m in s.messages"
              :key="m.message_id || `${m.from}-${m.ts}-${m.text}`"
              class="text-sm"
            >
              <div class="text-xs text-gray-500">{{ m.from }} · {{ formatHistoryTime(m.ts) }}</div>
              <div class="mt-0.5 rounded bg-[#E8E8E8]/90 text-gray-800 px-3 py-2 leading-relaxed break-words">
                {{ m.text }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-3 gap-2">
        <button
          v-for="mode in workspaceModes"
          :key="mode.key"
          class="rounded border px-2 py-2 text-left transition-colors"
          :class="selectedWorkspaceMode === mode.key ? 'border-[#84A65B] bg-[#2f3b2b]' : 'border-gray-700 bg-[#2a2a2a] hover:border-gray-500'"
          @click="selectWorkspaceMode(mode.key)"
        >
          <div class="text-sm font-medium text-gray-100">{{ mode.label }}</div>
          <div class="mt-1 text-[11px] leading-snug text-gray-400">{{ mode.hint }}</div>
        </button>
      </div>

      <div
        v-if="selectedWorkspaceMode === 'solo_multi_agent'"
        class="rounded border border-gray-700 bg-[#242424] p-3 space-y-3"
      >
        <div class="flex items-center justify-between gap-2">
          <div>
            <div class="text-sm font-medium text-gray-100">配置 AI 专家组</div>
            <div class="mt-0.5 text-[12px] text-gray-500">选择要加入本地聊天室的 Agent，也可以添加自定义角色</div>
          </div>
          <div class="text-[12px] text-[#B8D58D]">{{ selectedExpertPayloads.length }} 个</div>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <label
            v-for="role in roleTemplates"
            :key="role.key"
            class="flex items-start gap-2 rounded bg-[#2a2a2a] border border-gray-700 px-2.5 py-2 cursor-pointer hover:border-[#84A65B]"
          >
            <input
              type="checkbox"
              class="mt-1 accent-[#84A65B]"
              :checked="expertGroupConfig.selectedRoleKeys.has(role.key)"
              @change="setExpertRoleSelected(role.key, $event.target.checked)"
            />
            <span class="min-w-0">
              <span class="block text-sm text-gray-100">{{ role.name }}</span>
              <span class="block truncate text-[11px] text-gray-500">{{ role.hint }}</span>
            </span>
          </label>
        </div>
        <div v-if="expertGroupConfig.customExperts.length" class="space-y-1.5">
          <div
            v-for="(expert, index) in expertGroupConfig.customExperts"
            :key="`${expert.name}-${index}`"
            class="flex items-center justify-between gap-2 rounded bg-[#2a2a2a] px-2.5 py-1.5 text-sm"
          >
            <span class="truncate text-gray-200">{{ expert.name }}</span>
            <button
              class="text-red-400 text-xs hover:text-red-300"
              @click="removeCustomExpertAt(index)"
            >
              移除
            </button>
          </div>
        </div>
        <div class="grid grid-cols-[1fr_1.5fr_auto] gap-2">
          <input v-model="customExpertForm.name" placeholder="自定义名字" :class="inputCls" />
          <input v-model="customExpertForm.persona" placeholder="角色职责 / 人设" :class="inputCls" />
          <button
            class="px-3 rounded bg-[#3a3a3a] text-sm text-gray-100 hover:bg-[#84A65B]/80 disabled:opacity-50"
            :disabled="!customExpertForm.name.trim()"
            @click="addCustomExpertFromForm"
          >
            添加
          </button>
        </div>
      </div>

      <!-- tab 切换 -->
      <div v-if="selectedWorkspaceMode === 'multiplayer_multi_agent'" class="flex gap-2">
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
        <template v-if="roomMode === 'multi'">
          <input v-model="form.room" placeholder="房间号" :class="inputCls" />
          <input v-model="form.password" placeholder="密码（可选）" :class="inputCls" />
        </template>
        <button
          class="w-full py-2 rounded bg-[#84A65B] text-white text-sm disabled:opacity-50"
          :disabled="selectedWorkspaceMode === 'solo_multi_agent' && !selectedExpertPayloads.length"
          @click="onCreate"
        >
          {{ createButtonText }}
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
      <div class="flex items-center justify-between gap-3 px-3 py-2.5 bg-[#343434] text-sm">
        <div class="min-w-0">
          <div class="text-[13px] text-gray-400">{{ s.mode === 'single' ? '本地单人协作' : '局域网协作' }}</div>
          <div class="truncate text-base font-semibold text-gray-100">
            {{ s.mode === 'single' ? '单人聊天室' : s.room }}
            <template v-if="s.role === 'host' && s.mode === 'multi'"> · {{ s.ip }}:{{ s.port }}</template>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <span
            class="rounded-full px-2 py-1 text-[12px]"
            :class="s.connection === 'connected' ? 'bg-[#84A65B]/20 text-[#B8D58D]' : 'bg-yellow-500/20 text-yellow-300'"
          >
            {{ roomStatusLabel }}
          </span>
          <button
            class="px-2.5 py-1.5 rounded bg-[#84A65B]/85 text-white text-sm"
            title="添加 AI 助手"
            @click="showAddAgent = true"
          >
            ＋助手
          </button>
          <button class="px-2.5 py-1.5 rounded bg-red-500/80 text-white text-sm" @click="onLeave">
            {{ s.role === 'host' ? '关闭' : '离开' }}
          </button>
        </div>
      </div>

      <!-- 重连提示条 -->
      <div
        v-if="s.connection === 'reconnecting'"
        class="px-3 py-1.5 bg-yellow-500/20 text-yellow-300 text-sm flex items-center gap-2"
      >
        <span class="inline-block w-2 h-2 rounded-full bg-yellow-400 animate-pulse"></span>
        连接已断开
      </div>

      <div
        v-if="currentDisclosure"
        class="px-3 py-3 border-b border-gray-700 bg-[#222722] text-sm"
      >
        <div class="flex items-center justify-between gap-2">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span
                v-if="isWaitingDisclosure"
                class="inline-block h-2.5 w-2.5 rounded-full bg-[#B8D58D] animate-pulse"
              ></span>
              <span class="text-[#B8D58D] font-semibold truncate">{{ currentDisclosure.stage || '协作状态' }}</span>
              <span v-if="disclosureAgeText" class="shrink-0 text-[12px] text-gray-500">{{ disclosureAgeText }}</span>
            </div>
            <div class="text-[15px] text-gray-200 leading-relaxed mt-1">{{ currentDisclosure.public_message }}</div>
            <div v-if="resourceDiagnosisText" class="text-gray-400 leading-relaxed mt-1">
              {{ resourceDiagnosisText }}
            </div>
            <div v-if="waitHintText" class="mt-1.5 text-[13px] text-gray-400">
              {{ waitHintText }}
            </div>
          </div>
          <div class="shrink-0 text-right">
            <div class="text-lg font-semibold text-gray-100 tabular-nums">{{ currentDisclosure.progress }}%</div>
            <div class="text-[11px] text-gray-500">{{ isWaitingDisclosure ? '处理中' : '状态' }}</div>
          </div>
        </div>
        <div class="mt-2.5 h-2 rounded bg-[#3a3a3a] overflow-hidden">
          <div
            class="h-full bg-[#84A65B] transition-all duration-300"
            :style="{ width: `${currentDisclosure.progress}%` }"
          ></div>
        </div>
        <div v-if="waitSteps.length" class="mt-2.5 grid grid-cols-5 gap-1">
          <div
            v-for="step in waitSteps"
            :key="step.key"
            class="h-1.5 rounded-full"
            :class="step.active ? 'bg-[#84A65B]' : (step.done ? 'bg-[#84A65B]/45' : 'bg-[#3a3a3a]')"
            :title="step.label"
          ></div>
        </div>
        <div v-if="currentDisclosure.available_actions.length" class="mt-2.5 flex flex-wrap gap-1.5">
          <template
            v-for="action in currentDisclosure.available_actions"
            :key="action"
          >
            <button
              v-if="isDisclosureActionSendable(action)"
              class="px-2.5 py-1 rounded bg-[#3a3a3a] text-gray-200 hover:bg-[#84A65B]/70"
              @click="sendDisclosureAction(action)"
            >
              {{ disclosureActionLabel(action) }}
            </button>
            <span
              v-else
              class="px-2.5 py-1 rounded bg-[#3a3a3a] text-gray-200"
            >
              {{ disclosureActionLabel(action) }}
            </span>
          </template>
        </div>
        <div
          v-if="currentDisclosure.requires_confirmation && currentDisclosure.proposal_id && !lanchat.isProposalHandled(currentDisclosure.proposal_id) && s.role === 'host'"
          class="mt-2.5 flex gap-2"
        >
          <button
            class="px-3 py-1.5 rounded bg-[#84A65B] text-white text-sm"
            @click="sendGmDecision(currentDisclosure.proposal_id, 'confirm')"
          >
            确认
          </button>
          <button
            class="px-3 py-1.5 rounded bg-[#3a3a3a] text-gray-100 text-sm"
            @click="sendGmDecision(currentDisclosure.proposal_id, 'reject')"
          >
            拒绝
          </button>
        </div>
      </div>

      <div
        v-if="s.role === 'host'"
        class="px-3 py-2 border-b border-gray-700 bg-[#202020] text-sm flex items-center justify-between gap-2"
      >
        <label class="flex items-center gap-2 text-gray-300 cursor-pointer select-none">
          <input
            type="checkbox"
            class="accent-[#84A65B]"
            :checked="s.generationOptions.vlmEnabled"
            @change="onVlmToggle"
          />
          <span>VLM 外观检查</span>
        </label>
        <span class="text-gray-500">{{ s.generationOptions.vlmEnabled ? '审查 1 个关键目标' : '关闭' }}</span>
      </div>

      <div class="flex flex-1 min-h-0">
        <!-- 消息区 -->
        <div class="flex-1 flex flex-col min-h-0">
          <div ref="msgRef" class="flex-1 overflow-y-auto p-4 space-y-3.5">
            <div
              v-for="(m, idx) in s.messages"
              :key="idx"
              class="flex flex-col"
              :class="m.self ? 'items-end' : 'items-start'"
            >
              <span class="text-[12px] text-gray-400 mb-1">{{ m.from }}</span>
              <div
                class="px-3.5 py-2.5 rounded-lg text-base leading-relaxed max-w-[88%] whitespace-pre-wrap break-words"
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
            <div
              v-if="showAiReplySpinner"
              class="flex flex-col items-start"
            >
              <span class="text-[12px] text-gray-400 mb-1">{{ pendingReplyTarget }}</span>
              <div class="max-w-[88%] rounded-lg bg-[#E8E8E8]/90 px-3.5 py-2.5 text-gray-800 shadow-sm">
                <div class="flex items-center gap-2 text-[15px] leading-relaxed">
                  <span class="inline-block h-4 w-4 rounded-full border-2 border-gray-400 border-t-[#84A65B] animate-spin"></span>
                  <span>{{ pendingReplyText }}</span>
                  <span class="typing-dots text-gray-500"><span>.</span><span>.</span><span>.</span></span>
                </div>
                <div v-if="pendingReplyHint" class="mt-1 text-[12px] text-gray-500">
                  {{ pendingReplyHint }}
                </div>
              </div>
            </div>
          </div>

          <!-- 输入区 -->
          <div
            v-if="isWaitingDisclosure"
            class="px-3 py-2 border-t border-gray-700 bg-[#242424] text-[13px] text-gray-400"
          >
            {{ inputAssistText }}
          </div>
          <div class="p-3 border-t border-gray-600 flex gap-2">
            <div class="relative flex-1 space-y-2">
              <div class="flex flex-wrap items-center gap-1.5">
                <button
                  v-for="action in draftActions"
                  :key="action.key"
                  class="px-2.5 py-1 rounded text-xs"
                  :class="selectedDraftAction === action.key ? 'bg-[#84A65B] text-white' : 'bg-[#3a3a3a] text-gray-300 hover:bg-[#4a4a4a]'"
                  :title="action.hint"
                  @click="selectDraftAction(action.key)"
                >
                  {{ action.label }}
                </button>
                <select
                  v-model="selectedTargetKey"
                  class="ml-auto min-w-[112px] rounded bg-[#2a2a2a] border border-gray-600 px-2 py-1 text-xs text-gray-100 outline-none focus:border-[#84A65B]"
                  @change="applyInputRouteState"
                >
                  <option
                    v-for="target in targetOptions"
                    :key="target.key"
                    :value="target.key"
                  >
                    {{ target.label }}
                  </option>
                </select>
              </div>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="target in targetQuickOptions"
                  :key="target.key"
                  class="px-2 py-1 rounded text-[11px]"
                  :class="selectedTargetKey === target.key ? 'bg-[#84A65B] text-white' : 'bg-[#3a3a3a] text-gray-300 hover:bg-[#4a4a4a]'"
                  @click="selectTarget(target.key)"
                >
                  {{ target.label }}
                </button>
              </div>
              <input
                ref="draftInput"
                v-model="draft"
                :class="inputCls"
                :disabled="s.connection === 'reconnecting'"
                :placeholder="draftPlaceholder"
                @input="onDraftInput"
                @keydown="onDraftKeydown"
              />
              <div
                class="text-[11px]"
                :class="routeGuardText ? 'text-yellow-300' : 'text-gray-500'"
              >
                {{ routeGuardText || inputRouteHint }}
              </div>
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
              class="px-4 rounded bg-[#84A65B] text-white text-base disabled:opacity-50"
              :disabled="sendDisabled"
              @click="onSend"
            >
              发送
            </button>
          </div>
        </div>

        <!-- 成员区 -->
        <div class="w-36 border-l border-gray-600 py-2 overflow-y-auto">
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
import { reactive, ref, computed, nextTick, watch, onMounted, onBeforeUnmount } from 'vue';
import lanchat from '../../../stores/lanchat.js';
import {
  buildGmDecisionMessage,
  buildGmDisclosureActionMessage,
  buildManualGmMessageOptions,
  buildParticipantDisclosureDraft,
} from '../../../stores/lanchatDisclosure.js';
import MemberList from './MemberList.vue';
import {
  resolveSelectedTargetKey,
  routeGuardMessage,
  targetPayloadForKey,
} from './routeSelection.js';
import {
  addCustomExpert,
  createExpertGroupConfig,
  removeCustomExpert,
  selectedExpertPayloads as buildSelectedExpertPayloads,
  setRoleSelected,
} from './expertGroupConfig.js';

const s = lanchat.state;
const lobbyTab = ref('create');
const roomMode = ref('multi');
const draft = ref('');
const selectedWorkspaceMode = ref(s.workspaceMode || 'multiplayer_multi_agent');
const selectedDraftAction = ref(s.draftAction || 'chat');
const selectedTargetKey = ref('scene');
const showAddAgent = ref(false);
const agentForm = reactive({ name: '', persona: '' });
const customExpertForm = reactive({ name: '', persona: '' });
const mentionCandidates = ref([]);
const mentionActiveIndex = ref(0);
const msgRef = ref(null);
const draftInput = ref(null);
const nowMs = ref(Date.now());
const pendingReplyTarget = ref('AI 助手');
const pendingReplySinceMs = ref(0);
let waitClock = null;

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
const defaultExpertRoleKeys = roleTemplateBundles[0]?.roles || [];
const expertGroupConfig = reactive(createExpertGroupConfig(roleTemplates, defaultExpertRoleKeys));

const workspaceModes = [
  {
    key: 'solo_single_agent',
    label: '自己设计',
    hint: '本地单人，默认设计助手',
  },
  {
    key: 'solo_multi_agent',
    label: 'AI 专家组',
    hint: '本地单人，多助手讨论',
  },
  {
    key: 'multiplayer_multi_agent',
    label: '多人共创',
    hint: '房主开房，成员加入',
  },
];

const draftActions = [
  { key: 'chat', label: '问一下', hint: '只让目标回复，不生成场景' },
  { key: 'plan', label: '生成方案', hint: '先整理可确认方案' },
  { key: 'supplement', label: '补充要求', hint: '更新当前目标方案' },
  { key: 'generate', label: '确认生成', hint: '按当前方案进入生成' },
  { key: 'edit', label: '调整场景', hint: '对已有场景提出修改' },
];

const form = reactive({
  room: '',
  password: '',
  ip: '',
  port: 27960,
  nickname: '',
});

const inputCls =
  'w-full px-3 py-2 rounded bg-[#2a2a2a] border border-gray-600 text-[15px] text-gray-100 outline-none focus:border-[#84A65B]';

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
const createButtonText = computed(() => {
  if (roomMode.value === 'multi') return '创建多人房间';
  if (s.selectedHistoryRoom) return '继续所选历史';
  return selectedWorkspaceMode.value === 'solo_multi_agent' ? '进入 AI 专家组' : '进入自己设计';
});
const selectedExpertPayloads = computed(() => buildSelectedExpertPayloads(expertGroupConfig, roleTemplates));
const roomStatusLabel = computed(() => {
  if (s.connection === 'connected') return s.role === 'host' ? '房主在线' : '已连接';
  if (s.connection === 'reconnecting') return '重连中';
  if (s.connection === 'syncing') return '同步中';
  if (s.connection === 'connecting') return '连接中';
  return '未连接';
});
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
const isWaitingDisclosure = computed(() => {
  const disclosure = currentDisclosure.value;
  if (!disclosure) return false;
  if (disclosure.requires_confirmation) return false;
  const stage = String(disclosure.stage || '');
  const message = String(disclosure.public_message || '');
  const progress = Number(disclosure.progress || 0);
  if (progress > 0 && progress < 100) return true;
  return /排队|等待|生成|资源|图片|模型|检索|下载|导入|组装|审查|检查|可介入|执行中/.test(`${stage} ${message}`);
});
const disclosureAgeText = computed(() => {
  const disclosure = currentDisclosure.value;
  if (!disclosure?.created_at) return '';
  const elapsed = Math.max(0, Math.floor((nowMs.value - Number(disclosure.created_at) * 1000) / 1000));
  if (elapsed < 15) return '刚刚更新';
  if (elapsed < 60) return `${elapsed} 秒前`;
  const minutes = Math.floor(elapsed / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  return `${Math.floor(minutes / 60)} 小时前`;
});
const waitHintText = computed(() => {
  if (!isWaitingDisclosure.value) return '';
  const disclosure = currentDisclosure.value || {};
  const stage = `${disclosure.stage || ''} ${disclosure.public_message || ''}`;
  if (/排队|等待资源/.test(stage)) return '任务已进入队列，生成资源空出来后会自动继续。';
  if (/图片/.test(stage)) return '图片阶段耗时可能较长，期间可以继续补充风格或新增物体。';
  if (/模型|检索|下载/.test(stage)) return '模型资源正在准备，慢任务会分批完成并继续更新。';
  if (/导入|组装/.test(stage)) return '正在把本批模型放入场景，建议等当前批次落地后再评价布局。';
  if (/审查|检查|VLM/.test(stage)) return '正在做外观或摆放检查，结果只会形成建议，不会直接覆盖你的场景。';
  if (/可介入/.test(stage)) return '现在可以补充“新增、调整、说明、问题”，系统会优先带入下一批。';
  return '系统仍在处理；长耗时阶段会持续更新，未完成前不要反复确认同一任务。';
});
const waitSteps = computed(() => {
  const disclosure = currentDisclosure.value;
  if (!disclosure || !isWaitingDisclosure.value) return [];
  const labels = [
    { key: 'plan', label: '理解方案' },
    { key: 'image', label: '图片/素材' },
    { key: 'model', label: '模型生成' },
    { key: 'import', label: '导入组装' },
    { key: 'review', label: '检查收尾' },
  ];
  const progress = Number(disclosure.progress || 0);
  const text = `${disclosure.stage || ''} ${disclosure.public_message || ''}`;
  let activeIndex = Math.min(labels.length - 1, Math.max(0, Math.floor(progress / 25)));
  if (/图片|素材|检索|下载/.test(text)) activeIndex = 1;
  if (/模型/.test(text)) activeIndex = 2;
  if (/导入|组装|摆放/.test(text)) activeIndex = 3;
  if (/审查|检查|最终|完成/.test(text)) activeIndex = 4;
  return labels.map((step, index) => ({
    ...step,
    active: index === activeIndex,
    done: index < activeIndex,
  }));
});
const inputAssistText = computed(() => {
  if (!isWaitingDisclosure.value) return '';
  if (s.role === 'host') {
    return '等待期间可以继续输入：说明、调整、新增或 @GM 查询状态；系统会按批次吸收。';
  }
  return '等待期间可以继续补充想法；涉及执行和确认的操作会交给房主处理。';
});
const draftPlaceholder = computed(() => {
  if (s.connection === 'reconnecting') return '连接已断开';
  if (isWaitingDisclosure.value) return '生成中也可输入：新增一个… / 调整… / 问题…';
  if (selectedDraftAction.value === 'plan') return '描述你想设计什么';
  if (selectedDraftAction.value === 'supplement') return '写清要改的风格、物件、布局或限制';
  if (selectedDraftAction.value === 'generate') return '确认按当前方案生成，也可补一句生成范围';
  if (selectedDraftAction.value === 'edit') return '描述要调整的已有物体或位置';
  return '输入要问的问题';
});
const showAiReplySpinner = computed(() => {
  if (!pendingReplySinceMs.value) return false;
  if (isWaitingDisclosure.value) return false;
  if (s.connection === 'reconnecting') return false;
  return nowMs.value - pendingReplySinceMs.value < 90000;
});
const pendingReplyText = computed(() => {
  const elapsed = Math.max(0, Math.floor((nowMs.value - pendingReplySinceMs.value) / 1000));
  if (elapsed >= 20) return `${pendingReplyTarget.value} 仍在处理`;
  if (elapsed >= 8) return `${pendingReplyTarget.value} 正在整理`;
  return `${pendingReplyTarget.value} 正在思考`;
});
const pendingReplyHint = computed(() => {
  if (!pendingReplySinceMs.value) return '';
  const elapsed = Math.max(0, Math.floor((nowMs.value - pendingReplySinceMs.value) / 1000));
  if (elapsed < 12) return '';
  return '复杂方案或工具调用可能需要更久，你可以继续补充要求。';
});
const resourceDiagnosisText = computed(() => {
  if (!currentDisclosure.value || currentDisclosure.value.stage !== '资源调度') return '';
  return resourceDiagnosisLabel(currentDisclosure.value.metadata?.diagnosis);
});
const targetOptions = computed(() => {
  const options = [];
  const agents = Array.isArray(s.agents) ? s.agents : [];
  if (agents.length) {
    for (const agent of agents) {
      options.push({
        key: `agent:${agent.agent_id || agent.name}`,
        label: agent.name,
        scope: 'agent',
        agentId: agent.agent_id || agent.name || '',
        agentName: agent.name || agent.agent_name || '',
      });
    }
  } else {
    options.push({
      key: 'agent:design-assistant',
      label: '设计助手',
      scope: 'agent',
      agentId: 'design-assistant',
      agentName: '设计助手',
    });
  }
  options.push({ key: 'group', label: '专家组', scope: 'group' });
  options.push({ key: 'gm', label: '主持人', scope: 'gm', agentId: 'gm', agentName: 'GM' });
  options.push({ key: 'scene', label: '当前场景', scope: 'scene' });
  return options;
});
const selectedTarget = computed(() => (
  targetOptions.value.find((item) => item.key === selectedTargetKey.value) ||
  targetOptions.value[0]
));
const targetQuickOptions = computed(() => targetOptions.value.filter((item) => (
  item.scope === 'agent' || item.scope === 'group' || item.scope === 'scene'
)));
const inputRouteHint = computed(() => {
  const target = selectedTarget.value?.label || '当前目标';
  const action = draftActions.find((item) => item.key === selectedDraftAction.value)?.label || '发送';
  return `${action} · 发给 ${target}`;
});
const routeGuardText = computed(() => routeGuardMessage(
  selectedDraftAction.value,
  selectedTarget.value,
  draft.value
));
const sendDisabled = computed(() => s.connection === 'reconnecting' || Boolean(routeGuardText.value));

function refreshHistoryRooms() {
  return lanchat.refreshHistoryRooms();
}

function loadHistoryRoom(room) {
  return lanchat.loadHistoryRoom(room);
}

function historyRoomTitle(room) {
  if (!room) return '';
  return room.room_id === 'single-default' ? '单人聊天室' : room.room_id;
}

function formatHistoryTime(ts) {
  const seconds = Number(ts || 0);
  if (!seconds) return '';
  const date = new Date(seconds * 1000);
  const pad = (value) => String(value).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

onMounted(refreshHistoryRooms);

onMounted(() => {
  waitClock = window.setInterval(() => {
    nowMs.value = Date.now();
  }, 1000);
});

onBeforeUnmount(() => {
  if (waitClock) window.clearInterval(waitClock);
  waitClock = null;
});

function selectWorkspaceMode(mode) {
  selectedWorkspaceMode.value = mode;
  lanchat.setWorkspaceMode(mode);
  if (mode === 'multiplayer_multi_agent') {
    roomMode.value = 'multi';
  } else {
    roomMode.value = 'single';
    lobbyTab.value = 'create';
  }
}

function selectDraftAction(action) {
  selectedDraftAction.value = action;
  lanchat.setDraftAction(action);
  applyInputRouteState();
}

function selectTarget(key) {
  selectedTargetKey.value = resolveSelectedTargetKey(key, targetOptions.value);
  applyInputRouteState();
}

function applyInputRouteState() {
  lanchat.setDraftAction(selectedDraftAction.value);
  lanchat.setActiveTarget(targetPayloadForKey(selectedTargetKey.value, targetOptions.value));
}

function setExpertRoleSelected(key, selected) {
  setRoleSelected(expertGroupConfig, key, selected);
}

function addCustomExpertFromForm() {
  addCustomExpert(expertGroupConfig, customExpertForm);
  customExpertForm.name = '';
  customExpertForm.persona = '';
}

function removeCustomExpertAt(index) {
  removeCustomExpert(expertGroupConfig, index);
}

async function onCreate() {
  selectWorkspaceMode(selectedWorkspaceMode.value);
  if (roomMode.value === 'single') {
    if (s.selectedHistoryRoom) {
      await continueHistoryAsSingle();
      return;
    }
    const res = await lanchat.openRoom({
      room: makeLocalRoomId(),
      password: '',
      port: form.port || 27960,
      mode: 'single',
    });
    if (!(res && res.ok)) return;
    if (selectedWorkspaceMode.value === 'solo_multi_agent') {
      await addDefaultExpertGroup();
    }
    return;
  }
  if (!form.room.trim()) return;
  await lanchat.openRoom({
    room: form.room.trim(),
    password: form.password,
    port: form.port || 27960,
    mode: roomMode.value,
  });
}

async function continueHistoryAsSingle() {
  if (!s.selectedHistoryRoom?.room_id) return;
  roomMode.value = 'single';
  lobbyTab.value = 'create';
  lanchat.setWorkspaceMode(selectedWorkspaceMode.value === 'solo_multi_agent' ? 'solo_multi_agent' : 'solo_single_agent');
  const res = await lanchat.continueHistoryAsLocalRoom({
    room: s.selectedHistoryRoom.room_id,
  });
  if (res && res.ok && selectedWorkspaceMode.value === 'solo_multi_agent') {
    await addDefaultExpertGroup();
  }
}

function makeLocalRoomId() {
  return 'single-default';
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
  if (!text.trim() || sendDisabled.value) return;
  applyInputRouteState();
  startPendingReply(text);
  lanchat.sendMessage(text, messageOptionsForText(text)).then((res) => {
    if (res && res.ok === false) {
      clearPendingReply();
      return;
    }
    draft.value = '';
    mentionCandidates.value = [];
    mentionActiveIndex.value = 0;
  }).catch((error) => {
    clearPendingReply();
    console.warn('[LANChat] send message failed', error);
  });
}

function startPendingReply(text) {
  const target = pendingTargetForText(text);
  pendingReplyTarget.value = target || 'AI 助手';
  pendingReplySinceMs.value = Date.now();
}

function clearPendingReply() {
  pendingReplySinceMs.value = 0;
}

function pendingTargetForText(text) {
  const trimmed = String(text || '').trim();
  const mention = trimmed.match(/^@([^\s，,：:]+)/);
  if (mention?.[1]) return mention[1];
  if (selectedTarget.value?.label) return selectedTarget.value.label;
  if (s.mode === 'single' && s.agents.length === 1) return s.agents[0].name || 'AI 助手';
  return 'AI 助手';
}

function isAiReplyMessage(message) {
  if (!message || message.self) return false;
  const from = String(message.from || '');
  if (!from || from === '系统') return false;
  if (from === s.nickname) return false;
  return true;
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
  await lanchat.sendMessage(message.text, { ...(message.options || {}), skipStructuredRoute: true });
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
    await lanchat.sendMessage(message.text, { ...(message.options || {}), skipStructuredRoute: true });
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

async function addDefaultExpertGroup() {
  const existingNames = new Set(
    (s.agents || [])
      .map((agent) => String(agent.name || '').trim())
      .filter(Boolean)
  );
  for (const expert of selectedExpertPayloads.value) {
    const name = String(expert?.name || '').trim();
    if (!name || existingNames.has(name)) continue;
    const res = await lanchat.addAgent(expert);
    if (res && res.ok) existingNames.add(name);
  }
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
  const generationMetadata = s.role === 'host' ? lanchat.generationOptionsMetadata() : {};
  applyInputRouteState();
  if (/^@GM(?:\s|$)/i.test(trimmed)) {
    if (!Object.keys(generationMetadata).length) return buildManualGmMessageOptions(s.role);
    const options = buildManualGmMessageOptions(s.role);
    options.metadata = {
      ...(options.metadata || {}),
      ...generationMetadata,
    };
    return options;
  }
  return Object.keys(generationMetadata).length
    ? { metadata: generationMetadata }
    : {};
}

function onVlmToggle(event) {
  const enabled = Boolean(event?.target?.checked);
  lanchat.setGenerationOptions({
    vlmEnabled: enabled,
    vlmMaxTargets: enabled ? 1 : 0,
  });
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
    const latest = s.messages[s.messages.length - 1];
    if (isAiReplyMessage(latest)) clearPendingReply();
    await nextTick();
    if (msgRef.value) msgRef.value.scrollTop = msgRef.value.scrollHeight;
  }
);

watch(
  () => currentDisclosure.value?.event_id,
  async () => {
    if (currentDisclosure.value) clearPendingReply();
    await nextTick();
    if (msgRef.value) msgRef.value.scrollTop = msgRef.value.scrollHeight;
  }
);

watch(
  showAiReplySpinner,
  async () => {
    await nextTick();
    if (msgRef.value) msgRef.value.scrollTop = msgRef.value.scrollHeight;
  }
);

watch(
  targetOptions,
  (options) => {
    if (!options.length) return;
    selectedTargetKey.value = resolveSelectedTargetKey(selectedTargetKey.value, options);
    applyInputRouteState();
  },
  { immediate: true }
);

watch(
  () => s.workspaceMode,
  (mode) => {
    if (mode && mode !== selectedWorkspaceMode.value) {
      selectedWorkspaceMode.value = mode;
    }
  }
);

watch(
  () => s.draftAction,
  (action) => {
    if (action && action !== selectedDraftAction.value) {
      selectedDraftAction.value = action;
    }
  }
);
</script>
