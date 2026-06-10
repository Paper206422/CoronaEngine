<template>
  <div class="relative flex-1 min-h-0 w-full" tabindex="0">
    <!-- 顶部菜单栏 -->
    <div
      class="w-full bg-[#2d2d2d] text-gray-200 border-b border-gray-700 h-10 flex items-center px-4 space-x-6 text-sm shadow-md"
    >
      <!-- 项目菜单 -->
      <div class="relative">
        <button
          class="hover:bg-[#3d3d3d] px-3 py-1.5 rounded transition-colors duration-200"
          :class="{ 'bg-[#3d3d3d]': activeMenu === 'project' }"
          @click="toggleMenu('project')"
        >
          项目
        </button>
        <div
          v-if="activeMenu === 'project'"
          class="absolute top-full left-0 mt-1 w-48 bg-[#2d2d2d] border border-gray-700 rounded shadow-lg z-50"
        >
          <div class="py-1">
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleNewProject"
            >
              新建项目
            </a>
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleOpenProject"
            >
              打开项目
            </a>
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleProjectSettings"
            >
              项目设置
            </a>
            <hr class="border-gray-700 my-1" />
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleSaveProject"
            >
              保存项目
            </a>
          </div>
        </div>
      </div>

      <!-- 视图菜单 - 修改为动态渲染 -->
      <div class="relative">
        <button
          class="hover:bg-[#3d3d3d] px-3 py-1.5 rounded transition-colors duration-200"
          :class="{ 'bg-[#3d3d3d]': activeMenu === 'view' }"
          @click="toggleMenu('view')"
        >
          视图
        </button>
        <div
          v-if="activeMenu === 'view'"
          class="absolute top-full left-0 mt-1 w-56 bg-[#2d2d2d] border border-gray-700 rounded shadow-lg z-50"
        >
          <div class="py-1">
            <a
              v-for="tool in viewStates"
              :key="tool.id"
              href="#"
              class="flex items-center justify-between px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="toggleViewTool(tool)"
            >
              <span>{{ tool.name }}</span>
              <span class="text-sm" :class="tool.open ? 'text-green-400' : 'text-red-400'">
                {{ tool.open ? '√' : '×' }}
              </span>
            </a>
          </div>
        </div>
      </div>

      <!-- 物理参数菜单 -->
      <div class="relative">
        <button
          class="hover:bg-[#3d3d3d] px-3 py-1.5 rounded transition-colors duration-200"
          :class="{ 'bg-[#3d3d3d]': activeMenu === 'physics' }"
          @click="toggleMenu('physics')"
        >
          物理
        </button>
        <div
          v-if="activeMenu === 'physics'"
          class="absolute top-full left-0 mt-1 w-72 bg-[#2d2d2d] border border-gray-700 rounded shadow-lg z-50 p-3 space-y-3"
          @click.stop
        >
          <!-- 重力 -->
          <div>
            <label class="block text-xs text-gray-400 mb-1">重力 (X, Y, Z)</label>
            <div class="flex gap-1">
              <input
                v-model.number="physicsParams.gravityX"
                type="number"
                step="0.1"
                class="w-1/3 bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-xs text-white"
                placeholder="X"
              />
              <input
                v-model.number="physicsParams.gravityY"
                type="number"
                step="0.1"
                class="w-1/3 bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-xs text-white"
                placeholder="Y"
              />
              <input
                v-model.number="physicsParams.gravityZ"
                type="number"
                step="0.1"
                class="w-1/3 bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-xs text-white"
                placeholder="Z"
              />
            </div>
          </div>
          <!-- 地面高度 -->
          <div>
            <label class="block text-xs text-gray-400 mb-1">地面高度 (Floor Y)</label>
            <input
              v-model.number="physicsParams.floorY"
              type="number"
              step="0.1"
              class="w-full bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-xs text-white"
            />
          </div>
          <!-- 地面弹性 -->
          <div>
            <label class="block text-xs text-gray-400 mb-1">地面弹性系数</label>
            <input
              v-model.number="physicsParams.floorRestitution"
              type="number"
              step="0.05"
              min="0"
              max="1"
              class="w-full bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-xs text-white"
            />
          </div>
          <!-- 时间步长 -->
          <div>
            <label class="block text-xs text-gray-400 mb-1">物理步长 (秒)</label>
            <input
              v-model.number="physicsParams.fixedDt"
              type="number"
              step="0.001"
              min="0.001"
              class="w-full bg-[#1e1e1e] border border-gray-600 rounded px-2 py-1 text-xs text-white"
            />
          </div>
          <!-- 应用按钮 -->
          <button
            class="w-full bg-[#84a65b] hover:bg-[#6b8a48] text-white text-xs py-1.5 rounded transition-colors duration-200"
            @click="handleApplyPhysics"
          >
            应用物理参数
          </button>
        </div>
      </div>

      <!-- 插件菜单 - 修改为动态渲染 -->
      <div class="relative">
        <button
          class="hover:bg-[#3d3d3d] px-3 py-1.5 rounded transition-colors duration-200"
          :class="{ 'bg-[#3d3d3d]': activeMenu === 'plugin' }"
          @click="toggleMenu('plugin')"
        >
          插件
        </button>
        <div
          v-if="activeMenu === 'plugin'"
          class="absolute top-full left-0 mt-1 w-48 bg-[#2d2d2d] border border-gray-700 rounded shadow-lg z-50"
        >
          <div class="py-1">
            <a
              v-for="plugin in pluginStates"
              :key="plugin.id"
              href="#"
              class="flex items-center justify-between px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="toggleViewTool(plugin)"
            >
              <span>{{ plugin.name }}</span>
              <span class="text-sm" :class="plugin.open ? 'text-green-400' : 'text-red-400'">
                {{ plugin.open ? '√' : '×' }}
              </span>
            </a>
          </div>
        </div>
      </div>

      <!-- 运行菜单 -->
      <div class="relative">
        <button
          class="hover:bg-[#3d3d3d] px-3 py-1.5 rounded transition-colors duration-200"
          :class="{ 'bg-[#3d3d3d]': activeMenu === 'run' }"
          @click="toggleMenu('run')"
        >
          运行
        </button>
        <div
          v-if="activeMenu === 'run'"
          class="absolute top-full left-0 mt-1 w-48 bg-[#2d2d2d] border border-gray-700 rounded shadow-lg z-50"
        >
          <div class="py-1">
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleRunProject"
            >
              运行项目
            </a>
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleRunCurrentScene"
            >
              运行当前场景
            </a>
          </div>
        </div>
      </div>

      <!-- 帮助菜单 -->
      <div class="relative">
        <button
          class="hover:bg-[#3d3d3d] px-3 py-1.5 rounded transition-colors duration-200"
          :class="{ 'bg-[#3d3d3d]': activeMenu === 'help' }"
          @click="toggleMenu('help')"
        >
          帮助
        </button>
        <div
          v-if="activeMenu === 'help'"
          class="absolute top-full left-0 mt-1 w-48 bg-[#2d2d2d] border border-gray-700 rounded shadow-lg z-50"
        >
          <div class="py-1">
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleHelpDocs"
            >
              帮助文档
            </a>
            <a
              href="#"
              class="block px-4 py-2 hover:bg-[#3d3d3d] transition-colors duration-200"
              @click.prevent="handleAbout"
            >
              关于
            </a>
          </div>
        </div>
      </div>

      <div class="ml-auto flex items-center gap-2">
        <button
          class="px-2.5 py-1 rounded border transition-colors duration-200 whitespace-nowrap"
          :class="previewRunning || previewBusy
            ? 'border-gray-600 text-gray-500 bg-[#252525] cursor-not-allowed'
            : 'border-green-500/50 text-green-200 bg-green-700/20 hover:bg-green-600/30'"
          :disabled="previewRunning || previewBusy"
          title="开始项目预览"
          @click="handleStartGamePreview"
        >
          开始预览
        </button>
        <button
          class="px-2.5 py-1 rounded border transition-colors duration-200 whitespace-nowrap"
          :class="!previewRunning || previewBusy
            ? 'border-gray-600 text-gray-500 bg-[#252525] cursor-not-allowed'
            : 'border-red-500/50 text-red-200 bg-red-700/20 hover:bg-red-600/30'"
          :disabled="!previewRunning || previewBusy"
          title="结束项目预览"
          @click="handleStopGamePreview"
        >
          结束预览
        </button>
        <span v-if="previewStatusText" class="text-xs text-[#b8c7b0] whitespace-nowrap">
          {{ previewStatusText }}
        </span>
      </div>
    </div>

    <!-- 场景栏 -->
    <div
      class="w-full bg-gradient-to-r from-teal-700 to-green-600 border-b border-teal-800/60 h-13 relative shadow-md flex items-center"
    >
      <div
        class="flex items-center space-x-1 px-3 overflow-x-auto scroll-smooth tab-container flex-1"
      >
        <div
          v-for="(tab, index) in tabs"
          :key="index"
          class="px-5 py-2.5 cursor-pointer rounded-t-lg flex items-center gap-2 transition-all duration-200 ease-in-out"
          :class="{
            'bg-white/90 border-b-2 border-teal-500 shadow-sm': activeTab === index,
            'hover:bg-white/20 text-white/90': activeTab !== index,
            'text-gray-800': activeTab === index,
          }"
          @click="switchTab(index, false)"
        >
          <span class="max-w-[140px] truncate px-2 py-1 select-none font-medium">
            {{ tab.name }}
          </span>

          <button
            v-if="tabs.length > 1"
            class="hover:bg-gray-300/50 rounded-full p-1 transition-colors duration-200 hover:text-red-500"
            aria-label="关闭标签"
            @click.stop="closeTab(index)"
          >
            ×
          </button>
        </div>
        <!-- 新建场景按钮 -->
        <button
          class="ml-1 w-7 h-7 flex items-center justify-center rounded-full text-white/80 hover:bg-white/20 hover:text-white transition-colors duration-200 shrink-0 text-lg leading-none"
          aria-label="新建场景"
          title="新建场景"
          @click.stop="addNewTab"
        >
          +
        </button>
      </div>
      <!-- 摄像头速度调节 -->
      <div class="flex items-center gap-2 px-3 shrink-0 select-none">
        <span class="text-white/80 text-xs whitespace-nowrap">速度</span>
        <input
          v-model.number="cameraSpeed"
          type="range"
          :min="0.01"
          :max="2"
          :step="0.01"
          class="w-20 h-1 accent-white cursor-pointer"
          title="摄像头移动速度（Shift+滚轮调节）"
        />
        <span class="text-white/80 text-xs w-8 text-right">{{ cameraSpeed.toFixed(2) }}</span>
      </div>
    </div>
    <!-- 自定义弹窗 -->
    <div
      v-if="showDialog"
      class="fixed top-0 left-0 w-full h-full flex items-center justify-center bg-black/50 backdrop-blur-sm transition-opacity duration-300"
    >
      <div
        class="bg-white rounded-lg shadow-xl w-96 transform transition-all duration-300 ease-out scale-100"
      >
        <div class="p-6">
          <div>
            <label for="new-tab-name" class="block text-sm font-medium text-gray-700 mb-2">
              添加场景
            </label>
            <input
              id="new-tab-name"
              ref="nameInput"
              v-model="inputState.newTabName"
              type="text"
              class="mt-1 px-3 py-2 bg-gray-50 border border-gray-300 rounded-md w-full focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-colors duration-200 outline-none"
              autofocus
              placeholder="输入场景名称"
              @keyup.enter="confirmAddTab"
            />
          </div>
          <div class="flex justify-end gap-3 mt-5">
            <button
              class="px-4 py-2 text-gray-600 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors duration-200 focus:ring-2 focus:ring-teal-500 focus:ring-offset-2"
              @click="cancelAddTab"
            >
              取消
            </button>
            <button
              class="px-4 py-2 text-white bg-teal-600 rounded-md hover:bg-teal-700 transition-colors duration-200 shadow-sm hover:shadow-md focus:ring-2 focus:ring-teal-500 focus:ring-offset-2"
              @click="confirmAddTab"
            >
              创建场景
            </button>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="showLocalModal"
      class="fixed inset-0 bg-black/70 flex items-center justify-center z-[9999]"
    >
      <div class="bg-[#2a2a2a] rounded-lg p-6 min-w-[300px] border border-[#84a65b]/30 shadow-2xl">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-6 h-6 animate-spin">
            <svg
              class="w-full h-full text-[#84a65b]"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              ></path>
            </svg>
          </div>
          <span class="text-[#e0e0e0] font-medium">{{ localModalTitle }}</span>
        </div>
        <div class="text-sm text-[#909090] mb-2">{{ localModalMessage }}</div>
        <div v-if="localModalProgress > 0" class="w-full bg-[#1a1a1a] rounded-full h-2 mt-4">
          <div
            class="bg-[#84a65b] h-full rounded-full transition-all duration-300"
            :style="{ width: localModalProgress + '%' }"
          ></div>
        </div>
        <div v-if="localModalProgress > 0" class="text-xs text-[#84a65b] text-center mt-2">
          {{ Math.round(localModalProgress) }}%
        </div>
      </div>
    </div>

    <div
      class="fixed right-5 top-28 z-[80] h-24 w-24 pointer-events-none select-none rounded-md border border-white/10 bg-[#101418]/70 shadow-xl backdrop-blur-sm"
      aria-hidden="true"
    >
      <svg class="h-full w-full" viewBox="0 0 90 90">
        <circle cx="45" cy="45" r="3" fill="#dbeafe" opacity="0.85" />
        <g v-for="axis in sceneAxisVectors" :key="axis.name">
          <line
            x1="45"
            y1="45"
            :x2="axis.x"
            :y2="axis.y"
            :stroke="axis.color"
            :stroke-width="axis.width"
            stroke-linecap="round"
            :opacity="axis.opacity"
          />
          <circle :cx="axis.x" :cy="axis.y" r="4" :fill="axis.color" :opacity="axis.opacity" />
          <text
            :x="axis.labelX"
            :y="axis.labelY"
            text-anchor="middle"
            dominant-baseline="middle"
            class="fill-white text-[10px] font-semibold"
            :opacity="axis.opacity"
          >
            {{ axis.name }}
          </text>
        </g>
      </svg>
    </div>

    <!-- 包菜自动提示气泡：每隔一段时间弹出，时长由 cabbage_hint_time 控制 -->
    <AIHintBubble
      :show="cabbageBubbleShow"
      :hintText="cabbageBubbleText"
      :loading="cabbageBubbleLoading"
      :autoHideMs="cabbageHintTime * 1000"
      @close="onCabbageBubbleClose"
    />
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, reactive, watch, nextTick } from 'vue';
import { useRouter } from 'vue-router';
import { DEFAULT_SCENE_NAME } from '@/utils/constants.js';
import { Bridge, appService, sceneService, projectService, scriptingService } from '@/utils/bridge.js';
import { useErrorHandler } from '@/composables/useErrorHandler.js';
import { useDockStore } from '@/stores/dockStore.js';
import { PLUGIN_MANIFEST } from '@/config/pluginManifest.js';
import { coronaEventBus } from '@/utils/eventBus.js';
import AIHintBubble from '@/components/ui/AIHintBubble.vue';
import { startStageHints, stopStageHints, setHintShowMs } from '@/services/aiHintGenerator.js';

