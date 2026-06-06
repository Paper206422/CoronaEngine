<template>
  <div class="flex-1 min-h-0 w-full rounded-lg overflow-hidden relative bg-[#282828]/90 flex flex-col text-white font-sans">
    <DockTitleBar
      v-if="!isDocked"
      title="编辑器设置"
      extraClass="bg-[#5b8def]"
      routePath="/SetUp"
      @close="closeFloat"
    />

    <div class="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-3 text-xs">
      <!-- ═══ 工作流与提示 ═══ -->
      <div class="section-header" :class="{ collapsed: !sections.workflow }" @click="sections.workflow = !sections.workflow">
        <span class="arrow">▼</span> 工作流与提示
      </div>
      <div v-show="sections.workflow" class="space-y-3">
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">包菜提示时间</label>
          <div class="flex items-center gap-2">
            <input type="range" min="0.5" max="10" step="0.1" v-model.number="form.cabbage_hint_time" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-14 text-right tabular-nums">{{ form.cabbage_hint_time.toFixed(1) }} 秒</span>
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">自动存档间隔</label>
          <div class="flex items-center gap-2">
            <input type="range" min="1" max="60" step="1" v-model.number="form.autosave_interval" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-14 text-right tabular-nums">{{ form.autosave_interval }} 分钟</span>
          </div>
        </div>
      </div>

      <!-- ═══ 引擎与图形 ═══ -->
      <div class="section-header" :class="{ collapsed: !sections.engine }" @click="sections.engine = !sections.engine">
        <span class="arrow">▼</span> 引擎与图形
      </div>
      <div v-show="sections.engine" class="space-y-3">
        <div class="setting-row">
          <span class="setting-label">垂直同步</span>
          <label class="toggle">
            <input type="checkbox" v-model="form.vsync" />
            <span class="track"></span>
            <span class="thumb"></span>
          </label>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">相机速度</label>
          <div class="flex items-center gap-2">
            <input type="range" min="0.1" max="10" step="0.1" v-model.number="form.camera_speed" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-10 text-right tabular-nums">{{ form.camera_speed.toFixed(1) }}</span>
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">网格对齐</label>
          <div class="flex items-center gap-2">
            <input type="range" min="1" max="200" step="1" v-model.number="form.grid_snap_size" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-10 text-right tabular-nums">{{ form.grid_snap_size.toFixed(0) }}</span>
          </div>
        </div>
      </div>

      <!-- ═══ 音频 ═══ -->
      <div class="section-header" :class="{ collapsed: !sections.audio }" @click="sections.audio = !sections.audio">
        <span class="arrow">▼</span> 音频
      </div>
      <div v-show="sections.audio" class="space-y-3">
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">主音量</label>
          <div class="flex items-center gap-2">
            <input type="range" min="0" max="100" step="1" v-model.number="form.master_volume" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-10 text-right tabular-nums">{{ form.master_volume }}%</span>
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">背景音乐</label>
          <div class="flex items-center gap-2">
            <input type="range" min="0" max="100" step="1" v-model.number="form.bgm_volume" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-10 text-right tabular-nums">{{ form.bgm_volume }}%</span>
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">效果音</label>
          <div class="flex items-center gap-2">
            <input type="range" min="0" max="100" step="1" v-model.number="form.sfx_volume" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-10 text-right tabular-nums">{{ form.sfx_volume }}%</span>
          </div>
        </div>
      </div>

      <!-- ═══ 外观 ═══ -->
      <div class="section-header" :class="{ collapsed: !sections.appearance }" @click="sections.appearance = !sections.appearance">
        <span class="arrow">▼</span> 外观
      </div>
      <div v-show="sections.appearance" class="space-y-3">
        <div class="setting-row">
          <span class="setting-label">界面主题</span>
          <select v-model.number="form.theme_index" class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1.5 text-white focus:border-[#5b8def] outline-none text-xs">
            <option :value="0">暗色</option>
            <option :value="1">亮色</option>
            <option :value="2">古典</option>
          </select>
        </div>
        <div class="setting-row">
          <span class="setting-label">界面语言</span>
          <select v-model.number="form.language_index" class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1.5 text-white focus:border-[#5b8def] outline-none text-xs">
            <option :value="0">中文</option>
            <option :value="1">English</option>
          </select>
        </div>
        <div class="flex flex-col gap-1">
          <label class="text-gray-400">UI 缩放</label>
          <div class="flex items-center gap-2">
            <input type="range" min="0.5" max="2.0" step="0.1" v-model.number="form.ui_scale" class="flex-1 h-1 accent-[#5b8def] cursor-pointer" />
            <span class="text-gray-300 w-10 text-right tabular-nums">{{ form.ui_scale.toFixed(1) }}x</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 保存提示 -->
    <div class="save-badge" :class="{ show: saveVisible }">设置已保存</div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue';
import { appService } from '@/utils/bridge';
import { useDockPanel } from '@/composables/useDockPanel.js';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';

const { closePanel: closeDockPanel, isDocked } = useDockPanel();

const STORAGE_KEY = 'corona_editor_settings';

const defaultSettings = {
  cabbage_hint_time: 3.0,
  autosave_interval: 15,
  vsync: true,
  camera_speed: 2.5,
  grid_snap_size: 50,
  master_volume: 80,
  bgm_volume: 70,
  sfx_volume: 100,
  theme_index: 0,
  language_index: 0,
  ui_scale: 1.0,
};

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...defaultSettings, ...JSON.parse(raw) };
  } catch (e) { /* ignore */ }
  return { ...defaultSettings };
}

