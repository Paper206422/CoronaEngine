<script setup>
import { onMounted, onUnmounted } from 'vue';
import { appService } from './utils/bridge.js';

let gcTimer = null;

function isSettingsOpen() {
  return window.__settingsOpen === true;
}

function onGlobalKeyDown(event) {
  if (event.key === 'Escape' || event.code === 'Escape') {
    if (isSettingsOpen()) {
      appService.removeDockWidgetByRoute('/SetUp').then(() => {
        window.__settingsOpen = false;
      }).catch(() => {});
    } else {
      appService.addDockWidget('/SetUp', 'center', 450, 550, false).then(() => {
        window.__settingsOpen = true;
      }).catch(() => {});
    }
  }
}

onMounted(() => {
  // 每 60 秒触发 JS 垃圾回收（如果环境支持）
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
  <router-view></router-view>
</template>

<style scoped></style>