const { error: logError } = useErrorHandler('MainPage');

const router = useRouter();
const dockStore = useDockStore();

const goToHome = () => {
  router.push('/');
};

const showLocalModal = ref(false);
const localModalTitle = ref('');
const localModalMessage = ref('');
const localModalProgress = ref(0);

const activeTab = ref(0); // 当前激活的标签页

const cameraState = ref({
  position: [0.0, 5.0, 10.0],
  forward: [0.0, 1.5, 0.0],
  up: [0.0, 1.0, 0.0],
  fov: 45.0,
});

const cameraBindingState = ref({
  sceneId: DEFAULT_SCENE_NAME,
  cameraName: null,
  cameraHandle: null,
});

// 摄像头移动速度（可调节）
const cameraSpeed = ref(0.2);
const mouseSensitivity = ref(0.15);

// 鼠标旋转状态
const mouseRotate = reactive({
  active: false,
  lastX: 0,
  lastY: 0,
});

const hasActiveMovementKeys = () => Object.values(movementKeys).some((value) => value);

const isRealtimeCameraInputActive = () => mouseRotate.active || hasActiveMovementKeys();

// 摄像头更新节流：用 rAF 合并高频输入，每帧最多发送一次
let cameraDirty = false;
let cameraRafId = null;

const scheduleCameraUpdate = () => {
  cameraDirty = true;
  if (cameraRafId != null) return;
  cameraRafId = requestAnimationFrame(() => {
    cameraRafId = null;
    if (cameraDirty) {
      cameraDirty = false;
      if (!sendCameraUpdateFast()) {
        const sceneId = tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME;
        syncSceneCameraBinding(sceneId);
      }
    }
  });
};

