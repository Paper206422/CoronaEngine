<template>
  <div class="flex flex-col flex-1 min-h-0 w-full rounded-lg overflow-hidden relative bg-[#282828]/90">
    <DockTitleBar
      v-if="!isDocked"
      title="局域网聊天"
      extraClass="bg-[#84A65B]"
      routePath="/AITalkBar"
      @close="closeFloat"
    />

    <!-- 局域网聊天（单一模式） -->
    <div
      class="w-full bg-[#282828]/90"
      style="height: calc(100vh - 80px)"
    >
      <RoomPanel />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';
import RoomPanel from './lanchat/RoomPanel.vue';
import lanchat from '@/stores/lanchat.js';
import { useDockPanel } from '@/composables/useDockPanel.js';
import { coronaEventBus } from '@/utils/eventBus.js';

const { closePanel: closeDockPanel, isDocked } = useDockPanel();

// 局域网聊天室事件：C++ NetworkSystem 经 __coronaEmit('lanchat-event', event) 推送，
// __coronaEmit → coronaEventBus.emit('lanchat-event', event) → 本 handler。
const onLanchatEvent = (payload) => {
  lanchat.handleEvent(payload);
};

onMounted(() => {
  coronaEventBus.on('lanchat-event', onLanchatEvent);
});

onUnmounted(() => {
  coronaEventBus.off('lanchat-event', onLanchatEvent);
});

function closeFloat() {
  closeDockPanel();
}
</script>
