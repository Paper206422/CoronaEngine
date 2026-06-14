<script setup>
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute } from 'vue-router';
import { useDockStore } from '@/stores/dockStore.js';
import { getPluginManifest } from '@/config/pluginManifest.js';
import DockLayout from '@/components/dock/DockLayout.vue';
import DockPanel from '@/components/dock/DockPanel.vue';
import CameraFollowPanel from '@/components/panels/CameraFollowPanel.vue';
import '@/utils/eventBus.js'; // init window.__coronaEmit

const route = useRoute();
const dockStore = useDockStore();

// DockLayout + 摄像机跟随面板只在编辑器主页面显示，StartScreen / launcher 等不显示
const isEditorRoute = computed(() => route.path === '/');

const centerPanels = computed(() => dockStore.panelsByZone('center'));

let gcTimer = null;

function onGlobalKeyDown(event) {
  if (event.key === 'Escape' || event.code === 'Escape') {
    dockStore.togglePanel('EditorSettings');
  }
}

onMounted(() => {
  gcTimer = setInterval(() => {
    if (typeof window.gc === 'function') {
      try {
        window.gc();
      } catch {}
    }
  }, 60000);

  document.addEventListener('keydown', onGlobalKeyDown, true);
});

onUnmounted(() => {
  if (gcTimer) {
    clearInterval(gcTimer);
    gcTimer = null;
  }
  document.removeEventListener('keydown', onGlobalKeyDown, true);
});
</script>

<template>
  <DockLayout v-if="isEditorRoute" />
  <router-view v-else />
  <CameraFollowPanel v-if="isEditorRoute" />

  <!-- 全局中心面板覆盖层（所有页面可用） -->
  <template v-for="p in centerPanels" :key="p.id">
    <div class="global-center-overlay" @mousedown.self="dockStore.closePanel(p.id)">
      <div class="global-center-overlay-panel" :style="{ width: p.width + 'px', height: p.height + 'px' }">
        <DockPanel :panel-id="p.id" :component="getPluginManifest(p.id)?.component" />
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
  max-width: 90vw;
  max-height: 85vh;
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
