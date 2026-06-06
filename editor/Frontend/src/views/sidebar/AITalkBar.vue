<template>
  <div class="flex flex-col flex-1 min-h-0 w-full rounded-lg overflow-hidden relative bg-[#282828]/90">
    <DockTitleBar
      v-if="!isDocked"
      title="助手"
      extraClass="bg-[#84A65B]"
      routePath="/AITalkBar"
      @close="closeFloat"
    />

    <!-- 主内容区域 -->
    <div class="w-full bg-[#a8a4a3]/65 flex flex-col" style="height: calc(100vh - 48px)">
      <!-- 对话记录区域 -->
      <div ref="chatHistoryRef" class="flex-1 overflow-y-auto p-4">
        <div class="max-w-6xl mx-auto">
          <div class="space-y-2 pr-2">
            <div
              v-for="(message, index) in messages"
              :key="index"
              class="p-3 bg-[#E8E8E8]/80 rounded-lg shadow-sm border border-gray-100 space-y-2"
              :class="{
                'opacity-70': message.status === 'sending',
                'border-red-300 bg-red-50/50': message.status === 'failed',
                'border-purple-300 animate-pulse': message.status === 'streaming',
              }"
            >
              <div>
                <span
                  :class="{
                    'text-blue-500': message.sender === 'AI',
                    'text-green-500': message.sender === 'User',
                    'text-gray-500': message.sender === '系统',
                  }"
                  class="font-medium"
                >
                  {{ message.sender }}:
                </span>
                <!-- 无 parts 时（User/系统消息）显示纯文本 -->
                <RichTextPart
                  v-if="message.text && !message.parts"
                  class="mt-1"
                  :text="message.text"
                  :format="message.richTextFormat || (message.sender === 'AI' ? 'auto' : 'plain')"
                />

                <!-- 发送状态指示器 -->
                <span v-if="message.status === 'sending'" class="ml-2 text-xs text-gray-500">
                  <span class="inline-block animate-pulse">发送中...</span>
                </span>
                <span v-if="message.status === 'failed'" class="ml-2 text-xs text-red-500">
                  发送失败
                  <button
                    class="ml-2 px-2 py-0.5 bg-red-500 text-white rounded hover:bg-red-600 text-xs"
                    @click="retryMessage(index)"
                  >
                    重试
                  </button>
                </span>
              </div>

              <!-- AI 消息：按 parts 顺序渲染 -->
              <template v-if="message.parts && message.parts.length > 0">
                <template v-for="(part, pIdx) in message.parts" :key="pIdx">
                  <RichTextPart
                    v-if="part.type === 'text'"
                    :text="part.text"
                    :format="part.format || part.metadata?.format || 'auto'"
                    :streaming="message.status === 'streaming'"
                  />
                  <div v-else-if="part.type === 'image'" class="max-w-sm mt-1">
                    <img
                      :src="part.url"
                      :alt="part.name || 'image'"
                      class="rounded border cursor-pointer max-h-60 object-contain"
                      @click="openImagePreview({ imageData: part.url, imageName: part.name })"
                    />
                  </div>
                  <div v-else-if="part.type === 'video'" class="max-w-sm w-full mt-1">
                    <video
                      :src="part.url"
                      controls
                      class="rounded border max-h-60 w-full bg-black"
                    ></video>
                    <div class="text-xs text-gray-500 mt-1 truncate">{{ part.name || '视频' }}</div>
                  </div>
                  <div v-else-if="part.type === 'audio'" class="w-full mt-1">
                    <audio :src="part.url" controls class="w-full"></audio>
                    <div class="text-xs text-gray-500 mt-1 truncate">{{ part.name || '音频' }}</div>
                  </div>
                  <!-- 审核面板 -->
                  <div
                    v-else-if="part.type === 'review'"
                    class="w-full mt-2 p-3 bg-yellow-50 border border-yellow-300 rounded-lg"
                  >
                    <div class="font-medium text-yellow-800 mb-2">{{ part.text }}</div>
                    <div v-if="reviewEdits.length > 0" class="space-y-3">
                      <div
                        v-for="(item, rIdx) in reviewEdits"
                        :key="item.__itemId"
                        class="p-2 bg-white rounded border border-gray-200 space-y-2"
                        :class="{
                          'border-green-400 bg-green-50/30': item._confirmed,
                          'border-red-300 bg-red-50/40 opacity-80': item.__deleted,
                        }"
                      >
                        <div class="flex items-center justify-between gap-3">
                          <div class="text-sm font-medium text-gray-700">
                            {{ item.item_name || `元素 ${rIdx + 1}` }}
                            <span
                              v-if="item.__source === 'new'"
                              class="ml-2 text-[10px] px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded"
                            >
                              新增
                            </span>
                            <span
                              v-if="item.__deleted"
                              class="ml-2 text-[10px] px-1.5 py-0.5 bg-red-100 text-red-700 rounded"
                            >
                              已标记删除
                            </span>
                          </div>
                        </div>
                        <div v-for="(val, key) in item" :key="key" class="space-y-1">
                          <template v-if="isEditableReviewField(key)">
                            <label class="text-xs text-gray-500">{{ key }}</label>
                            <!-- 媒体字段：预览 + 上传 -->
                            <div
                              v-if="
                                typeof val === 'string' &&
                                (val.startsWith('http') ||
                                  val.startsWith('data:') ||
                                  val.startsWith('file:'))
                              "
                              class="flex items-center gap-2"
                            >
                              <img :src="val" class="h-16 w-16 object-cover rounded border" />
                              <label
                                class="px-2 py-1 text-xs bg-blue-500 text-white rounded cursor-pointer hover:bg-blue-600"
                              >
                                上传替换
                                <input
                                  type="file"
                                  accept="image/*"
                                  class="hidden"
                                  @change="
                                    async (e) => {
                                      const f = e.target.files[0];
                                      if (f) {
                                        const b = await fileToBase64(f);
                                        reviewEdits[rIdx][key] = b;
                                        reviewEdits[rIdx]._confirmed = true;
                                      }
                                      e.target.value = '';
                                    }
                                  "
                                />
                              </label>
                            </div>
                            <!-- 文本字段：textarea -->
                            <textarea
                              v-else-if="typeof val === 'string'"
                              v-model="reviewEdits[rIdx][key]"
                              rows="2"
                              class="w-full text-sm p-1.5 border border-gray-300 rounded resize-y focus:border-blue-400 focus:outline-none"
                              @input="reviewEdits[rIdx]._confirmed = true"
                            ></textarea>
                          </template>
                        </div>
                        <div class="flex gap-2 justify-end mt-1">
                          <button
                            v-if="item.__source === 'original'"
                            class="px-2 py-1 text-xs rounded"
                            :class="
                              item.__deleted
                                ? 'bg-green-500 text-white hover:bg-green-600'
                                : 'bg-red-500 text-white hover:bg-red-600'
                            "
                            @click="toggleReviewItemDeleted(rIdx)"
                          >
                            {{ item.__deleted ? '恢复项目' : '标记删除' }}
                          </button>
                          <button
                            v-else
                            class="px-2 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600"
                            @click="removeReviewItem(rIdx)"
                          >
                            删除项目
                          </button>
                          <button
                            class="px-2 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                            @click="resetReviewItem(rIdx)"
                          >
                            重置修改
                          </button>
                        </div>
                      </div>
                    </div>
                    <div v-else class="text-sm text-yellow-700 bg-yellow-100/60 rounded p-2">
                      当前无审核项目，请新增后提交。
                    </div>
                    <div class="flex justify-between items-center mt-3">
                      <button
                        class="px-3 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 font-medium"
                        @click="addReviewItem()"
                      >
                        新增项目
                      </button>
                      <button
                        class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
                        @click="submitReview()"
                      >
                        提交审核
                      </button>
                    </div>
                    <div v-if="reviewError" class="mt-2 text-xs text-red-600">
                      {{ reviewError }}
                    </div>
                  </div>
                </template>
              </template>

              <!-- User/系统消息：旧格式 bucket 渲染 -->
              <template v-if="!message.parts">
                <!-- 单张图片显示 -->
                <div v-if="message.imageData" class="max-w-sm">
                  <img
                    :src="message.imageData"
                    :alt="message.imageName || 'image'"
                    class="rounded border cursor-pointer max-h-60 object-contain"
                    @click="openImagePreview(message)"
                  />
                  <div v-if="message.imageName" class="text-xs text-gray-500 mt-1">
                    {{ message.imageName }}
                  </div>
                </div>
                <!-- 多张图片显示 -->
                <div
                  v-if="message.images && message.images.length > 0"
                  class="flex flex-wrap gap-2"
                >
                  <div v-for="(img, imgIdx) in message.images" :key="imgIdx" class="max-w-xs">
                    <img
                      :src="img.preview"
                      :alt="img.name"
                      class="rounded border cursor-pointer max-h-40 object-contain"
                      @click="openImagePreview({ imageData: img.preview, imageName: img.name })"
                    />
                    <div class="text-xs text-gray-500 mt-1 truncate">{{ img.name }}</div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="bg-[#E8E8E8]/80 border-t border-gray-200 shadow-lg backdrop-blur-sm">
        <div class="max-w-6xl mx-auto p-4">
          <!-- 隐藏图片选择器 -->
          <input
            ref="imageInputRef"
            type="file"
            accept="image/*"
            class="hidden"
            @change="onImageChange"
          />

          <div class="space-y-2">
            <!-- 顶部：导入图片和提示词按钮 -->
            <div class="flex gap-2">
              <button
                class="px-3 py-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 whitespace-nowrap"
                @click="triggerImageSelect('product')"
              >
                导入产品
              </button>
              <button
                class="px-3 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 whitespace-nowrap"
                @click="triggerImageSelect('scene')"
              >
                导入场景
              </button>
              <div class="relative" @keydown.escape="hidePrompts">
                <button
                  class="px-3 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 whitespace-nowrap"
                  @click="togglePrompts"
                >
                  提示词
                </button>
                <transition name="fade">
                  <div
                    v-if="showPrompts"
                    class="absolute bottom-full left-0 mb-2 w-64 max-h-72 overflow-y-auto bg-white/95 backdrop-blur border border-gray-200 rounded-lg shadow-lg p-2 space-y-1 z-50"
                  >
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-xs text-gray-500">常用提示词</span>
                      <button
                        class="text-xs text-gray-400 hover:text-gray-600"
                        @click="hidePrompts"
                      >
                        关闭
                      </button>
                    </div>
                    <template v-for="(p, i) in promptPresets" :key="i">
                      <button
                        class="w-full text-left text-sm px-2 py-1 rounded hover:bg-amber-100 focus:bg-amber-100 focus:outline-none"
                        @click="applyPrompt(p)"
                      >
                        {{ p.label }}
                      </button>
                    </template>
                  </div>
                </transition>
              </div>
            </div>

            <!-- 中间：输入框和待发送图片预览 -->
            <div class="bg-white rounded-lg border border-gray-300 p-2 space-y-2">
              <textarea
                v-model="userInput"
                placeholder="输入消息... (或以 / 开头输入工作流命令，如 /multi_scene 生成设计方案)"
                class="w-full p-2 border-none rounded-lg focus:ring-0 focus:outline-none transition-all resize-none"
                rows="3"
                @keydown.enter="handleEnter"
              ></textarea>

              <div v-if="hasPendingImages" class="space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-xs text-gray-600">待发送图片</span>
                  <button class="text-xs text-red-500 hover:text-red-700" @click="clearAllImages">
                    清空全部
                  </button>
                </div>
                <div class="flex flex-wrap gap-4">
                  <div v-for="type in imageTypes" :key="type">
                    <div v-if="pendingImages[type]" class="relative group">
                      <img
                        :src="pendingImages[type].preview"
                        :alt="pendingImages[type].name"
                        class="h-20 w-20 object-cover rounded border border-blue-300"
                      />

                      <!-- 上传中遮罩 -->
                      <div
                        v-if="pendingImages[type].uploading"
                        class="absolute inset-0 bg-black/50 rounded flex items-center justify-center"
                      >
                        <svg
                          class="animate-spin h-6 w-6 text-white"
                          xmlns="http://www.w3.org/2000/svg"
                          fill="none"
                          viewBox="0 0 24 24"
                        >
                          <circle
                            class="opacity-25"
                            cx="12"
                            cy="12"
                            r="10"
                            stroke="currentColor"
                            stroke-width="4"
                          ></circle>
                          <path
                            class="opacity-75"
                            fill="currentColor"
                            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                          ></path>
                        </svg>
                      </div>

                      <!-- 移除按钮 -->
                      <button
                        v-if="!pendingImages[type].uploading"
                        class="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center hover:bg-red-600 opacity-0 group-hover:opacity-100 transition-opacity"
                        @click="removeImage(type)"
                      >
                        ×
                      </button>

                      <div
                        class="text-xs text-gray-600 mt-1 w-20 truncate capitalize"
                        :title="pendingImages[type].name"
                      >
                        {{ imageTypeLabels[type] }}
                        <span v-if="pendingImages[type].uploading" class="text-blue-500">
                          上传中
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 底部：发送按钮 -->
            <div class="flex justify-end">
              <button
                :disabled="isSending"
                class="px-5 py-2 bg-blue-500 text-white rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 whitespace-nowrap"
                :class="{
                  'hover:bg-blue-600': !isSending,
                  'opacity-50 cursor-not-allowed': isSending,
                }"
                @click="sendMessage"
              >
                <span v-if="!isSending">发送</span>
                <span v-else class="flex items-center gap-2">
                  <svg
                    class="animate-spin h-4 w-4"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      class="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      stroke-width="4"
                    ></circle>
                    <path
                      class="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    ></path>
                  </svg>
                  发送中...
                </span>
              </button>
            </div>

            <div v-if="imageError" class="text-xs text-red-500">{{ imageError }}</div>
          </div>
        </div>
      </div>

      <!-- 简单图片预览遮罩 -->
      <div
        v-if="imagePreview"
        class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100]"
        @click.self="imagePreview = null"
      >
        <div class="bg-white p-4 rounded shadow max-w-[90vw] max-h-[90vh] flex flex-col">
          <img
            :src="imagePreview.imageData"
            :alt="imagePreview.imageName"
            class="object-contain max-w-full max-h-[70vh]"
          />
          <div class="mt-2 flex justify-between items-center text-sm text-gray-600">
            <span>{{ imagePreview.imageName }}</span>
            <button
              class="px-3 py-1 bg-gray-800 text-white rounded hover:bg-gray-700"
              @click="imagePreview = null"
            >
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';
import RichTextPart from '@/components/ui/RichTextPart.vue';
import { appService, aiClient, aiService } from '@/utils/bridge.js';
import { useErrorHandler } from '@/composables/useErrorHandler.js';
import { useDockPanel } from '@/composables/useDockPanel.js';
import { coronaEventBus } from '@/utils/eventBus.js';

