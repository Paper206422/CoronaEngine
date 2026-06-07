<script setup>
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute } from 'vue-router';
import { useDockStore } from '@/stores/dockStore.js';
import DockLayout from '@/components/dock/DockLayout.vue';
import CameraFollowPanel from '@/components/panels/CameraFollowPanel.vue';
import '@/utils/eventBus.js'; // init window.__coronaEmit

const route = useRoute();
const dockStore = useDockStore();

// DockLayout + 摄像机跟随面板只在编辑器主页面显示，StartScreen / launcher 等不显示
const isEditorRoute = computed(() => route.path === '/');

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

  document.addEventListener('keydown', onGlobalKeyDown, { passive: true });
});

onUnmounted(() => {
  if (gcTimer) {
    clearInterval(gcTimer);
    gcTimer = null;
  }
  document.removeEventListener('keydown', onGlobalKeyDown);
});
</script>

<template>
  <DockLayout v-if="isEditorRoute" />
  <router-view v-else />
  <CameraFollowPanel v-if="isEditorRoute" />
</template>