// 标签页数据
const tabs = ref([]);

// 添加新标签页
const showDialog = ref(false);
const inputState = reactive({
  newTabName: '',
});

// 新增：菜单状态
const activeMenu = ref(null);
const previewRunning = ref(false);
const previewBusy = ref(false);
const previewStatusText = ref('');
let previewPollTimer = null;

// 物理参数状态
const physicsParams = ref({
  gravityX: 0.0,
  gravityY: -9.8,
  gravityZ: 0.0,
  floorY: 0.0,
  floorRestitution: 0.6,
  fixedDt: 1.0 / 60.0,
});

// 视图/插件菜单状态：从 Pinia dockStore + pluginManifest 派生
const viewStates = computed(() =>
  PLUGIN_MANIFEST.filter((p) => p.pageType === 'view').map((p) => ({
    id: p.id,
    name: p.displayName,
    open: dockStore.panels[p.id]?.open ?? false,
  }))
);
const pluginStates = computed(() =>
  PLUGIN_MANIFEST.filter((p) => p.pageType === 'plugin').map((p) => ({
    id: p.id,
    name: p.displayName,
    open: dockStore.panels[p.id]?.open ?? false,
  }))
);

// ── 包菜提示气泡状态 ──
const STORAGE_KEY = 'corona_editor_settings';
const cabbageBubbleShow = ref(false);
const cabbageBubbleText = ref('');
const cabbageBubbleLoading = ref(false);
const cabbageHintTime = ref(3.0); // 默认 3 秒，从设置中读取

function readCabbageHintTime() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (typeof parsed.cabbage_hint_time === 'number' && parsed.cabbage_hint_time > 0) {
        cabbageHintTime.value = parsed.cabbage_hint_time;
      }
    }
  } catch (_) { /* keep default */ }
}

function onCabbageBubbleClose() {
  cabbageBubbleShow.value = false;
}

// 新增：加载状态
const isLoadingMenu = ref(false);

watch(showDialog, (newVal) => {
  if (newVal) {
    nextTick(() => {
      const input = document.getElementById('new-tab-name');
      if (input) {
        input.select();
      }
    });
  }
});

// 新增：切换菜单显示
const toggleMenu = (menu) => {
  if (activeMenu.value === menu) {
    activeMenu.value = null;
  } else {
    activeMenu.value = menu;
    if (menu === 'physics') {
      loadPhysicsParams();
    }
  }
};