const { closePanel: closeDockPanel, isDocked } = useDockPanel();
const { error: logError, warn: logWarn } = useErrorHandler('AITalkBar');

const messages = ref([{ sender: 'AI', text: '你好！我是 AI。', status: 'success' }]);
const userInput = ref('');
const chatHistoryRef = ref(null);
// sessionId 由前端负责生成，后端仅作兜底
const sessionId = ref(null);

// 生成随机 session id（优先使用 crypto.randomUUID）
function ensureSessionId() {
  if (sessionId.value) return sessionId.value;
  try {
    // 现代浏览器支持 crypto.randomUUID()
    sessionId.value =
      window.crypto && window.crypto.randomUUID
        ? window.crypto.randomUUID()
        : `sid_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  } catch (e) {
    sessionId.value = `sid_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  }
  return sessionId.value;
}

function createRequestId() {
  try {
    return window.crypto && window.crypto.randomUUID
      ? window.crypto.randomUUID()
      : `req_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  } catch (e) {
    return `req_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  }
}

const isSending = ref(false); // 发送状态
const sendTimeout = ref(null); // 发送超时定时器
const MESSAGE_TIMEOUT = 30000; // 30秒超时

const currentStreamingMessage = ref(null); // 当前正在流式接收的消息索引
const currentStreamingCheckpoint = ref(null); // 当前流式气泡绑定的 checkpoint 标识
const currentStreamingRequestId = ref(null); // 当前流式请求 ID（兼容新 ai_rpc 链路）
const streamCompletionTimer = ref(null); // 流式完成检测定时器
const streamingMessagesByRequestId = ref({}); // request_id -> 当前 AI 气泡索引
const streamingCheckpointsByRequestId = ref({}); // request_id -> 当前 checkpoint 标识
const streamCompletionTimersByRequestId = ref({}); // request_id -> 断连检测定时器
const HEARTBEAT_TIMEOUT = 15000; // 15秒无心跳/数据则认为连接断开

