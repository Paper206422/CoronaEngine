<template>
  <div
    :class="embedded ? 'h-full' : 'h-screen'"
    class="rounded-lg overflow-hidden relative bg-[#282828]/90 flex flex-col text-white font-sans"
  >
    <DockTitleBar
      v-if="!embedded"
      :title="editingTarget ? `积木编辑器 - ${editingTarget}` : '积木编辑器'"
      extraClass="bg-[#84A65B]"
      routePath="/ScratchTool"
      @close="handleClose"
    />

    <Navigat v-if="!embedded" @new-canvas="handleNewCanvas" />

    <div class="flex-1 flex overflow-hidden">
      <div ref="blockdiv" class="flex-1 relative" style="overflow: hidden;">
        <Search />
        <Zoom />
        <Trashcan />
        <div id="status-overlay" class="absolute inset-0 flex items-center justify-center z-10" style="background: #1e1e1e;">
          <div class="text-center">
            <div class="text-xl font-bold text-green-400 mb-2">积木编辑器</div>
            <div class="text-sm text-gray-400">Blockly 工作区加载中...</div>
          </div>
        </div>
      </div>

      <div
        v-if="store.hasLayoutSider.value"
        class="w-80 flex flex-col border-l border-gray-700 bg-[#1e1e1e]"
      >
        <div class="flex items-center justify-between px-3 py-2 border-b border-gray-700">
          <span class="text-sm text-gray-300 font-medium">Python 代码</span>
          <div class="flex items-center gap-1">
            <button
              class="text-xs px-2 py-1 rounded transition-colors font-medium select-none"
              :class="codeRunning
                ? 'text-red-300 bg-red-700/40 hover:bg-red-600/50 hover:text-red-200'
                : 'text-green-400 bg-green-700/30 hover:bg-green-600/40 hover:text-green-200'"
              @click="handleToggleRun"
            >{{ codeRunning ? '⏹ 停止' : '▶ 运行' }}</button>
            <button
              class="text-gray-400 hover:text-white transition-colors text-lg leading-none px-1"
              @click="store.hasLayoutSider.value = false"
            >✕</button>
          </div>
        </div>
        <pre class="flex-1 overflow-auto p-3 text-sm text-green-400 font-mono whitespace-pre-wrap m-0">{{ generatedCode }}</pre>
      </div>
    </div>
  </div>
</template>

<script>
// ============================================================
// 模块级持久状态（组件挂载/卸载后保持）
// 必须放在独立的 <script> 块中（非 setup），否则会被编译到 setup()
// 函数作用域内，导致每次组件挂载都重新初始化
// ============================================================

/** 存储每个 actor 的工作区序列化状态 key: "scene_name/actor_name" → state JSON */
const workspaceStates = new Map();

/** localStorage 键前缀 */
const LS_WS_PREFIX = '__bl_ws__';

/** 当前已加载的 actor key */
let loadedActorKey = '';

/** 当前编辑的 Actor 名称（给积木定义 getter 用） */
let currentActorNameVar = '';

/** 脚本状态轮询定时器 */
let pollTimer = null;
</script>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue';
import { useErrorHandler } from '@/composables/useErrorHandler.js';
import { appService, scriptingService } from '@/utils/bridge.js';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';
import Navigat from './Navigat.vue';
import Search from './Search.vue';
import Zoom from './Zoom.vue';
import Trashcan from './Trashcan.vue';
import { useStore } from '../store/store.js';
import { currentSceneName, currentActorName, getActorContext, syncActorContextFromStorage } from '../composables/useActorContext.js';

const props = defineProps({
  actorName: { type: String, default: '' },
  /** 嵌入式模式：作为子组件内嵌到物体属性面板 */
  embedded: { type: Boolean, default: false },
  /** 场景名称（嵌入式时由父组件传入） */
  sceneName: { type: String, default: '' },
});

const emit = defineEmits(['resize']);
const { error: logError } = useErrorHandler('BlocklyWorkspace');