// 新增：点击其他地方关闭菜单
const handleClickOutside = (event) => {
  const menuBar = document.querySelector('.bg-\\[\\#2d2d2d\\]');
  if (menuBar && !menuBar.contains(event.target)) {
    activeMenu.value = null;
  }
};

const addNewTab = async () => {
  const sceneNumbers = tabs.value
    .map((tab) => {
      const match = tab.name.match(/^场景(\d+)$/);
      return match ? parseInt(match[1]) : null;
    })
    .filter((num) => num !== null);

  const maxSceneNumber = sceneNumbers.length > 0 ? Math.max(...sceneNumbers) : 0;

  inputState.newTabName = `场景${maxSceneNumber + 1}`;
  showDialog.value = true;
};

const confirmAddTab = async () => {
  if (inputState.newTabName.trim()) {
    const finalName = inputState.newTabName.trim();

    try {
      // 先在项目文件夹中创建 .scene 文件，再初始化引擎场景
      const result = await projectService.createNewScene(finalName);
      const scenePath = result?.data?.path ?? result?.path;
      const sceneName = result?.data?.name ?? result?.name ?? finalName;

      if (!scenePath) {
        logError('创建场景文件失败：未返回路径');
        return;
      }

      // 添加新标签页（使用文件路径作为 id）
      tabs.value.push({
        name: sceneName,
        id: scenePath,
      });

      await switchTab(tabs.value.length - 1, false);
      showDialog.value = false;
      inputState.newTabName = '';
    } catch (e) {
      logError('创建场景失败', e);
    }
  } else {
    alert('请输入标签名称');
  }
};

// 清空输入框
const cancelAddTab = () => {
  showDialog.value = false;
  inputState.newTabName = '';
};

const isVector3 = (value) => Array.isArray(value) && value.length === 3;

const applySceneSnapshot = (sceneId, payload) => {
  const snapshot = payload?.scene ?? payload?.data?.scene ?? payload?.data ?? payload;
  if (!snapshot || typeof snapshot !== 'object') {
    cameraBindingState.value = {
      ...cameraBindingState.value,
      sceneId: sceneId ?? cameraBindingState.value.sceneId,
    };
    return;
  }

  const normalizedSceneId =
    snapshot.scene_id ?? snapshot.sceneId ?? snapshot.id ?? sceneId ?? DEFAULT_SCENE_NAME;
  const cameras = Array.isArray(snapshot.cameras) ? snapshot.cameras : [];
  const activeCameraName =
    snapshot.active_camera_name ?? snapshot.activeCameraName ?? cameras[0]?.name ?? null;
  const activeCamera =
    cameras.find((cam) => cam?.name === activeCameraName) ?? cameras[0] ?? snapshot.camera ?? null;

  cameraBindingState.value = {
    sceneId: normalizedSceneId,
    cameraName: activeCameraName,
    cameraHandle: activeCamera?.handle ?? activeCamera?.camera_handle ?? null,
  };

  if (
    activeCamera &&
    (isVector3(activeCamera.position) ||
      isVector3(activeCamera.forward) ||
      isVector3(activeCamera.world_up))
  ) {
    cameraState.value = {
      position: isVector3(activeCamera.position)
        ? [...activeCamera.position]
        : [...cameraState.value.position],
      forward: isVector3(activeCamera.forward)
        ? [...activeCamera.forward]
        : [...cameraState.value.forward],
      up: isVector3(activeCamera.world_up) ? [...activeCamera.world_up] : [...cameraState.value.up],
      fov: Number.isFinite(Number(activeCamera.fov))
        ? Number(activeCamera.fov)
        : cameraState.value.fov,
    };
  }
};

const syncSceneCameraBinding = async (sceneId) => {
  if (!sceneId) {
    return;
  }

  try {
    const result = await sceneService.getScene(sceneId);
    applySceneSnapshot(sceneId, result);
  } catch (e) {
    logError('Failed to sync scene camera binding', e);
  }
};

const handleWheel = (event) => {
  if (event.shiftKey) {
    // Shift+滚轮：调节摄像头速度
    const delta = event.deltaY > 0 ? -0.02 : 0.02;
    cameraSpeed.value =
      Math.round(Math.max(0.01, Math.min(2, cameraSpeed.value + delta)) * 100) / 100;
    event.preventDefault();
    return;
  }
  const direction = event.deltaY > 0 ? 'backward' : 'forward';
  handleCameraMove(direction);
};

const handleKeyDown = (event) => {
  // 检查输入框是否聚焦
  const inputElement = document.getElementById('new-tab-name');
  if (inputElement && inputElement === document.activeElement) {
    return;
  }
  const tag = event.target?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

  const key = event.key.toLowerCase();
  if (movementKeys[key] !== undefined) {
    event.preventDefault();
    movementKeys[key] = true;
    startMoveLoop();
  }
};

const handleKeyUp = (event) => {
  const key = event.key.toLowerCase();
  if (movementKeys[key] !== undefined) {
    movementKeys[key] = false;
    if (!hasActiveMovementKeys()) {
      stopMoveLoop();
      scheduleCameraUpdate();
    }
  }
};

// ---- 平滑移动系统 ----
const movementKeys = reactive({
  w: false,
  s: false,
  a: false,
  d: false,
  q: false,
  e: false,
  arrowleft: false,
  arrowright: false,
  arrowup: false,
  arrowdown: false,
});
let moveLoopId = null;
let lastMoveTime = 0;

const startMoveLoop = () => {
  if (moveLoopId !== null) return;
  lastMoveTime = performance.now();
  moveLoopId = requestAnimationFrame(moveLoop);
};

const stopMoveLoop = () => {
  if (moveLoopId !== null) {
    cancelAnimationFrame(moveLoopId);
    moveLoopId = null;
  }
};