function getStreamingMessageIndex(requestId) {
  if (requestId) {
    return streamingMessagesByRequestId.value[requestId] ?? null;
  }
  return currentStreamingMessage.value;
}

function setStreamingMessageIndex(requestId, index) {
  if (requestId) {
    streamingMessagesByRequestId.value[requestId] = index;
  }
  currentStreamingMessage.value = index;
}

function getStreamingCheckpoint(requestId) {
  if (requestId) {
    return streamingCheckpointsByRequestId.value[requestId] ?? null;
  }
  return currentStreamingCheckpoint.value;
}

function setStreamingCheckpoint(requestId, checkpoint) {
  if (requestId) {
    if (checkpoint === null) {
      delete streamingCheckpointsByRequestId.value[requestId];
    } else {
      streamingCheckpointsByRequestId.value[requestId] = checkpoint;
    }
  }
  currentStreamingCheckpoint.value = checkpoint;
}

function clearStreamingTimer(requestId) {
  const timer = requestId ? streamCompletionTimersByRequestId.value[requestId] : null;
  if (timer) {
    clearTimeout(timer);
    delete streamCompletionTimersByRequestId.value[requestId];
  }
  if (!requestId || requestId === currentStreamingRequestId.value) {
    if (streamCompletionTimer.value) {
      clearTimeout(streamCompletionTimer.value);
      streamCompletionTimer.value = null;
    }
  }
}