const blockdiv = ref(null);
const store = useStore();
const generatedCode = ref('');
const codeRunning = ref(false);

// 标题栏显示的当前编辑目标
const editingTarget = ref('');

// 关键修复：不使用 Vue ref()/shallowRef() 存储 Blockly workspace
// 原因：Vue ref() 内部会对对象调用 reactive() 生成 Proxy
// Blockly workspace 被 Proxy 包裹后，序列化/反序列化时访问
// caller/callee/arguments 等内部属性会触发严格模式限制而报错
// 参考 Blockly 官方 issue #8441
let workspace = null;

let BlocklyLib = null;
let blocklyCN = null;
let blocksRegistered = false;

// 保存 store 引用，供 onUnmounted 清理共享状态
let sharedStore = null;

let pythonGenerator = null;

// CEF 键盘事件转发：在 OSR 模式下 Blockly FieldTextInput 的 HTML widget
// 无法接收原生键盘事件，需要在 document 层面拦截并手动转发
let cefKeyHandler = null;

function setupCefFieldInputFix() {
  cefKeyHandler = (e) => {
    // 已有原生 input 获得焦点时，不干预
    const activeEl = document.activeElement;
    if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) {
      // 如果焦点就在 blocklyHtmlInput 上，说明原生键盘已生效，不转发
      if (activeEl.classList.contains('blocklyHtmlInput')) return;
      return;
    }

    // 查找 Blockly 字段编辑器输入框
    const htmlInput = document.querySelector('.blocklyHtmlInput');
    if (!htmlInput) return;

    // 转发可打印字符到输入框
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      e.stopPropagation();
      const start = htmlInput.selectionStart ?? htmlInput.value.length;
      const end = htmlInput.selectionEnd ?? start;
      htmlInput.value =
        htmlInput.value.slice(0, start) + e.key + htmlInput.value.slice(end);
      htmlInput.selectionStart = htmlInput.selectionEnd = start + 1;
      htmlInput.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: e.key }));
      return;
    }

    // 特殊功能键：先聚焦到输入框，让 Blockly 的内部处理器接管
    if (['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape', 'Enter', 'Tab'].includes(e.key)) {
      htmlInput.focus();
    }
  };
  document.addEventListener('keydown', cefKeyHandler, true);
}

function teardownCefFieldInputFix() {
  if (cefKeyHandler) {
    document.removeEventListener('keydown', cefKeyHandler, true);
    cefKeyHandler = null;
  }
}

async function updateGeneratedCode() {
  if (!workspace || !pythonGenerator) {
    generatedCode.value = '';
    return;
  }
  try {
    const code = pythonGenerator.workspaceToCode(workspace);
    generatedCode.value = code || '# 暂无代码';
  } catch {
    generatedCode.value = '# 代码生成失败';
  }
}

async function handleToggleRun() {
  if (codeRunning.value) {
    // 当前正在执行 → 停止
    clearPollTimer();
    try {
      await scriptingService.stopScriptExecution();
    } catch (e) {
      console.warn('[Blockly] 停止脚本失败:', e);
    }
    codeRunning.value = false;
    return;
  }

  // 当前未执行 → 运行
  const code = generatedCode.value;
  if (!code || code === '# 暂无代码' || code === '# 代码生成失败') {
    alert('没有可执行的代码。请先添加积木。');
    return;
  }

  // 嵌入模式用 props，独立模式用 useActorContext
  let scene, actor;
  if (props.embedded) {
    scene = props.sceneName;
    actor = props.actorName;
  } else {
    ({ scene, actor } = getActorContext());
  }
  if (!scene || !actor) {
    alert('请先在场景中选中一个物体，再点击运行。');
    return;
  }

  codeRunning.value = true;
  try {
    const result = await scriptingService.executePythonCode(
      code,
      0,
      scene,
      actor,
    );
    if (result?.status === 'error') {
      alert('代码执行出错：' + (result.message || '未知错误'));
      codeRunning.value = false;
    } else {
      // 脚本已在后台线程启动，开始轮询状态
      startPollTimer();
    }
  } catch (e) {
    alert('代码执行失败：' + (e.message || '通信错误'));
    codeRunning.value = false;
  }
}