const moveLoop = (now) => {
  const dt = Math.min((now - lastMoveTime) / 1000, 0.1); // 秒，上限 0.1s
  lastMoveTime = now;

  const anyActive = hasActiveMovementKeys();
  if (!anyActive) {
    moveLoopId = null;
    return;
  }

  const speed = cameraSpeed.value * 60 * dt; // 归一化到帧率无关
  const rotSpeed = 2.0 * 60 * dt;
  const { position, forward, up } = cameraState.value;
  const fwd = vec3.normalize(forward);
  const worldUp = vec3.normalize(up);
  const right = vec3.normalize(vec3.cross(worldUp, fwd));
  let moved = false;

  if (movementKeys.w) {
    position[0] += fwd[0] * speed;
    position[1] += fwd[1] * speed;
    position[2] += fwd[2] * speed;
    moved = true;
  }
  if (movementKeys.s) {
    position[0] -= fwd[0] * speed;
    position[1] -= fwd[1] * speed;
    position[2] -= fwd[2] * speed;
    moved = true;
  }
  if (movementKeys.a) {
    position[0] -= right[0] * speed;
    position[1] -= right[1] * speed;
    position[2] -= right[2] * speed;
    moved = true;
  }
  if (movementKeys.d) {
    position[0] += right[0] * speed;
    position[1] += right[1] * speed;
    position[2] += right[2] * speed;
    moved = true;
  }
  if (movementKeys.q) {
    position[0] += worldUp[0] * speed;
    position[1] += worldUp[1] * speed;
    position[2] += worldUp[2] * speed;
    moved = true;
  }
  if (movementKeys.e) {
    position[0] -= worldUp[0] * speed;
    position[1] -= worldUp[1] * speed;
    position[2] -= worldUp[2] * speed;
    moved = true;
  }

  if (movementKeys.arrowleft) {
    rotateCameraView('rotateLeft', rotSpeed);
    moved = true;
  }
  if (movementKeys.arrowright) {
    rotateCameraView('rotateRight', rotSpeed);
    moved = true;
  }
  if (movementKeys.arrowup) {
    rotateCameraView('rotateUp', rotSpeed);
    moved = true;
  }
  if (movementKeys.arrowdown) {
    rotateCameraView('rotateDown', rotSpeed);
    moved = true;
  }

  if (moved) {
    scheduleCameraUpdate();
  }

  moveLoopId = requestAnimationFrame(moveLoop);
};

// ---- 向量工具 ----
const vec3 = {
  length(v) {
    return Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
  },
  normalize(v) {
    const len = vec3.length(v);
    return len > 1e-8 ? [v[0] / len, v[1] / len, v[2] / len] : [0, 0, 1];
  },
  cross(a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  },
  dot(a, b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  },
};

const sceneAxisVectors = computed(() => {
  const fwd = vec3.normalize(cameraState.value.forward);
  let up = vec3.normalize(cameraState.value.up);
  let right = vec3.cross(up, fwd);

  if (vec3.length(right) <= 1e-6) {
    up = Math.abs(fwd[1]) < 0.95 ? [0, 1, 0] : [1, 0, 0];
    right = vec3.cross(up, fwd);
  }

  right = vec3.normalize(right);
  up = vec3.normalize(vec3.cross(fwd, right));

  const center = 45;
  const radius = 29;
  const axes = [
    { name: 'X', color: '#ef4444', vector: [1, 0, 0] },
    { name: 'Y', color: '#22c55e', vector: [0, 1, 0] },
    { name: 'Z', color: '#3b82f6', vector: [0, 0, 1] },
  ];

  return axes
    .map((axis) => {
      const screenX = vec3.dot(axis.vector, right);
      const screenY = -vec3.dot(axis.vector, up);
      const depth = vec3.dot(axis.vector, fwd);
      const x = center + screenX * radius;
      const y = center + screenY * radius;
      const labelOffset = 9;
      const labelLength = Math.max(1, Math.sqrt(screenX * screenX + screenY * screenY));

      return {
        ...axis,
        x,
        y,
        labelX: x + (screenX / labelLength) * labelOffset,
        labelY: y + (screenY / labelLength) * labelOffset,
        opacity: 0.58 + Math.max(0, depth) * 0.35,
        width: 2.5 + Math.max(0, depth) * 1.2,
        depth,
      };
    })
    .sort((a, b) => a.depth - b.depth);
});

/**
 * 绕任意轴旋转向量 v（罗德里格斯公式）
 * @param {number[]} v   待旋转向量
 * @param {number[]} axis 旋转轴（需归一化）
 * @param {number} angle  旋转角度（弧度）
 */
const rotateVecAroundAxis = (v, axis, angle) => {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const k = axis;
  const dot = vec3.dot(k, v);
  const cross = vec3.cross(k, v);
  return [
    v[0] * c + cross[0] * s + k[0] * dot * (1 - c),
    v[1] * c + cross[1] * s + k[1] * dot * (1 - c),
    v[2] * c + cross[2] * s + k[2] * dot * (1 - c),
  ];
};

/**
 * 旋转摄像头 forward 向量
 * @param {'rotateLeft'|'rotateRight'|'rotateUp'|'rotateDown'} direction
 * @param {number} [angleDeg=2] 每步旋转角度
 */
const rotateCameraView = (direction, angleDeg = 2) => {
  const { forward, up } = cameraState.value;
  const fwd = vec3.normalize(forward);
  const worldUp = vec3.normalize(up);
  const angleRad = (angleDeg * Math.PI) / 180;

  let newFwd;
  if (direction === 'rotateLeft' || direction === 'rotateRight') {
    // 水平旋转（绕 world_up 轴）
    const yawAngle = direction === 'rotateLeft' ? -angleRad : angleRad;
    newFwd = rotateVecAroundAxis(fwd, worldUp, yawAngle);
  } else {
    // 垂直旋转（绕 right 轴，即 forward × up）
    const right = vec3.normalize(vec3.cross(fwd, worldUp));
    const pitchAngle = direction === 'rotateUp' ? angleRad : -angleRad;
    newFwd = rotateVecAroundAxis(fwd, right, pitchAngle);
    // 限制俯仰角，防止翻转（与 world_up 夹角保持在 10°~170°）
    const dotUp = vec3.dot(vec3.normalize(newFwd), worldUp);
    if (Math.abs(dotUp) > 0.985) return; // cos(10°) ≈ 0.985
  }

  cameraState.value.forward = vec3.normalize(newFwd);
};

/**
 * 鼠标拖拽旋转摄像头（灵敏度与分辨率无关）
 */
const handleMouseRotate = (dx, dy) => {
  const sensitivity = mouseSensitivity.value; // 度/像素
  const { forward, up } = cameraState.value;
  const fwd = vec3.normalize(forward);
  const worldUp = vec3.normalize(up);

  // 水平 yaw
  const yawRad = (-dx * sensitivity * Math.PI) / 180;
  let newFwd = rotateVecAroundAxis(fwd, worldUp, yawRad);

  // 垂直 pitch
  const right = vec3.normalize(vec3.cross(newFwd, worldUp));
  const pitchRad = (dy * sensitivity * Math.PI) / 180;
  const pitched = rotateVecAroundAxis(newFwd, right, pitchRad);

  const dotUp = vec3.dot(vec3.normalize(pitched), worldUp);
  if (Math.abs(dotUp) < 0.985) {
    newFwd = pitched;
  }

  cameraState.value.forward = vec3.normalize(newFwd);
};