function clearStreamingState(requestId) {
  clearStreamingTimer(requestId);
  if (requestId) {
    delete streamingMessagesByRequestId.value[requestId];
    delete streamingCheckpointsByRequestId.value[requestId];
  }
  if (!requestId || requestId === currentStreamingRequestId.value) {
    currentStreamingMessage.value = null;
    currentStreamingCheckpoint.value = null;
    currentStreamingRequestId.value = null;
  }
}

function markStreamingMessageStatus(requestId, status) {
  const messageIndex = getStreamingMessageIndex(requestId);
  if (messageIndex !== null && messages.value[messageIndex]) {
    messages.value[messageIndex].status = status;
  }
}

function resetStreamCompletionTimer(requestId) {
  clearStreamingTimer(requestId);
  const timer = setTimeout(() => {
    markStreamingMessageStatus(requestId, 'failed');
    clearStreamingState(requestId);
  }, HEARTBEAT_TIMEOUT);
  if (requestId) {
    streamCompletionTimersByRequestId.value[requestId] = timer;
  }
  streamCompletionTimer.value = timer;
}

// ---- 审核相关状态 ----
const reviewPayload = ref(null); // 当前待审核的 review 数据（parameter.review）
const activeBatchId = ref(null); // 当前审核批次 ID
const activeFunctionId = ref(null); // 当前审核对应的工作流 function_id
const reviewEdits = ref([]); // 用户编辑后的 items 副本
const reviewOriginalMap = ref({}); // original item 快照映射，key 为 __itemId
const reviewFieldTemplate = ref([]); // 新增项字段模板
const reviewError = ref('');

let reviewItemSequence = 0;

function cloneJSON(data) {
  return JSON.parse(JSON.stringify(data));
}

function createReviewItemId() {
  reviewItemSequence += 1;
  return `review_item_${Date.now()}_${reviewItemSequence}`;
}

function isEditableReviewField(key) {
  return !key.startsWith('__') && key !== '_confirmed' && key !== 'is_deleted';
}

function normalizeTemplateFields(items) {
  const fieldSet = new Set();
  for (const item of items || []) {
    if (!item || typeof item !== 'object') continue;
    Object.keys(item).forEach((key) => {
      if (isEditableReviewField(key)) {
        fieldSet.add(key);
      }
    });
  }

  if (!fieldSet.has('item_name')) {
    fieldSet.add('item_name');
  }

  return Array.from(fieldSet);
}

function createReviewItemFromTemplate(source = 'new') {
  const item = {};
  for (const field of reviewFieldTemplate.value) {
    item[field] = '';
  }
  if (!Object.prototype.hasOwnProperty.call(item, 'item_name')) {
    item.item_name = '';
  }

  return {
    ...item,
    __itemId: createReviewItemId(),
    __source: source,
    __deleted: false,
    _confirmed: false,
  };
}

function toReviewEditorItem(rawItem, source = 'original') {
  const normalized = rawItem && typeof rawItem === 'object' ? cloneJSON(rawItem) : {};
  const itemId = createReviewItemId();
  const deleted = Boolean(normalized.is_deleted);

  return {
    ...normalized,
    is_deleted: deleted,
    __itemId: itemId,
    __source: source,
    __deleted: deleted,
    _confirmed: false,
  };
}

function buildReviewSubmitItems() {
  return reviewEdits.value.map((item) => {
    const submitItem = {};
    Object.entries(item).forEach(([key, value]) => {
      if (key.startsWith('__') || key === '_confirmed') {
        return;
      }
      submitItem[key] = value;
    });
    submitItem.is_deleted = Boolean(item.__deleted);
    return submitItem;
  });
}

function extractCheckpointSignature(content) {
  if (!content || !Array.isArray(content.part)) return null;

  for (const part of content.part) {
    const checkpoint = part?.parameter?.checkpoint;
    if (!checkpoint || checkpoint.entry_scope !== 'node') continue;

    const functionId = checkpoint.function_id ?? 'unknown';
    const nodeName = checkpoint.node_name ?? 'unknown';
    const checkpointIndex = checkpoint.checkpoint_index;
    if (checkpointIndex === undefined || checkpointIndex === null) {
      return `${functionId}:${nodeName}`;
    }
    return `${functionId}:${nodeName}:${checkpointIndex}`;
  }

  return null;
}

function hasValidReviewItems(items) {
  const activeItems = items.filter((item) => !item.is_deleted);
  if (activeItems.length === 0) {
    reviewError.value = '请至少保留一个未删除的审核项目。';
    return false;
  }

  const invalidIndex = activeItems.findIndex((item) => !String(item.item_name || '').trim());
  if (invalidIndex >= 0) {
    reviewError.value = `第 ${invalidIndex + 1} 个有效项目缺少 item_name。`;
    return false;
  }

  return true;
}

function initReviewFromPayload(review) {
  reviewError.value = '';
  reviewPayload.value = review;
  activeBatchId.value = review.batch_id;
  activeFunctionId.value = review.function_id; // 保存工作流 ID
  const sourceItems = Array.isArray(review.items) ? review.items : [];
  reviewFieldTemplate.value = normalizeTemplateFields(sourceItems);

  const originalMap = {};
  const parsedItems = sourceItems.map((item) => {
    const editorItem = toReviewEditorItem(item, 'original');
    originalMap[editorItem.__itemId] = cloneJSON(editorItem);
    return editorItem;
  });

  reviewOriginalMap.value = originalMap;
  reviewEdits.value = parsedItems;
}