function clearPollTimer() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function startPollTimer() {
  clearPollTimer();
  const poll = async () => {
    if (!codeRunning.value) return;
    try {
      const status = await scriptingService.getScriptStatus();
      if (status?.status === 'idle') {
        codeRunning.value = false;
        return;
      }
    } catch (e) {
      // 状态查询失败时也停止轮询并恢复按钮
      console.warn('[Blockly] 脚本状态查询失败:', e);
      codeRunning.value = false;
      return;
    }
    pollTimer = setTimeout(poll, 500);
  };
  pollTimer = setTimeout(poll, 500);
}

const loadBlocklyModules = async () => {
  try {
    BlocklyLib = await import('blockly/core');
    blocklyCN = await import('blockly/msg/zh-hans');
    return true;
  } catch (e) {
    logError('Blockly 模块加载失败', e);
    return false;
  }
};

const broadcastList = ref([]);
const createNewBroadcast = () => {
  const name = prompt('请输入新广播的名称：');
  if (name && name.trim() !== '') broadcastList.value.push(name.trim());
};

// ============================================================
// 按 Actor 管理工作区状态（Blockly 官方推荐模式）
function saveCurrentWorkspace() {
  if (!workspace || !BlocklyLib || !loadedActorKey) return;
  try {
    const state = BlocklyLib.serialization.workspaces.save(workspace);
    workspaceStates.set(loadedActorKey, state);
    // 持久化到 localStorage，使积木数据在页面刷新后不丢失
    try { localStorage.setItem(LS_WS_PREFIX + loadedActorKey, JSON.stringify(state)); } catch (_) {}
  } catch (e) {
    logError('保存工作区状态失败', e);
  }
}

/**
 * 切换到指定 Actor 的工作区状态
 * 参考 Blockly 官方序列化 API：
 *   - 保存当前状态 → 清空工作区 → 加载目标状态
 */
function switchToActor(sceneName, actorName) {
  if (!workspace || !BlocklyLib) return;

  const newKey = sceneName && actorName ? `${sceneName}/${actorName}` : '';
  if (newKey === loadedActorKey) return;

  // 1. 保存当前工作区
  saveCurrentWorkspace();

  // 2. 清空工作区（保留变量等全局数据）
  try {
    workspace.clear();
  } catch (e) {
    logError('清空工作区失败', e);
  }

  // 3. 加载目标 Actor 的工作区状态
  loadedActorKey = newKey;
  currentActorNameVar = actorName || '';

  if (newKey) {
    // 优先内存，兜底从 localStorage 恢复
    let state = workspaceStates.get(newKey);
    if (!state) {
      try {
        const raw = localStorage.getItem(LS_WS_PREFIX + newKey);
        if (raw) { state = JSON.parse(raw); workspaceStates.set(newKey, state); }
      } catch (_) {}
    }
    if (state) {
      try {
        BlocklyLib.serialization.workspaces.load(state, workspace);
      } catch (e) {
        logError('加载工作区状态失败', e);
      }
    }
  }

  // 4. 更新标题
  editingTarget.value = actorName
    ? `${actorName} [${sceneName || ''}]`
    : '';

  // 5. 刷新代码预览
  updateGeneratedCode();
}

// 嵌入模式监听 props，独立模式监听全局选中
if (props.embedded) {
  watch(
    () => [props.sceneName, props.actorName],
    ([s, a]) => { switchToActor(s, a); },
  );
} else {
  watch(
    [currentSceneName, currentActorName],
    ([scene, actor]) => { switchToActor(scene, actor); },
    { immediate: false },
  );
}