// 鼠标左键拾取3D物体的两阶段重试
let _pickRetryTimer = null;
const PICK_RETRY_DELAY_MS = 60; // 等待引擎处理拾取请求（约一帧时间）

const handleViewportPick = async (event) => {
  const sceneId = tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME;
  const vpW = window.innerWidth;
  const vpH = window.innerHeight;
  const clientX = event.clientX;
  const clientY = event.clientY;

  // ── 快速通道：coronaBridge.pickActor → CEF ProcessMessage → SharedDataHub ──
  const bridge = window.coronaBridge;
  if (bridge && typeof bridge.pickActor === 'function') {
    try {
      bridge.pickActor(0, clientX, clientY, vpW, vpH);  // scene_handle=0 means use current active scene
      console.log('[PickFast] pickActor called (%d,%d) vp=(%d,%d)', clientX, clientY, vpW, vpH);
      return;
    } catch (e) {
      console.warn('[PickFast] coronaBridge.pickActor failed, falling back to Python:', e);
    }
  }

  // ── 慢通道：Python cefQuery 回退 ──
  try {
    console.log('[Pick] 请求拾取 scene=%s pos=(%d,%d) vp=(%d,%d)', sceneId, clientX, clientY, vpW, vpH);
    const result = await sceneService.pickActor(
      sceneId, clientX, clientY, vpW, vpH
    );
    const data = result?.data ?? result;
    console.log('[Pick] 第一次响应:', JSON.stringify(data));
    if (data?.status === 'pending') {
      if (_pickRetryTimer) clearTimeout(_pickRetryTimer);
      _pickRetryTimer = setTimeout(async () => {
        _pickRetryTimer = null;
        try {
          const retryResult = await sceneService.pickActor(
            sceneId, clientX, clientY, vpW, vpH
          );
          const retryData = retryResult?.data ?? retryResult;
          if (retryData?.status === 'success') {
            console.log('[Pick] 选中物体:', retryData.actor?.name);
          }
        } catch (e) { /* retry silently */ }
      }, PICK_RETRY_DELAY_MS);
    } else if (data?.status === 'success') {
      console.log('[Pick] 命中缓存:', data.actor?.name);
    }
  } catch (e) { /* pick silently */ }
};

const onMouseDown = (event) => {
  // 右键拖拽旋转（原有逻辑不变）
  if (event.button === 2) {
    mouseRotate.active = true;
    mouseRotate.lastX = event.clientX;
    mouseRotate.lastY = event.clientY;
    event.preventDefault();
    return;
  }

  // 左键：在3D视口中拾取物体
  if (event.button === 0) {
    // 忽略UI交互元素上的点击（菜单栏、按钮、输入框、场景标签等）
    const interactiveEl = event.target.closest(
      'button, a, input, select, textarea, [role="button"], [role="menubar"]'
    );
    if (interactiveEl) return;

    handleViewportPick(event);
  }
};

const onMouseMove = (event) => {
  if (!mouseRotate.active) return;
  const dx = event.clientX - mouseRotate.lastX;
  const dy = event.clientY - mouseRotate.lastY;
  mouseRotate.lastX = event.clientX;
  mouseRotate.lastY = event.clientY;

  if (dx === 0 && dy === 0) return;
  handleMouseRotate(dx, dy);
  scheduleCameraUpdate();
};

const onMouseUp = (event) => {
  if (event.button === 2 && mouseRotate.active) {
    mouseRotate.active = false;
    if (!sendCameraUpdateFast()) {
      const sceneId = tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME;
      syncSceneCameraBinding(sceneId);
    }
  }
};

const onContextMenu = (event) => {
  event.preventDefault();
};

const sendCameraUpdateFast = () => {
  const handle = cameraBindingState.value.cameraHandle;
  if (!handle) return false;
  const bridge = window.coronaBridge;
  if (!bridge || typeof bridge.cameraMove !== 'function') {
    if (!window._coronaBridgeWarned) {
      window._coronaBridgeWarned = true;
      console.warn(
        '[Camera] coronaBridge 缺失或 cameraMove 不可用，' +
        'CEF 子进程可能未运行。快速通道摄像头更新已禁用。'
      );
    }
    return false;
  }
  try {
    bridge.cameraMove(
      handle,
      [...cameraState.value.position],
      [...cameraState.value.forward],
      [...cameraState.value.up],
      cameraState.value.fov
    );
    return true;
  } catch (e) {
    return false;
  }
};

/** 发送当前 cameraState 到引擎——已移除，全部走快速通道 */

const handleCameraMove = (direction) => {
  const speed = cameraSpeed.value;
  const { position, forward, up } = cameraState.value;

  // 基于摄像头朝向计算移动方向（左手坐标系：right = up × forward）
  const fwd = vec3.normalize(forward);
  const worldUp = vec3.normalize(up);
  const right = vec3.normalize(vec3.cross(worldUp, fwd));

  switch (direction) {
    case 'up':
      position[0] += worldUp[0] * speed;
      position[1] += worldUp[1] * speed;
      position[2] += worldUp[2] * speed;
      break;
    case 'down':
      position[0] -= worldUp[0] * speed;
      position[1] -= worldUp[1] * speed;
      position[2] -= worldUp[2] * speed;
      break;
    case 'left':
      position[0] -= right[0] * speed;
      position[1] -= right[1] * speed;
      position[2] -= right[2] * speed;
      break;
    case 'right':
      position[0] += right[0] * speed;
      position[1] += right[1] * speed;
      position[2] += right[2] * speed;
      break;
    case 'forward':
      position[0] += fwd[0] * speed;
      position[1] += fwd[1] * speed;
      position[2] += fwd[2] * speed;
      break;
    case 'backward':
      position[0] -= fwd[0] * speed;
      position[1] -= fwd[1] * speed;
      position[2] -= fwd[2] * speed;
      break;
    case 'rotateRight':
    case 'rotateLeft':
    case 'rotateUp':
    case 'rotateDown':
      rotateCameraView(direction);
      break;
  }

  scheduleCameraUpdate();
};

