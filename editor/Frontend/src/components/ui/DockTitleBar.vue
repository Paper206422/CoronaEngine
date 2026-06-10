<template>
  <div
    ref="titleBarRef"
    class="titlebar flex items-center w-full p-2 justify-between select-none cursor-default"
    :class="extraClass"
    style="touch-action: none; -webkit-user-select: none; user-select: none"
  >
    <div class="text-white font-medium w-auto whitespace-nowrap">{{ title }}</div>
    <div class="flex w-full space-x-2 justify-end">
      <slot name="actions"></slot>

      <div class="flex items-center space-x-1">
        <button
          title="切换浮动/停靠"
          class="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded transition-colors duration-200"
          @click.stop="onToggleFloat"
        >
          ⤢
        </button>

        <button
          class="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded transition-colors duration-200"
          @click.stop="onClose"
        >
          ×
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, defineProps, defineEmits } from 'vue';
// 引入 projectService
import { projectService } from '@/utils/bridge.js';

const props = defineProps({
  title: { type: String, default: '' },
  extraClass: { type: String, default: '' },
  // 必须传入当前页面的 routePath，以便后端 Python 查找对应的 tab-Id
  routePath: { type: String, required: true },
});

const emit = defineEmits(['close', 'toggleFloat']);

// DOM 引用
const titleBarRef = ref(null);

// ============================================================================
// 内部坐标同步逻辑 (原 regionReporter.js 内容合并)
// ============================================================================

// 共享的节流函数，防止 Resize 期间发送请求过快
const THROTTLE_MS = 16; // 约 60fps

function throttle(fn, delay) {
  let lastCall = 0;
  return function (...args) {
    const now = new Date().getTime();
    if (now - lastCall < delay) return;
    lastCall = now;
    return fn(...args);
  };
}

// 实际发送坐标的函数
const sendRegionsToNative = (routePath, element) => {
  if (!routePath || !element) return;

  // 获取相对于 CEF 视口的坐标
  const rect = element.getBoundingClientRect();

  // 转换成后端需要的整数 (x, y, w, h)
  // 假设整个 TitleBar 区域都是可拖拽区域
  const x = Math.floor(rect.x);
  const y = Math.floor(rect.y);
  const w = Math.floor(rect.width);
  const h = Math.floor(rect.height);

  // 使用 bridge.js 中定义的 projectService 设置拖拽区域
  // 注意：projectService.setDragRegions 内部已经封装 DockCommand
  projectService.setDragRegions(routePath, x, y, w, h);
};

// 创建节流版本的发送函数
const throttledSend = throttle(sendRegionsToNative, THROTTLE_MS);

// 用于监听 DOM 尺寸变化的 Observer
let resizeObserver = null;

// ============================================================================
// 生命周期钩子
// ============================================================================

onMounted(() => {
  if (titleBarRef.value && props.routePath) {
    // 1. 初始化时发送一次坐标
    sendRegionsToNative(props.routePath, titleBarRef.value);

    // 2. 绑定 ResizeObserver，监听后续变化（如窗口缩放、布局调整）
    resizeObserver = new ResizeObserver(() => {
      // 变化时调用节流发送
      throttledSend(props.routePath, titleBarRef.value);
    });
    resizeObserver.observe(titleBarRef.value);
  } else {
    console.error('[DockTitleBar] Missing titleBarRef or routePath prop.');
  }
});

onUnmounted(() => {
  // 资源清理，防止内存泄漏
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
});

// ============================================================================
// 按钮事件处理
// ============================================================================

function onToggleFloat() {
  emit('toggleFloat');
}

function onClose() {
  emit('close');
}
</script>

<style scoped>
/* 保持原有的样式 */
</style>