const initBlocklyAndGenerators = async () => {
  currentActorNameVar = props.actorName || '';

  if (!blocksRegistered) {
    const [
      { defineEngineBlocks },
      { defineAppearanceBlocks },
      { defineEventBlocks },
      { defineControlBlocks },
      { defineDetectBlocks },
      { defineMathBlocks },
      { defineVariableBlocks },
      { defineListBlocks },
    ] = await Promise.all([
      import('@/blockly/blocks/engine.js'),
      import('@/blockly/blocks/appearance.js'),
      import('@/blockly/blocks/event.js'),
      import('@/blockly/blocks/control.js'),
      import('@/blockly/blocks/detect.js'),
      import('@/blockly/blocks/math.js'),
      import('@/blockly/blocks/variable.js'),
      import('@/blockly/blocks/list.js'),
    ]);

    try {
      defineEngineBlocks({ get value() { return currentActorNameVar; } });
      defineAppearanceBlocks({ get value() { return currentActorNameVar; } });
      defineEventBlocks({ get value() { return currentActorNameVar; } }, broadcastList, createNewBroadcast);
      defineControlBlocks({ get value() { return currentActorNameVar; } });
      defineDetectBlocks({ get value() { return currentActorNameVar; } });
      defineMathBlocks();
      defineVariableBlocks();
      defineListBlocks({ get value() { return currentActorNameVar; } });

      const [
        { defineEngineGenerators },
        { defineAppearanceGenerators },
        { defineEventGenerators },
        { defineControlGenerators },
        { defineDetectGenerators },
        { defineMathGenerators },
        { defineVariableGenerators },
        { defineListGenerators },
      ] = await Promise.all([
        import('@/blockly/generators/engine.js'),
        import('@/blockly/generators/appearance.js'),
        import('@/blockly/generators/event.js'),
        import('@/blockly/generators/control.js'),
        import('@/blockly/generators/detect.js'),
        import('@/blockly/generators/math.js'),
        import('@/blockly/generators/variable.js'),
        import('@/blockly/generators/list.js'),
      ]);

      defineEngineGenerators();
      defineAppearanceGenerators();
      defineEventGenerators();
      defineControlGenerators();
      defineDetectGenerators();
      defineMathGenerators();
      defineVariableGenerators();
      defineListGenerators();

      blocksRegistered = true;
    } catch (e) {
      logError('注册积木/生成器失败', e);
      throw e;
    }
  }
};