const handleApplyPhysics = async () => {
  const sceneId = tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME;
  activeMenu.value = null;
  try {
    await sceneService.setPhysicsParams(sceneId, {
      gravity: [
        physicsParams.value.gravityX,
        physicsParams.value.gravityY,
        physicsParams.value.gravityZ,
      ],
      floor_y: physicsParams.value.floorY,
      floor_restitution: physicsParams.value.floorRestitution,
      fixed_dt: physicsParams.value.fixedDt,
    });
  } catch (e) {
    logError('Apply physics params failed', e);
  }
};

const loadPhysicsParams = async () => {
  const sceneId = tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME;
  try {
    const result = await sceneService.getPhysicsParams(sceneId);
    const data = result?.data ?? result;
    if (data && data.status !== 'error') {
      const g = data.gravity || [0, -9.8, 0];
      physicsParams.value.gravityX = g[0];
      physicsParams.value.gravityY = g[1];
      physicsParams.value.gravityZ = g[2];
      physicsParams.value.floorY = data.floor_y ?? 0.0;
      physicsParams.value.floorRestitution = data.floor_restitution ?? 0.6;
      physicsParams.value.fixedDt = data.fixed_dt ?? 1.0 / 60.0;
    }
  } catch (e) {
    logError('Load physics params failed', e);
  }
};

// 关闭标签页
const closeTab = async (index) => {
  if (tabs.value.length > 1) {
    const removedId = tabs.value[index]?.id;

    if (activeTab.value === index && activeTab.value === 0) {
      activeTab.value = 1;
    }

    tabs.value.splice(index, 1);
    if (activeTab.value >= index) {
      await switchTab(Math.max(0, activeTab.value - 1), false);
    }

    if (removedId) {
      try {
        await projectService.removeScene(removedId);
      } catch (e) {
        logError('Failed to remove scene from project', e);
      }
    }
  }
};

// 切换标签页
const switchTab = async (index, if_new) => {
  if (activeTab.value === index) {
    return;
  }
  const current_name = tabs.value[activeTab.value]?.id;
  const to_name = tabs.value[index]?.id;
  activeTab.value = index;
  if (if_new) {
    await createScene();
  }

  await projectService.sceneSwitch(current_name, to_name);

  await syncSceneCameraBinding(to_name);
};

const startEngine = () => {
  dockStore.initDefaultLayout();
};

const createScene = async () => {
  const payload = tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME;
  try {
    const result = await sceneService.createScene(payload);
    applySceneSnapshot(payload, result);
  } catch (e) {
    logError('Failed to create scene', e);
  }
};

// ========== 预留的空函数 ==========

// 项目菜单
const handleNewProject = () => {
  console.log('新建项目');
  activeMenu.value = null;
  // TODO: 实现新建项目逻辑
};

const handleOpenProject = () => {
  console.log('打开项目');
  activeMenu.value = null;
  // TODO: 实现打开项目逻辑
};

const handleProjectSettings = () => {
  dockStore.openPanel('ProjectSettings');
  activeMenu.value = null;
};

const handleSaveProject = () => {
  console.log('保存项目');
  activeMenu.value = null;
  // TODO: 实现保存项目逻辑
};

// 视图工具/插件切换：由 Pinia dockStore 管理
const toggleViewTool = (tool) => {
  dockStore.togglePanel(tool.id);
};

const unwrapBridgeData = (result) => result?.data ?? result;

const clearPreviewPoll = () => {
  if (previewPollTimer) {
    clearTimeout(previewPollTimer);
    previewPollTimer = null;
  }
};

const pollGamePreviewStatus = () => {
  clearPreviewPoll();
  const poll = async () => {
    try {
      const result = await scriptingService.getGamePreviewStatus();
      const status = unwrapBridgeData(result);
      const state = status?.status || 'idle';
      const count = status?.running_count || 0;
      const hasSnapshot = !!status?.has_snapshot;
      previewRunning.value = state === 'running' || state === 'stopping' || count > 0 || hasSnapshot;
      previewStatusText.value = previewRunning.value
        ? (count > 0 ? `预览中 ${count}` : '预览已停止，等待恢复')
        : state === 'error'
          ? '预览出错'
          : '';
      if (previewRunning.value) {
        previewPollTimer = setTimeout(poll, 1000);
      }
    } catch (error) {
      previewRunning.value = false;
      previewStatusText.value = '预览状态异常';
      logError('查询预览状态失败', error);
    }
  };
  previewPollTimer = setTimeout(poll, 800);
};

const handleStartGamePreview = async () => {
  if (previewRunning.value || previewBusy.value) return;
  previewBusy.value = true;
  previewStatusText.value = '准备预览...';
  try {
    if (typeof window.__coronaBlocklyFlushSave === 'function') {
      await window.__coronaBlocklyFlushSave();
    }
    const result = await scriptingService.startGamePreview({ scope: 'project' });
    const payload = unwrapBridgeData(result);
    if (payload?.status === 'error') {
      previewRunning.value = false;
      previewStatusText.value = '预览启动失败';
      logError('开始预览失败', payload.message);
      return;
    }
    previewRunning.value = payload?.status === 'running' || (payload?.started_count || 0) > 0;
    previewStatusText.value = previewRunning.value
      ? `预览中 ${payload?.started_count || 0}`
      : '没有可运行积木';
    if (previewRunning.value) pollGamePreviewStatus();
  } catch (error) {
    previewRunning.value = false;
    previewStatusText.value = '预览启动失败';
    logError('开始预览失败', error);
  } finally {
    previewBusy.value = false;
    activeMenu.value = null;
  }
};

const handleStopGamePreview = async () => {
  if (!previewRunning.value || previewBusy.value) return;
  previewBusy.value = true;
  previewStatusText.value = '正在恢复预览前参数...';
  let keepPreviewActive = false;
  try {
    const result = await scriptingService.stopGamePreview();
    const payload = unwrapBridgeData(result);
    if (payload?.restore_error) {
      keepPreviewActive = true;
      previewStatusText.value = '预览恢复失败';
      logError('结束预览恢复失败', payload.restore_error);
      return;
    }
    if (payload?.restored) {
      previewStatusText.value = '已恢复预览前参数';
      setTimeout(() => {
        if (!previewRunning.value && !previewBusy.value && previewStatusText.value === '已恢复预览前参数') {
          previewStatusText.value = '';
        }
      }, 2000);
    } else {
      previewStatusText.value = '';
    }
  } catch (error) {
    previewStatusText.value = '结束预览失败';
    logError('结束预览失败', error);
  } finally {
    clearPreviewPoll();
    previewRunning.value = keepPreviewActive;
    previewBusy.value = false;
    activeMenu.value = null;
  }
};

