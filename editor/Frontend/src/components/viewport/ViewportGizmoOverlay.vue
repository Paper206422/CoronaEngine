<template>
  <div
    v-if="visible"
    class="absolute inset-0 z-20 pointer-events-none select-none"
    data-viewport-gizmo-overlay
  >
    <div
      class="absolute left-3 top-3 pointer-events-auto flex items-center gap-1 rounded border border-white/10 bg-[#15181d]/80 p-1 shadow-lg backdrop-blur-sm"
      @pointerdown.stop
      @mousedown.stop
    >
      <button
        v-for="item in modeItems"
        :key="item.mode"
        class="h-7 min-w-9 rounded px-2 text-[11px] font-medium"
        :class="renderModel.mode === item.mode ? 'bg-[#4b5563] text-white' : 'text-[#cbd5e1] hover:bg-white/10'"
        type="button"
        :title="item.title"
        @click="$emit('mode-change', item.mode)"
      >
        {{ item.label }}
      </button>
    </div>

    <svg class="absolute inset-0 h-full w-full overflow-visible">
      <g v-for="ring in renderModel.rings" :key="`ring-${ring.name}`">
        <path
          :d="ring.path"
          fill="none"
          stroke="transparent"
          stroke-width="18"
          class="pointer-events-auto cursor-grab active:cursor-grabbing"
          @pointerdown.stop.prevent="$emit('drag-start', 'rotate', ring.name, $event)"
        />
        <path
          :d="ring.path"
          fill="none"
          :stroke="ring.color"
          stroke-width="3"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="pointer-events-none drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]"
        />
      </g>

      <g v-for="axis in renderModel.axes" :key="`axis-${axis.name}`">
        <line
          :x1="axis.start[0]"
          :y1="axis.start[1]"
          :x2="axis.end[0]"
          :y2="axis.end[1]"
          stroke="transparent"
          stroke-width="18"
          stroke-linecap="round"
          class="pointer-events-auto cursor-grab active:cursor-grabbing"
          @pointerdown.stop.prevent="$emit('drag-start', renderModel.mode, axis.name, $event)"
        />
        <line
          :x1="axis.start[0]"
          :y1="axis.start[1]"
          :x2="axis.end[0]"
          :y2="axis.end[1]"
          :stroke="axis.color"
          stroke-width="3"
          stroke-linecap="round"
          class="pointer-events-none drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]"
        />
        <polygon
          v-if="axis.handle === 'arrow'"
          :points="arrowPoints(axis)"
          :fill="axis.color"
          class="pointer-events-none drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]"
        />
        <rect
          v-else
          :x="axis.end[0] - 6"
          :y="axis.end[1] - 6"
          width="12"
          height="12"
          rx="1.5"
          :fill="axis.color"
          class="pointer-events-none drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]"
        />
        <text
          :x="axis.label[0]"
          :y="axis.label[1]"
          text-anchor="middle"
          dominant-baseline="middle"
          :fill="axis.color"
          class="pointer-events-none text-[11px] font-bold drop-shadow-[0_1px_2px_rgba(0,0,0,0.9)]"
        >
          {{ axis.name.toUpperCase() }}
        </text>
      </g>

      <rect
        v-if="renderModel.showUniformScale"
        :x="renderModel.center[0] - 7"
        :y="renderModel.center[1] - 7"
        width="14"
        height="14"
        rx="2"
        class="pointer-events-auto cursor-grab fill-white/95 stroke-[#111820] drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)] active:cursor-grabbing"
        stroke-width="2"
        @pointerdown.stop.prevent="$emit('drag-start', 'scale', 'uniform', $event)"
      />
      <circle
        v-else-if="renderModel.center"
        :cx="renderModel.center[0]"
        :cy="renderModel.center[1]"
        r="4"
        class="pointer-events-none fill-white/90 stroke-[#111820] drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]"
        stroke-width="1.5"
      />
      <rect
        v-if="renderModel.showUniformScale"
        :x="renderModel.center[0] - 11"
        :y="renderModel.center[1] - 11"
        width="22"
        height="22"
        rx="4"
        fill="transparent"
        class="pointer-events-auto cursor-grab active:cursor-grabbing"
        @pointerdown.stop.prevent="$emit('drag-start', 'scale', 'uniform', $event)"
      />
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { buildGizmoRenderModel } from '@/utils/viewportGizmoView.js';

const props = defineProps({
  state: { type: Object, default: null },
  mode: { type: String, default: 'move' },
  screenOffset: { type: Object, default: () => ({ x: 0, y: 0 }) },
});

defineEmits(['mode-change', 'drag-start']);

const modeItems = [
  { mode: 'move', label: 'Move', title: '移动' },
  { mode: 'scale', label: 'Scale', title: '缩放' },
  { mode: 'rotate', label: 'Rotate', title: '旋转' },
];

const renderModel = computed(() =>
  buildGizmoRenderModel(props.state, props.mode, props.screenOffset)
);

const arrowPoints = (axis) => {
  const dx = axis.end[0] - axis.start[0];
  const dy = axis.end[1] - axis.start[1];
  const length = Math.max(1, Math.sqrt(dx * dx + dy * dy));
  const ux = dx / length;
  const uy = dy / length;
  const px = -uy;
  const py = ux;
  const tip = axis.end;
  const baseX = tip[0] - ux * 14;
  const baseY = tip[1] - uy * 14;
  return [
    [tip[0], tip[1]],
    [baseX + px * 6, baseY + py * 6],
    [baseX - px * 6, baseY - py * 6],
  ]
    .map((point) => point.join(','))
    .join(' ');
};

const visible = computed(() => renderModel.value.visible);
</script>
