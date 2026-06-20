<template>
  <div class="text-sm">
    <!-- 人类成员 -->
    <div class="px-2 pb-1 text-gray-400">成员</div>
    <div
      v-for="(m, idx) in members"
      :key="'m-' + idx"
      class="px-2 py-1.5 truncate text-gray-200"
    >
      {{ m }}
    </div>

    <!-- AI 助手 -->
    <div v-if="agents.length" class="px-2 pt-2 pb-1 text-gray-400 border-t border-gray-700 mt-1">
      AI 助手
    </div>
    <div
      v-for="a in agents"
      :key="'a-' + a.agent_id"
      class="px-2 py-1.5 flex items-center justify-between text-gray-200"
    >
      <span class="truncate">🤖 {{ a.name }}</span>
      <button
        v-if="a.owner === peerId"
        class="ml-1 text-red-400 hover:text-red-300"
        title="移除"
        @click="$emit('remove-agent', a.agent_id)"
      >
        ✕
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  members: { type: Array, default: () => [] },
  agents: { type: Array, default: () => [] },
  peerId: { type: String, default: '' },
});
defineEmits(['remove-agent']);
</script>