// 修改：运行菜单的处理函数
const handleRunProject = async () => {
  try {
    console.log('运行项目');
    // 不传参数，运行整个项目
    const result = await projectService.runProject();

    if (result.success) {
      // TODO: 可以显示一个成功提示
    } else {
      logError('运行项目返回失败', result?.message);
    }
  } catch (error) {
    logError('运行项目失败', error);
  } finally {
    activeMenu.value = null;
  }
};

const handleRunCurrentScene = async () => {
  try {
    console.log('运行当前场景');
    const currentSceneId = tabs.value[activeTab.value]?.id;

    if (!currentSceneId) {
      logError('没有当前场景');
      return;
    }

    // 传入场景路径，运行指定场景
    const result = await projectService.runProject(currentSceneId);

    if (result.success) {
      // TODO: 可以显示一个成功提示
    } else {
      logError('运行当前场景返回失败', result?.message);
    }
  } catch (error) {
    logError('运行当前场景失败', error);
  } finally {
    activeMenu.value = null;
  }
};

// 帮助菜单
const handleHelpDocs = () => {
  console.log('帮助文档');
  activeMenu.value = null;
  // TODO: 实现打开帮助文档逻辑
};

const handleAbout = () => {
  console.log('关于');
  activeMenu.value = null;
  // TODO: 实现显示关于信息逻辑
};

const setupListener = () => {
  // 显示弹窗（智能选择主窗口或本地）
  window.showLoading = (title, message, progress = 0) => {
    localModalTitle.value = title;
    localModalMessage.value = message;
    localModalProgress.value = progress;
    showLocalModal.value = true;
  };

  // 更新弹窗
  window.updateLoading = (message, progress) => {
    if (message !== undefined) localModalMessage.value = message;
    if (progress !== undefined) localModalProgress.value = progress;
  };

  // 隐藏弹窗
  window.hideLoading = () => {
    showLocalModal.value = false;
    setTimeout(() => {
      localModalTitle.value = '';
      localModalMessage.value = '';
      localModalProgress.value = 0;
    }, 300);
  };

  window.syncCameraState = () => {
    const sceneId = tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME;
    syncSceneCameraBinding(sceneId);
  };

  window.addTab = (name, id) => {
    const existingIndex = tabs.value.findIndex((tab) => tab.id === id);
    if (existingIndex !== -1) {
      switchTab(existingIndex, false);
      return false;
    }
    tabs.value.push({
      name: name,
      id: id,
    });
    switchTab(tabs.value.length - 1, false);
    return true;
  };

  window.renameTab = (oldId, newId, newName) => {
    const tabIndex = tabs.value.findIndex((tab) => tab.id === oldId);
    if (tabIndex !== -1) {
      tabs.value[tabIndex] = {
        ...tabs.value[tabIndex],
        id: newId,
        name: newName || tabs.value[tabIndex].name, // 如果没有提供新名称，保留原名称
      };

      if (activeTab.value === tabIndex) {
        cameraBindingState.value.sceneId = newId;
        syncSceneCameraBinding(newId);
      }

      return true;
    }
  };
};

// 监听其他窗口（如设置页面）修改了 cabbage_hint_time
function onStorageChange(e) {
  if (e.key === STORAGE_KEY) {
    readCabbageHintTime();
    setHintShowMs(cabbageHintTime.value * 1000);
  }
}

onMounted(async () => {
  await appService.removeDockWidget('RecentGames');
  await appService.removeDockWidgetByRoute('/StartScreen');
  const result = await projectService.OnInit();
  const initData = result?.data ?? result;
  const scenes = initData?.scenes ?? [];
  const activeIndex = initData?.active_index ?? 0;

  if (scenes.length > 0) {
    for (const s of scenes) {
      tabs.value.push({ name: s.name, id: s.path });
    }
  } else {
    // 兼容旧格式
    tabs.value.push({
      name: initData?.name ?? DEFAULT_SCENE_NAME,
      id: initData?.path ?? DEFAULT_SCENE_NAME,
    });
  }
  activeTab.value = activeIndex;

  await startEngine();
  // 等待 Vue 渲染 dock 面板（SceneBar/Object 等），确保 eventBus 监听就绪
  await nextTick();
  const initialSceneId = tabs.value[activeIndex]?.id || DEFAULT_SCENE_NAME;
  await projectService.sceneSwitch(null, initialSceneId);
  await syncSceneCameraBinding(tabs.value[activeTab.value]?.id || DEFAULT_SCENE_NAME);

  document.addEventListener('keydown', handleKeyDown);
  document.addEventListener('keyup', handleKeyUp);
  document.addEventListener('click', handleClickOutside);
  document.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
  document.addEventListener('contextmenu', onContextMenu);
  setupListener();

  // 跨窗口事件监听：scene-add / scene-rename / panel-closed
  coronaEventBus.on('scene-add', (name, id) => {
    if (window.addTab) window.addTab(name, id);
  });
  coronaEventBus.on('scene-rename', (oldId, newId, newName) => {
    if (window.renameTab) window.renameTab(oldId, newId, newName);
  });
  coronaEventBus.on('panel-closed', (payload) => {
    const panelId = payload?.panelId;
    if (panelId) dockStore.popIn(panelId);
  });

  // 启动阶段性包菜提示：每隔一段时间根据用户操作自动弹出 AI 提示气泡
  startStageHints(
    (text) => {
      cabbageBubbleText.value = text;
      cabbageBubbleLoading.value = false;
      cabbageBubbleShow.value = true;
    },
    () => {
      cabbageBubbleShow.value = false;
      cabbageBubbleLoading.value = true;
    },
    cabbageHintTime.value * 1000
  );
});

onUnmounted(() => {
  clearPreviewPoll();
  stopStageHints();
  coronaEventBus.off('scene-add');
  coronaEventBus.off('scene-rename');
  coronaEventBus.off('panel-closed');
  window.removeEventListener('storage', onStorageChange);
  stopMoveLoop();
  // 清理拾取重试定时器
  if (_pickRetryTimer) {
    clearTimeout(_pickRetryTimer);
    _pickRetryTimer = null;
  }
  document.removeEventListener('keydown', handleKeyDown);
  document.removeEventListener('keyup', handleKeyUp);
  document.removeEventListener('click', handleClickOutside);
  document.removeEventListener('mousedown', onMouseDown);
  document.removeEventListener('mousemove', onMouseMove);
  document.removeEventListener('mouseup', onMouseUp);
  document.removeEventListener('contextmenu', onContextMenu);
});
</script>
