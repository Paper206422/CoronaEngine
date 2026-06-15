<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useDockStore } from '@/stores/dockStore.js';
import { getPluginManifest } from '@/config/pluginManifest.js';
import DockLayout from '@/components/dock/DockLayout.vue';
import DockPanel from '@/components/dock/DockPanel.vue';
import CameraFollowPanel from '@/components/panels/CameraFollowPanel.vue';
import '@/utils/eventBus.js'; // init window.__coronaEmit

const route = useRoute();
const dockStore = useDockStore();

const isEditorRoute = computed(() => route.path === '/');
const centerPanels = computed(() => dockStore.panelsByZone('center'));

let gcTimer = null;

function isEscapeKey(event) {
  const modifierKeys = new Set([
    'Shift', 'Control', 'Alt', 'Meta',
    'ShiftLeft', 'ShiftRight',
    'ControlLeft', 'ControlRight',
    'AltLeft', 'AltRight',
    'MetaLeft', 'MetaRight',
  ]);
  if (modifierKeys.has(event.key) || modifierKeys.has(event.code)) return false;
  return event.key === 'Escape' && (event.code === 'Escape' || event.keyCode === 27 || event.which === 27);
}

function onGlobalKeyDown(event) {
  if (event.defaultPrevented) return;
  if (isEscapeKey(event)) {
    dockStore.togglePanel('EditorSettings');
  }
}

// ── 面板缩放 ──
const resizing = ref(null); // { panelId, startX, startY, startW, startH, edge }

function startResize(panelId, edge, e) {
  e.preventDefault();
  e.stopPropagation();
  const panel = dockStore.panels[panelId];
  if (!panel) return;
  resizing.value = {
    panelId,
    edge,
    startX: e.clientX,
    startY: e.clientY,
    startW: panel.width || 450,
    startH: panel.height || 550,
  };
}

function onResizeMove(e) {
  if (!resizing.value) return;
  const r = resizing.value;
  const dx = e.clientX - r.startX;
  const dy = e.clientY - r.startY;
  let w = r.startW;
  let h = r.startH;

  if (r.edge.includes('e')) w = Math.max(320, r.startW + dx);
  if (r.edge.includes('s')) h = Math.max(300, r.startH + dy);
  if (r.edge.includes('w')) w = Math.max(320, r.startW - dx);
  if (r.edge.includes('n')) h = Math.max(300, r.startH - dy);

  dockStore.resizePanel(r.panelId, w, h);
}

function onResizeUp() {
  resizing.value = null;
}

onMounted(() => {
  gcTimer = setInterval(() => {
    if (typeof window.gc === 'function') {
      try { window.gc(); } catch {}
    }
  }, 60000);

  document.addEventListener('keydown', onGlobalKeyDown, true);
  document.addEventListener('mousemove', onResizeMove);
  document.addEventListener('mouseup', onResizeUp);
});

onUnmounted(() => {
  if (gcTimer) {
    clearInterval(gcTimer);
    gcTimer = null;
  }
  document.removeEventListener('keydown', onGlobalKeyDown, true);
  document.removeEventListener('mousemove', onResizeMove);
  document.removeEventListener('mouseup', onResizeUp);
});
</script>

<template>
  <DockLayout v-if="isEditorRoute" />
  <router-view v-else />
  <CameraFollowPanel v-if="isEditorRoute" />

  <!-- 全局中心面板覆盖层（可缩放） -->
  <template v-for="p in centerPanels" :key="p.id">
    <div class="global-center-overlay" @mousedown.self="dockStore.closePanel(p.id)">
      <div
        class="global-center-overlay-panel"
        :style="{ width: p.width + 'px', height: p.height + 'px' }"
      >
        <DockPanel :panel-id="p.id" :component="getPluginManifest(p.id)?.component" />
        <!-- 缩放句柄 -->
        <div class="resize-handle resize-n"  @mousedown="startResize(p.id, 'n', $event)"></div>
        <div class="resize-handle resize-s"  @mousedown="startResize(p.id, 's', $event)"></div>
        <div class="resize-handle resize-w"  @mousedown="startResize(p.id, 'w', $event)"></div>
        <div class="resize-handle resize-e"  @mousedown="startResize(p.id, 'e', $event)"></div>
        <div class="resize-handle resize-nw" @mousedown="startResize(p.id, 'nw', $event)"></div>
        <div class="resize-handle resize-ne" @mousedown="startResize(p.id, 'ne', $event)"></div>
        <div class="resize-handle resize-sw" @mousedown="startResize(p.id, 'sw', $event)"></div>
        <div class="resize-handle resize-se" @mousedown="startResize(p.id, 'se', $event)"></div>
      </div>
    </div>
  </template>
</template>

<style>
.global-center-overlay {
  position: fixed;
  inset: 0;
  z-index: 100000;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}
.global-center-overlay-panel {
  position: relative;
  max-width: 90vw;
  max-height: 85vh;
  min-width: 320px;
  min-height: 300px;
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── 缩放句柄 ── */
.resize-handle { position: absolute; z-index: 10; }
.resize-n, .resize-s { left: 8px; right: 8px; height: 6px; cursor: ns-resize; }
.resize-n { top: 0; }
.resize-s { bottom: 0; }
.resize-w, .resize-e { top: 8px; bottom: 8px; width: 6px; cursor: ew-resize; }
.resize-w { left: 0; }
.resize-e { right: 0; }
.resize-nw, .resize-ne, .resize-sw, .resize-se { width: 14px; height: 14px; }
.resize-nw { top: 0; left: 0; cursor: nw-resize; }
.resize-ne { top: 0; right: 0; cursor: ne-resize; }
.resize-sw { bottom: 0; left: 0; cursor: sw-resize; }
.resize-se { bottom: 0; right: 0; cursor: se-resize; }
</style>
