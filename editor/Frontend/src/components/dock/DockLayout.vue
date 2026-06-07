<template>
  <div class="dock-root">
    <!-- Top row: left | center | right -->
    <div class="dock-row">
      <!-- LEFT ZONE -->
      <template v-if="leftPanels.length > 0">
        <div class="dock-zone-v" :style="{ width: leftWidth + 'px' }">
          <DockPanel
            v-for="p in leftPanels"
            :key="p.id"
            :panel-id="p.id"
            :component="getComponent(p.id)"
          />
        </div>
        <div class="dock-sep-v" @mousedown="startResize('left', $event)"></div>
      </template>

      <!-- CENTER ZONE -->
      <div class="dock-zone-center">
        <router-view />
      </div>

      <!-- RIGHT ZONE -->
      <template v-if="rightPanels.length > 0">
        <div class="dock-sep-v" @mousedown="startResize('right', $event)"></div>
        <div class="dock-zone-v" :style="{ width: rightWidth + 'px' }">
          <DockPanel
            v-for="p in rightPanels"
            :key="p.id"
            :panel-id="p.id"
            :component="getComponent(p.id)"
          />
        </div>
      </template>
    </div>

    <!-- BOTTOM ZONE -->
    <template v-if="bottomPanels.length > 0">
      <div class="dock-sep-h" @mousedown="startResize('bottom', $event)"></div>
      <div class="dock-zone-bottom" :style="{ height: bottomHeight + 'px' }">
        <div class="dock-bottom-row">
          <DockPanel
            v-for="p in bottomPanels"
            :key="p.id"
            :panel-id="p.id"
            :component="getComponent(p.id)"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue';
import { useDockStore } from '@/stores/dockStore.js';
import { getPluginManifest } from '@/config/pluginManifest.js';
import DockPanel from './DockPanel.vue';

const dockStore = useDockStore();

const leftPanels = computed(() => dockStore.panelsByZone('left'));
const rightPanels = computed(() => dockStore.panelsByZone('right'));
const bottomPanels = computed(() => dockStore.panelsByZone('bottom'));

const leftWidth = ref(260);
const rightWidth = ref(300);
const bottomHeight = ref(200);

const MIN_SIDE = 150;
const MIN_BOTTOM = 80;

function getComponent(panelId) {
  return getPluginManifest(panelId)?.component ?? null;
}

let resizing = null;

function startResize(zone, e) {
  resizing = { zone, startX: e.clientX, startY: e.clientY };
  e.preventDefault();
}

function onMouseMove(e) {
  if (!resizing) return;
  const dx = e.clientX - resizing.startX;
  const dy = e.clientY - resizing.startY;

  if (resizing.zone === 'left') {
    leftWidth.value = Math.max(MIN_SIDE, leftWidth.value + dx);
  } else if (resizing.zone === 'right') {
    rightWidth.value = Math.max(MIN_SIDE, rightWidth.value - dx);
  } else if (resizing.zone === 'bottom') {
    bottomHeight.value = Math.max(MIN_BOTTOM, bottomHeight.value - dy);
  }
  resizing.startX = e.clientX;
  resizing.startY = e.clientY;
}

function onMouseUp() {
  resizing = null;
}

onMounted(() => {
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
});

onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove);
  window.removeEventListener('mouseup', onMouseUp);
});
</script>

<style scoped>
.dock-root {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  contain: layout style;
}

.dock-row {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  contain: layout style;
}

.dock-zone-v {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
  background: #1a1a2e;
  contain: layout style;
}

.dock-zone-center {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  contain: layout style;
}

.dock-zone-bottom {
  overflow: hidden;
  flex-shrink: 0;
  background: #1a1a2e;
  contain: layout style;
}

.dock-bottom-row {
  display: flex;
  height: 100%;
}

.dock-sep-v {
  width: 4px;
  flex-shrink: 0;
  background: #3c3c3c;
  cursor: col-resize;
  z-index: 10;
}
.dock-sep-v:hover {
  background: #ec4899;
}

.dock-sep-h {
  height: 4px;
  flex-shrink: 0;
  background: #3c3c3c;
  cursor: row-resize;
  z-index: 10;
}
.dock-sep-h:hover {
  background: #ec4899;
}
</style>