function resetReviewItem(idx) {
  const current = reviewEdits.value[idx];
  if (!current) return;

  if (current.__source === 'new') {
    const resetNewItem = createReviewItemFromTemplate('new');
    resetNewItem.__itemId = current.__itemId;
    reviewEdits.value[idx] = resetNewItem;
    return;
  }

  const original = reviewOriginalMap.value[current.__itemId];
  if (original) {
    reviewEdits.value[idx] = cloneJSON(original);
  }
}

function addReviewItem() {
  reviewError.value = '';
  reviewEdits.value.push(createReviewItemFromTemplate('new'));
}

function removeReviewItem(idx) {
  const current = reviewEdits.value[idx];
  if (!current || current.__source !== 'new') {
    return;
  }
  reviewEdits.value.splice(idx, 1);
}

function toggleReviewItemDeleted(idx) {
  const current = reviewEdits.value[idx];
  if (!current || current.__source !== 'original') {
    return;
  }

  current.__deleted = !current.__deleted;
  current.is_deleted = current.__deleted;
  if (current.__deleted) {
    current._confirmed = false;
  }
}

async function submitReview() {
  if (!reviewPayload.value) return;
  reviewError.value = '';

  const submitItems = buildReviewSubmitItems();
  if (!hasValidReviewItems(submitItems)) {
    return;
  }

  const submitParts = [
    {
      content_type: 'review',
      content_text: '审核确认',
      content_url: '',
      parameter: {
        review: {
          stage: 'submitted',
          batch_id: activeBatchId.value,
          function_id: activeFunctionId.value, // 回传工作流 ID
          schema_version: reviewPayload.value.schema_version || 1,
          items: submitItems,
        },
      },
    },
  ];

  ensureSessionId();
  const requestId = createRequestId();
  currentStreamingRequestId.value = requestId;
  const payloadObj = {
    session_id: sessionId.value,
    metadata: { review_submit: true, request_id: requestId },
    llm_content: [
      {
        role: 'user',
        interface_type: 'integrated',
        part: submitParts,
      },
    ],
  };

  try {
    await aiClient.chatStream({
      operation: 'chat.stream',
      request_id: requestId,
      session_id: sessionId.value,
      payload: payloadObj,
      metadata: { source: 'AITalkBar', review_submit: true },
    });
    // 清空审核状态，继续接收后续流式输出
    reviewPayload.value = null;
    activeBatchId.value = null;
    activeFunctionId.value = null;
    reviewEdits.value = [];
    reviewOriginalMap.value = {};
    reviewFieldTemplate.value = [];
    reviewError.value = '';
  } catch (err) {
    logError('提交审核失败', err);
    reviewError.value = err?.message || '提交审核失败，请稍后重试。';
  }
}

function parseIncomingAIMessage(data) {
  if (typeof data === 'string') {
    try {
      return JSON.parse(data);
    } catch {
      return { content: data };
    }
  }

  if (data && typeof data === 'object' && !Array.isArray(data)) {
    return data;
  }

  return {
    content: data == null ? '' : String(data),
  };
}

function getAIMessageError(message) {
  if (!message || typeof message !== 'object') {
    return null;
  }

  if (message.success === false) {
    return message.error || message.message || 'AI 处理失败';
  }

  if (!Object.prototype.hasOwnProperty.call(message, 'error_code')) {
    return null;
  }

  const errorCode = Number(message.error_code);
  if (!Number.isFinite(errorCode)) {
    logWarn('收到无法解析的 error_code，按兼容消息处理', message.error_code);
    return null;
  }

  if (errorCode !== 0) {
    return message.status_info || 'AI 处理失败';
  }

  return null;
}

function getTextPartFormat(part, fallback = 'auto') {
  return (
    part?.format ||
    part?.content_format ||
    part?.metadata?.format ||
    part?.parameter?.format ||
    part?.parameter?.metadata?.format ||
    fallback
  );
}

// 图片相关
const imageInputRef = ref(null);
const imageError = ref('');
const imagePreview = ref(null); // {imageData, imageName}
const imageTypes = ['product', 'scene'];
const currentImageType = ref(null); // 'product' | 'scene'
const pendingImages = ref({
  product: null,
  scene: null,
});

const imageTypeLabels = {
  product: '产品',
  scene: '场景',
};

const hasPendingImages = computed(() => {
  return Object.values(pendingImages.value).some((img) => img !== null);
});

// 提示词相关
const showPrompts = ref(false);
const promptPresets = ref([
  { label: '总结以上内容', text: '请总结以上对话的要点。' },
  { label: '解释代码', text: '请详细解释下面这段代码的作用及时间复杂度:\n' },
  { label: '生成测试用例', text: '请为下面的函数编写单元测试（使用pytest）:\n' },
  { label: '优化提示', text: '请审查我的提示词并给出更明确、更可执行的改进建议：\n' },
  { label: '翻译为英文', text: '请将下面的内容准确翻译成英文：\n' },
  { label: '改写更专业', text: '请将下面的文本改写得更专业、清晰且结构良好：\n' },
  { label: '3d模型生成', text: '帮我生成这个图片的3d模型' },
]);

function togglePrompts() {
  showPrompts.value = !showPrompts.value;
}
function hidePrompts() {
  showPrompts.value = false;
}
function applyPrompt(p) {
  userInput.value = p.text;
  hidePrompts();
}

function handleEnter(e) {
  if (e.isComposing) return;
  if (!e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function triggerImageSelect(type) {
  imageError.value = '';
  currentImageType.value = type;
  imageInputRef.value && imageInputRef.value.click();
}

function openImagePreview(message) {
  imagePreview.value = { imageData: message.imageData, imageName: message.imageName };
}

function removeImage(type) {
  if (pendingImages.value[type]) {
    pendingImages.value[type] = null;
  }
}

function clearAllImages() {
  pendingImages.value.product = null;
  pendingImages.value.scene = null;
}

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// 检测并提取用户输入中的 slash 命令
// 返回 {hasCommand: bool, commandText: string, remainingText: string}
function extractSlashCommand(text) {
  const trimmed = text.trim();
  const commandMatch = trimmed.match(/^\/\S+(?:\s+(.*))?$/);

  if (commandMatch) {
    return {
      hasCommand: true,
      commandText: trimmed,
      remainingText: '',
    };
  }

  // 检查是否在文本中间包含命令（如果有的话）
  // 优先查找行首的命令
  const lines = trimmed.split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().match(/^\/\S+/)) {
      const command = lines[i].trim();
      const remaining = [...lines.slice(0, i), ...lines.slice(i + 1)].join('\n').trim();

      return {
        hasCommand: true,
        commandText: command,
        remainingText: remaining,
      };
    }
  }

  return {
    hasCommand: false,
    commandText: '',
    remainingText: trimmed,
  };
}