const initBlockly = async () => {
  const container = blockdiv.value;
  if (!container) {
    logError('Blockly 容器未找到');
    return false;
  }

  const modulesOk = await loadBlocklyModules();
  if (!modulesOk) return false;

  const Blockly = BlocklyLib;
  const CN = blocklyCN;

  try {
    Blockly.setLocale(CN);
  } catch (e) {
    logError('setLocale 失败', e);
  }

  await initBlocklyAndGenerators();

  const { WORKSPACE_CONFIG } = await import('@/blockly/configs/workspaceConfig.js');
  const store = useStore();
  sharedStore = store;

  try {
    workspace = Blockly.inject(container, WORKSPACE_CONFIG);
  } catch (e) {
    logError('Blockly.inject 失败', e);
    return false;
  }

  store.workspace.value = workspace;
  store.workspaceSvg.value = workspace.workspaceSvg || workspace;

  // CEF OSR 键盘转发修复
  setupCefFieldInputFix();

  try { Blockly.ContextMenuRegistry.registry.unregister('saveWorkspace'); } catch {}

  Blockly.ContextMenuRegistry.registry.register({
    displayText: '保存工作区',
    preconditionFn: () => workspace && workspace.getAllBlocks(false).length > 0 ? 'enabled' : 'disabled',
    callback: async () => {
      const data = Blockly.serialization.workspaces.save(workspace);
      const jsonStr = JSON.stringify(data, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/json' });
      try {
        const opts = {
          types: [{ description: 'Blockly 项目文件', accept: { 'application/json': ['.blockly'] } }],
          suggestedName: `project_${Date.now()}.blockly`,
        };
        const handle = await window.showSaveFilePicker(opts);
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
      } catch {}
    },
    scopeType: Blockly.ContextMenuRegistry.ScopeType.WORKSPACE,
    id: 'saveWorkspace',
    weight: 1,
  });

  const { pythonGenerator: pyGen } = await import('blockly/python');
  pythonGenerator = pyGen;
  updateGeneratedCode();

  workspace.addChangeListener(() => { updateGeneratedCode(); });

  hideOverlay();
  resizeBlockly();
  return true;
};

const hideOverlay = () => {
  const overlay = document.getElementById('status-overlay');
  if (overlay) overlay.style.display = 'none';
};

const resizeBlockly = () => {
  try {
    if (!workspace) return;
    BlocklyLib && BlocklyLib.svgResize(workspace);
    emit('resize');
  } catch {}
};

const handleClose = async () => {
  try {
    await appService.removeDockWidget('ScratchTool');
  } catch (e) {
    logError('关闭积木编辑器失败', e);
  }
};

/**
 * 新建画布：保存当前状态 → 清空工作区 → 清除持久化状态
 * 确保后续切换 Actor 时不会加载旧积木
 */
function handleNewCanvas() {
  if (!workspace || !BlocklyLib) return;

  // 1. 先保存当前状态（用户可能做了修改但还没切换）
  saveCurrentWorkspace();

  // 2. 清除当前 Actor 的持久化状态
  if (loadedActorKey) {
    workspaceStates.delete(loadedActorKey);
    try { localStorage.removeItem(LS_WS_PREFIX + loadedActorKey); } catch (_) {}
  }

  // 3. 清空工作区
  try {
    workspace.clear();
  } catch (e) {
    logError('清空工作区失败', e);
  }

  // 4. 立即保存空的 workspace 状态（覆盖旧状态）
  try {
    const emptyState = BlocklyLib.serialization.workspaces.save(workspace);
    if (loadedActorKey) {
      workspaceStates.set(loadedActorKey, emptyState);
    }
  } catch (e) {
    logError('保存空状态失败', e);
  }

  // 5. 刷新代码预览
  updateGeneratedCode();
}

const handleWindowResize = () => resizeBlockly();

let resizeObserver = null;

onMounted(async () => {
  window.addEventListener('resize', handleWindowResize);

  if (blockdiv.value) {
    resizeObserver = new ResizeObserver(() => resizeBlockly());
    resizeObserver.observe(blockdiv.value);
  }

  try {
    await initBlockly();
    if (props.embedded) {
      switchToActor(props.sceneName, props.actorName);
    } else {
      syncActorContextFromStorage();
      switchToActor(currentSceneName.value, currentActorName.value);
    }
  } catch (err) {
    logError('初始化失败', err);
    const overlay = document.getElementById('status-overlay');
    if (overlay) {
      overlay.innerHTML = '<div class="text-center"><div class="text-xl font-bold text-red-400 mb-2">初始化失败</div><div class="text-sm text-gray-400">请检查 Blockly 相关模块是否正确安装</div></div>';
    }
  }
});

onUnmounted(() => {
  window.removeEventListener('resize', handleWindowResize);
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null; }
  // 清理 CEF 键盘转发
  teardownCefFieldInputFix();
  // 清理状态轮询
  clearPollTimer();
  // 销毁前保存当前工作区状态
  saveCurrentWorkspace();
  if (workspace) {
    try { workspace.dispose(); } catch {}
    workspace = null;
  }
  // 清理共享 store 中的 workspace 引用，防止其他组件持有已销毁的对象
  if (sharedStore) {
    sharedStore.workspace.value = null;
    sharedStore.workspaceSvg.value = null;
  }
  // 重置积木注册标记，确保下次挂载时重新注册积木类型和生成器
  blocksRegistered = false;
  pythonGenerator = null;
  generatedCode.value = '';
});

defineExpose({ resize: resizeBlockly });
</script>