const form = reactive(loadSettings());

const sections = reactive({
  workflow: true,
  engine: true,
  audio: true,
  appearance: true,
});

const saveVisible = ref(false);
let saveTimer = null;

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(form));
  } catch (e) { /* ignore */ }
}

function notifyEngine() {
  if (typeof cefQuery !== 'undefined') {
    cefQuery({
      request: JSON.stringify({
        function: 'update_settings',
        module: 'EditorSettings',
        args: [JSON.parse(JSON.stringify(form))],
      }),
      onSuccess: function () {},
      onFailure: function () {},
    });
  }
}

function showSaved() {
  saveVisible.value = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { saveVisible.value = false; }, 1500);
}

watch(form, () => {
  persist();
  notifyEngine();
  showSaved();
}, { deep: true });

const closeFloat = () => {
  window.__settingsOpen = false;
  if (closeDockPanel) { closeDockPanel(); return; }
  appService.removeDockWidgetByRoute('/SetUp').catch(() => {});
};

onMounted(() => {
  notifyEngine();
});
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #444;
  border-radius: 3px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #5b8def;
}

.section-header {
  display: flex; align-items: center;
  font-size: 13px; font-weight: 600;
  color: #8b8d96;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #353740;
  cursor: pointer;
  user-select: none;
}
.section-header.collapsed .arrow { transform: rotate(-90deg); }
.section-header .arrow {
  margin-right: 6px;
  transition: transform 0.2s;
  font-size: 10px;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 28px;
}
.setting-label {
  color: #c8cad4;
  flex-shrink: 0;
  margin-right: 12px;
}

/* 开关 */
.toggle {
  position: relative; width: 40px; height: 22px; cursor: pointer;
}
.toggle input { display: none; }
.toggle .track {
  position: absolute; inset: 0;
  background: #353740; border-radius: 11px;
  transition: 0.2s ease;
}
.toggle input:checked + .track { background: #5b8def; }
.toggle .thumb {
  position: absolute;
  top: 2px; left: 2px;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: #fff;
  transition: 0.2s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
.toggle input:checked ~ .thumb { left: 20px; }

/* 保存提示 */
.save-badge {
  position: absolute;
  bottom: 8px; right: 12px;
  background: #5b8def; color: #fff;
  font-size: 11px; padding: 4px 10px;
  border-radius: 4px;
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.3s, transform 0.3s;
  pointer-events: none;
  z-index: 10;
}
.save-badge.show { opacity: 1; transform: translateY(0); }

input[type="range"] {
  -webkit-appearance: none; appearance: none;
  height: 4px; border-radius: 2px;
  background: #353740; outline: none;
}
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #5b8def;
  cursor: pointer;
}
</style>