async function onImageChange(e) {
  const file = e.target.files[0];
  if (!file) return;
  imageError.value = '';

  if (file.size > 20 * 1024 * 1024) {
    imageError.value = `图片 ${file.name} 大小超过 20MB。`;
    e.target.value = '';
    return;
  }

  if (!currentImageType.value) {
    logWarn('图片类型未指定');
    e.target.value = '';
    return;
  }
  try {
    const base64 = await fileToBase64(file);
    const type = currentImageType.value;

    // 只在前端预览，不立即上传
    pendingImages.value[type] = {
      name: file.name,
      preview: base64,
      type,
      path: currentImageType.value.path, // 服务器保存的文件路径
    };

    imageError.value = '';
  } catch (err) {
    logError('读取图片失败', err);
    imageError.value = err?.message || '读取图片失败，请重试。';
    if (currentImageType.value) {
      pendingImages.value[currentImageType.value] = null;
    }
  } finally {
    e.target.value = '';
    currentImageType.value = null; // 重置
  }
}

const SendMessageToAI = async (query, extra = {}) => {
  // 构造符合 llms.txt 规范的请求
  // 智能拆分：如果输入中包含 slash 命令，则单独成 part
  const parts = [];

  if (query) {
    // 尝试提取命令
    const extraction = extractSlashCommand(query);

    // 先添加命令 part（如果有），这样后端会优先捕获
    if (extraction.hasCommand) {
      parts.push({
        content_type: 'text',
        content_text: extraction.commandText,
      });
    }

    // 再添加非命令文本 part（如果有）
    if (extraction.remainingText) {
      parts.push({
        content_type: 'text',
        content_text: extraction.remainingText,
      });
    }

    // 如果既没有命令也没有剩余文本（只有空白），仍保留原始查询
    if (!extraction.hasCommand && !extraction.remainingText) {
      parts.push({
        content_type: 'text',
        content_text: query,
      });
    }
  }

  if (extra.images && extra.images.length > 0) {
    extra.images.forEach((img) => {
      parts.push({
        content_type: 'image',
        content_url: img.url || img.preview,
        content_path: img.path,
        content_text: img.type,
        parameter: {},
      });
    });
  }

  // 确保 session_id 已生成
  ensureSessionId();
  const requestId = createRequestId();
  currentStreamingRequestId.value = requestId;

  const payloadObj = {
    session_id: sessionId.value,
    llm_content: [
      {
        role: 'user',
        interface_type: 'integrated',
        sent_time_stamp: Date.now(),
        part: parts,
      },
    ],
    metadata: { request_id: requestId },
  };

  try {
    await aiClient.chatStream({
      operation: 'chat.stream',
      request_id: requestId,
      session_id: sessionId.value,
      payload: payloadObj,
      metadata: { source: 'AITalkBar' },
    });
  } catch (error) {
    logError('发送消息失败', error);
    throw error;
  }
};

const sendMessage = async () => {
  const text = userInput.value.trim();
  const imagesToSend = imageTypes
    .map((type) => pendingImages.value[type])
    .filter((img) => img !== null);

  // 至少要有文字或图片之一
  if (!text && imagesToSend.length === 0) return;

  // 防止重复发送
  if (isSending.value) return;

  // 保存当前输入以备回滚
  const savedInput = text;
  const savedImages = [...imagesToSend];

  const messageObj = { sender: 'User', status: 'sending' };
  let displayText = text || '';

  if (imagesToSend.length > 0) {
    // 如果没有文字，显示简单的图片标记
    if (!displayText) {
      displayText = imagesToSend.length === 1 ? '[1张图片]' : `[${imagesToSend.length}张图片]`;
    }
    // 如果有文字，不额外添加文件名列表，因为会显示图片缩略图

    if (imagesToSend.length === 1) {
      messageObj.imageData = imagesToSend[0].preview;
      messageObj.imageName = imagesToSend[0].name;
    } else {
      messageObj.images = imagesToSend.map((img) => ({
        preview: img.preview,
        name: img.name,
        path: img.path,
      }));
    }
  }

  messageObj.text = displayText;
  messageObj.originalText = savedInput; // 保存原始输入
  messageObj.originalImages = savedImages; // 保存原始图片

  const messageIndex = messages.value.length;
  messages.value.push(messageObj);

  // 清空输入
  userInput.value = '';
  clearAllImages();
  imageError.value = '';
  isSending.value = true;

  nextTick(() => {
    const chatHistory = chatHistoryRef.value;
    if (chatHistory) {
      chatHistory.scrollTop = chatHistory.scrollHeight;
    }
  });

  const extra = { session_id: sessionId.value };
  // 确保 session_id 在发送时存在
  ensureSessionId();
  extra.session_id = sessionId.value;
  if (imagesToSend.length > 0) {
    extra.images = imagesToSend.map((img) => ({
      name: img.name,
      preview: img.preview,
      type: img.type,
      path: img.path,
    }));
  }

  // 设置超时
  sendTimeout.value = setTimeout(() => {
    if (messages.value[messageIndex]?.status === 'sending') {
      messages.value[messageIndex].status = 'failed';
      messages.value[messageIndex].error = '发送超时';
      isSending.value = false;
      messages.value.push({
        sender: '系统',
        text: '消息发送超时，请检查网络连接或重试。',
        status: 'error',
      });
    }
  }, MESSAGE_TIMEOUT);

  try {
    await SendMessageToAI(text, extra);
    // WebChannel 是单向的，我们假设发送成功
    // 实际的成功会在 receiveAIMessage / receiveAIMessageChunk 中确认
    messages.value[messageIndex].status = 'sent';
  } catch (error) {
    logError('发送消息失败', error);
    messages.value[messageIndex].status = 'failed';
    messages.value[messageIndex].error = error.message || '发送失败';

    // 显示错误提示
    messages.value.push({
      sender: '系统',
      text: `消息发送失败: ${error.message || '未知错误'}`,
      status: 'error',
    });
  } finally {
    if (sendTimeout.value) {
      clearTimeout(sendTimeout.value);
      sendTimeout.value = null;
    }
    isSending.value = false;
  }
};

// 重试发送失败的消息
const retryMessage = async (index) => {
  const message = messages.value[index];
  if (!message || message.status !== 'failed') return;

  // 恢复输入
  userInput.value = message.originalText || '';

  // 恢复图片
  if (message.originalImages && message.originalImages.length > 0) {
    message.originalImages.forEach((img) => {
      if (img.type && imageTypes.includes(img.type)) {
        pendingImages.value[img.type] = img;
      }
    });
  }

  // 删除失败的消息
  messages.value.splice(index, 1);
};

// 将 file:// URL 转换为 data URL
const convertFileUrlToDataUrl = async (fileUrl) => {
  if (!fileUrl || !fileUrl.startsWith('file://')) {
    return fileUrl;
  }

  try {
    const dataUrl = await aiService.readLocalFileAsBase64(fileUrl);
    return dataUrl || fileUrl; // 如果转换失败，返回原URL
  } catch (error) {
    logError('转换文件URL失败', error);
    return fileUrl;
  }
};

// 流式消息接收处理
// 流式消息接收处理：同一轮 QA 的所有 chunk 追加到同一条气泡
window.receiveAIMessageChunk = async (data) => {
  let streamRequestId = null;
  try {
    const message = parseIncomingAIMessage(data);

    if (message.session_id) {
      sessionId.value = message.session_id;
    }
    streamRequestId = message.metadata?.request_id || currentStreamingRequestId.value;
    if (streamRequestId) {
      currentStreamingRequestId.value = streamRequestId;
    }

    // 收到第一个流式块时，将用户消息标记为成功并清空旧定时器
    if (getStreamingMessageIndex(streamRequestId) === null) {
      const lastUserMessage = messages.value
        .slice()
        .reverse()
        .find((m) => m.sender === 'User');
      if (
        lastUserMessage &&
        (lastUserMessage.status === 'sending' || lastUserMessage.status === 'sent')
      ) {
        lastUserMessage.status = 'success';
      }
      clearStreamingTimer(streamRequestId);
    }

    const messageError = getAIMessageError(message);
    if (messageError) {
      logError('AI处理错误', messageError);
      const lastUserMessage = messages.value
        .slice()
        .reverse()
        .find((m) => m.sender === 'User');
      if (lastUserMessage) {
        lastUserMessage.status = 'failed';
        lastUserMessage.error = messageError;
      }
      markStreamingMessageStatus(streamRequestId, 'failed');
      clearStreamingState(streamRequestId);
      return;
    }

    // 收到流结束信号：立即完成气泡
    if (message.metadata?.stream_done) {
      markStreamingMessageStatus(streamRequestId, 'success');
      clearStreamingState(streamRequestId);
      return;
    }

    // 收到心跳信号：重置断连计时器；若为节点边界则结束当前气泡等待态
    if (message.metadata?.heartbeat) {
      if (message.metadata?.workflow_node_boundary) {
        markStreamingMessageStatus(streamRequestId, 'success');
        clearStreamingState(streamRequestId);
      }
      resetStreamCompletionTimer(streamRequestId);
      return;
    }

    // 收到内容数据：重置断连计时器
    clearStreamingTimer(streamRequestId);

    if (!Array.isArray(message.llm_content)) {
      if (message.content) {
        messages.value.push({
          sender: 'AI',
          parts: [{ type: 'text', text: message.content, format: 'auto' }],
          status: 'success',
        });
      }
      return;
    }

    // 处理流式内容：将 parts 追加到当前气泡（或新建气泡）
    for (const content of message.llm_content) {
      if (content.role !== 'assistant') continue;

      const checkpointSignature = extractCheckpointSignature(content);
      if (checkpointSignature && getStreamingCheckpoint(streamRequestId) !== checkpointSignature) {
        markStreamingMessageStatus(streamRequestId, 'success');
        if (streamRequestId) {
          delete streamingMessagesByRequestId.value[streamRequestId];
        }
        currentStreamingMessage.value = null;
        setStreamingCheckpoint(streamRequestId, checkpointSignature);
      }

      // 取出/创建当前气泡
      const existingIndex = getStreamingMessageIndex(streamRequestId);
      let existingMsg = existingIndex !== null ? messages.value[existingIndex] : null;

      if (existingMsg == null) {
        // 第一个 chunk：新建气泡
        existingMsg = {
          sender: 'AI',
          requestId: message.metadata?.request_id || currentStreamingRequestId.value,
          parts: [],
          status: 'streaming',
        };
        messages.value.push(existingMsg);
        setStreamingMessageIndex(streamRequestId, messages.value.length - 1);
        if (!checkpointSignature) {
          setStreamingCheckpoint(streamRequestId, null);
        }
      }

      if (content.part && Array.isArray(content.part)) {
        for (const part of content.part) {
          if (part.content_type === 'text') {
            const newText = part.content_text || '';
            const format = getTextPartFormat(part);
            // 连续文本 chunk 合并到最后一个 text part，避免多余分段
            const last = existingMsg.parts[existingMsg.parts.length - 1];
            if (last && last.type === 'text' && (last.format || 'auto') === format) {
              last.text = last.text ? last.text + '\n' + newText : newText;
            } else {
              existingMsg.parts.push({ type: 'text', text: newText, format });
            }
          } else if (part.content_type === 'image') {
            existingMsg.parts.push({ type: 'image', url: part.content_url, name: 'image' });
          } else if (part.content_type === 'video') {
            const videoUrl = await convertFileUrlToDataUrl(part.content_url);
            existingMsg.parts.push({ type: 'video', url: videoUrl, name: 'video' });
          } else if (part.content_type === 'audio') {
            const audioUrl = await convertFileUrlToDataUrl(part.content_url);
            existingMsg.parts.push({ type: 'audio', url: audioUrl, name: 'audio' });
          } else if (
            part.content_type === 'review' &&
            part.parameter?.review?.stage === 'pending'
          ) {
            // 收到审核块：初始化审核状态，渲染审核面板
            initReviewFromPayload(part.parameter.review);
            existingMsg.parts.push({
              type: 'review',
              text: part.content_text || '请确认以下设计方案',
              review: part.parameter.review,
            });
          }
        }
      }
    }

    // 断连检测计时器：15秒无任何数据/心跳则标记失败
    resetStreamCompletionTimer(streamRequestId);

    // 滚动到底部
    nextTick(() => {
      const chatHistory = chatHistoryRef.value;
      if (chatHistory) {
        chatHistory.scrollTop = chatHistory.scrollHeight;
      }
    });
  } catch (e) {
    logError('处理AI流式消息失败', e);
    markStreamingMessageStatus(streamRequestId, 'failed');
    clearStreamingState(streamRequestId);
  }
};

window.receiveAIMessage = async (data) => {
  try {
    const message = parseIncomingAIMessage(data);

    if (message.session_id) {
      sessionId.value = message.session_id;
    }

    // 收到 AI 回复时，将最后一条"发送中"的用户消息标记为成功
    const lastUserMessage = messages.value
      .slice()
      .reverse()
      .find((m) => m.sender === 'User');
    if (
      lastUserMessage &&
      (lastUserMessage.status === 'sending' || lastUserMessage.status === 'sent')
    ) {
      lastUserMessage.status = 'success';
    }

    const messageError = getAIMessageError(message);
    if (messageError) {
      logError('AI处理错误', messageError);
      // 将用户消息标记为失败
      if (lastUserMessage) {
        lastUserMessage.status = 'failed';
        lastUserMessage.error = messageError;
      }
      return;
    }

    // 解析 llm_content 显示消息
    if (message.llm_content && Array.isArray(message.llm_content)) {
      for (const content of message.llm_content) {
        if (content.role === 'assistant') {
          const parts = [];

          if (content.part && Array.isArray(content.part)) {
            for (const part of content.part) {
              if (part.content_type === 'text') {
                const text = (part.content_text || '').trim();
                if (text) parts.push({ type: 'text', text, format: getTextPartFormat(part) });
              } else if (part.content_type === 'image') {
                parts.push({ type: 'image', url: part.content_url, name: 'image' });
              } else if (part.content_type === 'video') {
                const videoUrl = await convertFileUrlToDataUrl(part.content_url);
                parts.push({ type: 'video', url: videoUrl, name: 'video' });
              } else if (part.content_type === 'audio') {
                const audioUrl = await convertFileUrlToDataUrl(part.content_url);
                parts.push({ type: 'audio', url: audioUrl, name: 'audio' });
              } else if (
                part.content_type === 'review' &&
                part.parameter?.review?.stage === 'pending'
              ) {
                initReviewFromPayload(part.parameter.review);
                parts.push({
                  type: 'review',
                  text: part.content_text || '请确认以下设计方案',
                  review: part.parameter.review,
                });
              }
            }
          }

          if (parts.length === 0) continue; // 忽略空消息

          messages.value.push({ sender: 'AI', parts, status: 'success' });
        }
      }
    } else {
      // 兼容旧格式或 fallback
      const msgObj = {
        sender: 'AI',
        text: message.content || JSON.stringify(message),
        richTextFormat: 'auto',
        status: 'success',
      };
      messages.value.push(msgObj);
    }

    // 滚动到底部
    nextTick(() => {
      const chatHistory = chatHistoryRef.value;
      if (chatHistory) {
        chatHistory.scrollTop = chatHistory.scrollHeight;
      }
    });
  } catch (e) {
    logError('处理AI消息失败', e);
    messages.value.push({
      sender: '系统',
      text: `无法处理AI响应: ${typeof data === 'string' ? data : JSON.stringify(data)}`,
      status: 'error',
    });
  }
};

const closeFloat = async () => {
  if (closeDockPanel) { closeDockPanel(); return; }
  try {
    await appService.removeDockWidgetByRoute('/AITalkBar');
  } catch (e) {
    logError('关闭 AITalkBar 失败', e);
  }
};

// 事件总线 handler 引用（用于精准卸载）
const onAiChunk = (payload) => {
  if (window.receiveAIMessageChunk) window.receiveAIMessageChunk(payload);
};

onMounted(async () => {
  document.addEventListener('click', handleGlobalClick, true);
  coronaEventBus.on('ai-chunk', onAiChunk);
});

function handleGlobalClick(e) {
  // 如果点击不在提示词区域且不是按钮
  if (!showPrompts.value) return;
  const pop = document.querySelector('.prompt-popover-flag');
  if (pop && !pop.contains(e.target)) {
    // 通过 ref/ class 控制更精准，这里简单判断
    // 但我们已添加捕获监听, 若为按钮也会触发, 用 closest 判断
    const target = e.target;
    if (!target.closest || !target.closest('.prompt-popover-exclude')) {
      hidePrompts();
    }
  }
}

onUnmounted(() => {
  coronaEventBus.off('ai-chunk', onAiChunk);
  document.removeEventListener('click', handleGlobalClick, true);

  if (sendTimeout.value) {
    clearTimeout(sendTimeout.value);
    sendTimeout.value = null;
  }

  if (streamCompletionTimer.value) {
    clearTimeout(streamCompletionTimer.value);
    streamCompletionTimer.value = null;
  }
});
</script>

<style scoped>
/* 可选过渡 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
