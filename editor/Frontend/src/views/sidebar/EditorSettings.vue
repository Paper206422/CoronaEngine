<template>
  <div class="fui-root">
    <!-- 背景层 -->
    <div class="fui-bg-grid"></div>
    <div class="fui-bg-scan"></div>
    <div class="fui-bg-tags">
      <span class="fui-tag" style="top:8%;left:5%">SYS::CORONA-SETTINGS</span>
      <span class="fui-tag" style="top:15%;right:8%">ASSET-ID-019</span>
      <span class="fui-tag" style="bottom:12%;left:10%">CAM-SPD-001</span>
      <span class="fui-tag" style="bottom:20%;right:5%">MOD::EDITOR-CORE</span>
    </div>

    <!-- 标题栏（非 docked 模式） -->
    <DockTitleBar
      v-if="!isDocked"
      title="编辑器设置"
      extraClass="fui-titlebar"
      routePath="/SetUp"
      @close="closeFloat"
    />

    <!-- 主内容 -->
    <div class="fui-content">

      <!-- 工具栏：返回主页 + 保存状态 -->
      <div class="fui-toolbar">
        <button class="fui-btn-home" @click="goHome">
          <span class="fui-btn-home-icon">◄</span>
          <span>返回主页</span>
        </button>
        <div class="fui-status">
          <span class="fui-status-dot" :class="{ active: saveVisible }"></span>
          <span>{{ saveVisible ? '已保存' : '就绪' }}</span>
        </div>
      </div>

      <!-- 四象限矩阵布局 -->
      <div class="fui-quad-grid">

        <!-- 中心全息核心 -->
        <div class="fui-holo-core">
          <div class="fui-tesseract">
            <div class="fui-tesseract-face fui-tf-front"></div>
            <div class="fui-tesseract-face fui-tf-back"></div>
            <div class="fui-tesseract-face fui-tf-left"></div>
            <div class="fui-tesseract-face fui-tf-right"></div>
            <div class="fui-tesseract-face fui-tf-top"></div>
            <div class="fui-tesseract-face fui-tf-bottom"></div>
            <div class="fui-tesseract-inner"></div>
          </div>
          <div class="fui-crosshair-h"></div>
          <div class="fui-crosshair-v"></div>
        </div>

        <!-- Q1: 工作流与提示 (左上) -->
        <div class="fui-quad fui-quad-tl" :class="{ collapsed: !sections.workflow }">
          <div class="fui-quad-header" @click="sections.workflow = !sections.workflow">
            <span class="fui-quad-icon">◇</span>
            <span class="fui-quad-label">工作流与提示</span>
            <span class="fui-quad-arrow">▼</span>
          </div>
          <div v-show="sections.workflow" class="fui-quad-body">
            <!-- 包菜提示时间 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">包菜提示时间</span>
                <span class="fui-field-val">{{ form.cabbage_hint_time.toFixed(1) }}<small>秒</small></span>
              </div>
              <div class="fui-slider-track">
                <div class="fui-slider-fill" :style="{ width: ((form.cabbage_hint_time - 0.5) / 9.5 * 100) + '%' }"></div>
                <input type="range" min="0.5" max="10" step="0.1" v-model.number="form.cabbage_hint_time" class="fui-slider" />
              </div>
            </div>
            <!-- 自动存档间隔 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">自动存档间隔</span>
                <span class="fui-field-val">{{ form.autosave_interval }}<small>分钟</small></span>
              </div>
              <div class="fui-slider-track">
                <div class="fui-slider-fill" :style="{ width: ((form.autosave_interval - 1) / 59 * 100) + '%' }"></div>
                <input type="range" min="1" max="60" step="1" v-model.number="form.autosave_interval" class="fui-slider" />
              </div>
            </div>
          </div>
        </div>

        <!-- Q2: 引擎与图形 (右上) -->
        <div class="fui-quad fui-quad-tr" :class="{ collapsed: !sections.engine }">
          <div class="fui-quad-header" @click="sections.engine = !sections.engine">
            <span class="fui-quad-icon">◈</span>
            <span class="fui-quad-label">引擎与图形</span>
            <span class="fui-quad-arrow">▼</span>
          </div>
          <div v-show="sections.engine" class="fui-quad-body">
            <!-- 垂直同步 -->
            <div class="fui-field fui-field-row">
              <span class="fui-field-label">垂直同步</span>
              <label class="fui-toggle" :class="{ on: form.vsync }" @click="form.vsync = !form.vsync">
                <span class="fui-toggle-track">
                  <span class="fui-toggle-circuit"></span>
                </span>
                <span class="fui-toggle-thumb"></span>
              </label>
            </div>
            <!-- 相机速度 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">相机速度</span>
                <span class="fui-field-val">{{ form.camera_speed.toFixed(1) }}</span>
              </div>
              <div class="fui-slider-track">
                <div class="fui-slider-fill" :style="{ width: ((form.camera_speed - 0.1) / 9.9 * 100) + '%' }"></div>
                <input type="range" min="0.1" max="10" step="0.1" v-model.number="form.camera_speed" class="fui-slider" />
              </div>
            </div>
            <!-- 网格对齐 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">网格对齐</span>
                <span class="fui-field-val">{{ form.grid_snap_size.toFixed(0) }}</span>
              </div>
              <div class="fui-slider-track">
                <div class="fui-slider-fill" :style="{ width: ((form.grid_snap_size - 1) / 199 * 100) + '%' }"></div>
                <input type="range" min="1" max="200" step="1" v-model.number="form.grid_snap_size" class="fui-slider" />
              </div>
            </div>
          </div>
        </div>

        <!-- Q3: 音频 (左下) -->
        <div class="fui-quad fui-quad-bl" :class="{ collapsed: !sections.audio }">
          <div class="fui-quad-header" @click="sections.audio = !sections.audio">
            <span class="fui-quad-icon">∿</span>
            <span class="fui-quad-label">音频</span>
            <span class="fui-quad-arrow">▼</span>
          </div>
          <div v-show="sections.audio" class="fui-quad-body">
            <!-- 主音量 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">主音量</span>
                <span class="fui-field-val">{{ form.master_volume }}<small>%</small></span>
              </div>
              <div class="fui-slider-track fui-slider-audio">
                <div class="fui-waveform" :style="{ width: form.master_volume + '%' }">
                  <svg class="fui-wave-svg" viewBox="0 0 200 24" preserveAspectRatio="none">
                    <path :d="wavePath(form.master_volume)" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" />
                  </svg>
                </div>
                <input type="range" min="0" max="100" step="1" v-model.number="form.master_volume" class="fui-slider fui-slider-wave" />
              </div>
            </div>
            <!-- 背景音乐 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">背景音乐</span>
                <span class="fui-field-val">{{ form.bgm_volume }}<small>%</small></span>
              </div>
              <div class="fui-slider-track fui-slider-audio">
                <div class="fui-waveform" :style="{ width: form.bgm_volume + '%' }">
                  <svg class="fui-wave-svg" viewBox="0 0 200 24" preserveAspectRatio="none">
                    <path :d="wavePath(form.bgm_volume)" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" />
                  </svg>
                </div>
                <input type="range" min="0" max="100" step="1" v-model.number="form.bgm_volume" class="fui-slider fui-slider-wave" />
              </div>
            </div>
            <!-- 效果音 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">效果音</span>
                <span class="fui-field-val">{{ form.sfx_volume }}<small>%</small></span>
              </div>
              <div class="fui-slider-track fui-slider-audio">
                <div class="fui-waveform" :style="{ width: form.sfx_volume + '%' }">
                  <svg class="fui-wave-svg" viewBox="0 0 200 24" preserveAspectRatio="none">
                    <path :d="wavePath(form.sfx_volume)" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" />
                  </svg>
                </div>
                <input type="range" min="0" max="100" step="1" v-model.number="form.sfx_volume" class="fui-slider fui-slider-wave" />
              </div>
            </div>
          </div>
        </div>

        <!-- Q4: 外观 (右下) -->
        <div class="fui-quad fui-quad-br" :class="{ collapsed: !sections.appearance }">
          <div class="fui-quad-header" @click="sections.appearance = !sections.appearance">
            <span class="fui-quad-icon">◉</span>
            <span class="fui-quad-label">外观</span>
            <span class="fui-quad-arrow">▼</span>
          </div>
          <div v-show="sections.appearance" class="fui-quad-body">
            <!-- 界面主题 - 分段选择器 -->
            <div class="fui-field">
              <span class="fui-field-label">界面主题</span>
              <div class="fui-segment-group">
                <button
                  v-for="(t, i) in themes"
                  :key="i"
                  class="fui-segment"
                  :class="{ active: form.theme_index === i }"
                  @click="form.theme_index = i"
                >{{ t }}</button>
              </div>
            </div>
            <!-- 界面语言 - 分段选择器 -->
            <div class="fui-field">
              <span class="fui-field-label">界面语言</span>
              <div class="fui-segment-group">
                <button
                  v-for="(l, i) in languages"
                  :key="i"
                  class="fui-segment"
                  :class="{ active: form.language_index === i }"
                  @click="form.language_index = i"
                >{{ l }}</button>
              </div>
            </div>
            <!-- UI 缩放 -->
            <div class="fui-field">
              <div class="fui-field-head">
                <span class="fui-field-label">UI 缩放</span>
                <span class="fui-field-val">{{ form.ui_scale.toFixed(1) }}<small>x</small></span>
              </div>
              <div class="fui-slider-track">
                <div class="fui-slider-fill" :style="{ width: ((form.ui_scale - 0.5) / 1.5 * 100) + '%' }"></div>
                <input type="range" min="0.5" max="2.0" step="0.1" v-model.number="form.ui_scale" class="fui-slider" />
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useDockStore } from '@/stores/dockStore.js';
import { useDockPanel } from '@/composables/useDockPanel.js';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';

const router = useRouter();
const dockStore = useDockStore();
const { closePanel: closeDockPanel, isDocked } = useDockPanel();

function goHome() {
  dockStore.closePanel('EditorSettings');
  router.push('/StartScreen');
}

const themes = ['暗色', '亮色', '古典'];
const languages = ['中文', 'English'];

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
};

/** 音频波形路径生成 */
function wavePath(amplitude) {
  const pts = [];
  const scale = amplitude / 100;
  for (let i = 0; i <= 20; i++) {
    const x = (i / 20) * 200;
    const y = 12 + Math.sin(i * 1.8 + Date.now() * 0.002) * 8 * scale + Math.sin(i * 3.3) * 4 * scale;
    pts.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return pts.join(' ');
}

onMounted(() => {
  notifyEngine();
});
</script>

<style scoped>
/* ═══════════════════════════════════════════
   FUI — Futuristic UI Design System
   ═══════════════════════════════════════════ */

/* ── 根容器 ── */
.fui-root {
  flex: 1;
  min-height: 0;
  width: 100%;
  position: relative;
  overflow: hidden;
  background: #020818;
  color: #c8d6e5;
  font-family: 'Segoe UI', system-ui, sans-serif;
  display: flex;
  flex-direction: column;
  border-radius: 8px;
}

/* ── 背景网格 ── */
.fui-bg-grid {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image:
    linear-gradient(rgba(0, 240, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 240, 255, 0.03) 1px, transparent 1px);
  background-size: 32px 32px;
}

/* ── 扫描线 ── */
.fui-bg-scan {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0, 200, 255, 0.008) 2px,
    rgba(0, 200, 255, 0.008) 4px
  );
  animation: scanMove 8s linear infinite;
}
@keyframes scanMove {
  0% { transform: translateY(0); }
  100% { transform: translateY(4px); }
}

/* ── 背景标签 ── */
.fui-bg-tags {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}
.fui-tag {
  position: absolute;
  font-size: 8px;
  font-family: 'Consolas', 'Courier New', monospace;
  color: rgba(0, 200, 255, 0.12);
  letter-spacing: 1px;
  text-transform: uppercase;
}

/* ── 标题栏 ── */
:deep(.fui-titlebar) {
  background: linear-gradient(90deg, #0a1628, #0d2137, #0a1628) !important;
  border-bottom: 1px solid rgba(0, 220, 255, 0.2) !important;
  color: #00e5ff !important;
}

/* ── 内容区 ── */
.fui-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.fui-content::-webkit-scrollbar { width: 4px; }
.fui-content::-webkit-scrollbar-track { background: #020818; }
.fui-content::-webkit-scrollbar-thumb { background: #0a3050; border-radius: 2px; }
.fui-content::-webkit-scrollbar-thumb:hover { background: #0d5080; }

/* ── 工具栏 ── */
.fui-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(0, 200, 255, 0.08);
}
.fui-btn-home {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  background: rgba(0, 200, 255, 0.06);
  border: 1px solid rgba(0, 200, 255, 0.15);
  border-radius: 2px;
  color: #00c8ff;
  font-size: 10px;
  cursor: pointer;
  transition: all 0.2s;
  font-family: inherit;
}
.fui-btn-home:hover {
  background: rgba(0, 200, 255, 0.14);
  border-color: rgba(0, 200, 255, 0.35);
  box-shadow: 0 0 12px rgba(0, 200, 255, 0.15);
}
.fui-btn-home-icon { font-size: 9px; }
.fui-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 9px;
  color: #506070;
}
.fui-status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #304050;
  transition: all 0.3s;
}
.fui-status-dot.active {
  background: #00ff88;
  box-shadow: 0 0 6px #00ff88;
}

/* ── 四象限网格 ── */
.fui-quad-grid {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 40px 1fr;
  grid-template-rows: 1fr 40px 1fr;
  gap: 0;
  min-height: 440px;
  position: relative;
}

/* ── 中心核心区 ── */
.fui-holo-core {
  grid-column: 2;
  grid-row: 2;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5;
}
.fui-crosshair-h, .fui-crosshair-v {
  position: absolute;
  background: rgba(0, 200, 255, 0.1);
}
.fui-crosshair-h {
  width: 200%;
  height: 1px;
  left: -50%;
}
.fui-crosshair-v {
  width: 1px;
  height: 200%;
  top: -50%;
}

/* ── 全息核心（tesseract） ── */
.fui-tesseract {
  width: 32px;
  height: 32px;
  position: relative;
  transform-style: preserve-3d;
  animation: tesseractRotate 8s linear infinite;
}
@keyframes tesseractRotate {
  0% { transform: rotateX(0deg) rotateY(0deg) rotateZ(0deg); }
  100% { transform: rotateX(360deg) rotateY(360deg) rotateZ(360deg); }
}
.fui-tesseract-face {
  position: absolute;
  width: 32px;
  height: 32px;
  border: 1px solid rgba(0, 220, 255, 0.5);
  background: rgba(0, 180, 255, 0.06);
  box-shadow: inset 0 0 8px rgba(0, 200, 255, 0.1), 0 0 10px rgba(0, 200, 255, 0.15);
}
.fui-tf-front  { transform: translateZ(8px); }
.fui-tf-back   { transform: translateZ(-8px); }
.fui-tf-left   { transform: rotateY(90deg) translateZ(8px); }
.fui-tf-right  { transform: rotateY(-90deg) translateZ(8px); }
.fui-tf-top    { transform: rotateX(90deg) translateZ(8px); }
.fui-tf-bottom { transform: rotateX(-90deg) translateZ(8px); }
.fui-tesseract-inner {
  position: absolute;
  width: 12px;
  height: 12px;
  top: 10px;
  left: 10px;
  border: 1px solid rgba(0, 255, 200, 0.4);
  background: rgba(0, 255, 200, 0.04);
  box-shadow: 0 0 14px rgba(0, 255, 200, 0.2);
  transform: translateZ(0px);
}

/* ── 象限面板 ── */
.fui-quad {
  background: rgba(4, 16, 36, 0.7);
  border: 1px solid rgba(0, 180, 255, 0.13);
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: border-color 0.3s;
}
.fui-quad:hover {
  border-color: rgba(0, 200, 255, 0.25);
}
.fui-quad.collapsed .fui-quad-body {
  display: none;
}
.fui-quad.collapsed .fui-quad-arrow {
  transform: rotate(-90deg);
}

.fui-quad-tl { grid-column: 1; grid-row: 1; }
.fui-quad-tr { grid-column: 3; grid-row: 1; }
.fui-quad-bl { grid-column: 1; grid-row: 3; }
.fui-quad-br { grid-column: 3; grid-row: 3; }

/* ── 象限标题 ── */
.fui-quad-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: rgba(0, 160, 255, 0.06);
  border-bottom: 1px solid rgba(0, 180, 255, 0.1);
  cursor: pointer;
  user-select: none;
  flex-shrink: 0;
}
.fui-quad-header:hover {
  background: rgba(0, 180, 255, 0.1);
}
.fui-quad-icon {
  font-size: 14px;
  color: #00d4ff;
  text-shadow: 0 0 6px rgba(0, 212, 255, 0.4);
  width: 18px;
  text-align: center;
}
.fui-quad-label {
  flex: 1;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #80c8e0;
}
.fui-quad-arrow {
  font-size: 8px;
  color: #4080a0;
  transition: transform 0.25s;
}

/* ── 象限内容 ── */
.fui-quad-body {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  flex: 1;
}
.fui-quad-body::-webkit-scrollbar { width: 3px; }
.fui-quad-body::-webkit-scrollbar-thumb { background: #0a3050; border-radius: 2px; }

/* ── 字段 ── */
.fui-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fui-field-row {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}
.fui-field-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.fui-field-label {
  font-size: 10px;
  color: #6a90b0;
  letter-spacing: 0.6px;
  text-transform: uppercase;
}
.fui-field-val {
  font-size: 12px;
  font-weight: 600;
  color: #00e5ff;
  font-family: 'Consolas', 'Courier New', monospace;
  text-shadow: 0 0 6px rgba(0, 229, 255, 0.3);
}
.fui-field-val small {
  font-size: 9px;
  font-weight: 400;
  color: #5090a0;
  margin-left: 2px;
}

/* ── 自定义滑块 ── */
.fui-slider-track {
  position: relative;
  height: 18px;
  display: flex;
  align-items: center;
  background: rgba(0, 20, 40, 0.8);
  border: 1px solid rgba(0, 160, 255, 0.15);
  border-radius: 2px;
  overflow: hidden;
}
.fui-slider-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: linear-gradient(90deg, rgba(0, 200, 255, 0.12), rgba(0, 240, 200, 0.18));
  border-right: 1px solid rgba(0, 220, 255, 0.3);
  pointer-events: none;
  transition: width 0.1s ease;
}
.fui-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 100%;
  background: transparent;
  outline: none;
  cursor: pointer;
  position: relative;
  z-index: 1;
  margin: 0;
}
.fui-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 10px;
  height: 22px;
  background: linear-gradient(180deg, #00e5ff, #0080aa);
  border: 1px solid #00e5ff;
  border-radius: 2px;
  cursor: pointer;
  box-shadow: 0 0 10px rgba(0, 229, 255, 0.5), 0 0 20px rgba(0, 229, 255, 0.2);
  position: relative;
}
.fui-slider::-webkit-slider-thumb::after {
  content: '';
  position: absolute;
  inset: 2px;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 1px,
    rgba(0, 255, 200, 0.3) 1px,
    rgba(0, 255, 200, 0.3) 2px
  );
}

/* ── 音频滑块波形 ── */
.fui-slider-audio {
  position: relative;
}
.fui-waveform {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
  transition: width 0.1s ease;
}
.fui-wave-svg {
  width: 100%;
  height: 100%;
  color: rgba(0, 255, 180, 0.5);
}
.fui-slider-wave::-webkit-slider-thumb {
  background: linear-gradient(180deg, #00ffaa, #008855);
  border-color: #00ffaa;
  box-shadow: 0 0 10px rgba(0, 255, 170, 0.5);
}

/* ── 霓虹开关 ── */
.fui-toggle {
  position: relative;
  width: 44px;
  height: 24px;
  cursor: pointer;
  display: flex;
  align-items: center;
}
.fui-toggle-track {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 12px;
  background: #0a1a2e;
  border: 1px solid rgba(0, 160, 255, 0.25);
  transition: all 0.3s;
  overflow: hidden;
}
.fui-toggle.on .fui-toggle-track {
  background: rgba(0, 200, 255, 0.1);
  border-color: #00c8ff;
  box-shadow: 0 0 12px rgba(0, 200, 255, 0.25), inset 0 0 8px rgba(0, 200, 255, 0.08);
}
.fui-toggle-circuit {
  position: absolute;
  left: 0;
  top: 50%;
  width: 28px;
  height: 1px;
  background: rgba(0, 200, 255, 0.3);
  transform: translateY(-50%);
  transition: all 0.3s;
}
.fui-toggle.on .fui-toggle-circuit {
  background: #00e5ff;
  width: 34px;
  box-shadow: 0 0 6px #00e5ff;
}
.fui-toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1a3a50, #0a1a2e);
  border: 1px solid rgba(0, 180, 255, 0.4);
  transition: all 0.3s;
  box-shadow: 0 0 4px rgba(0, 180, 255, 0.2);
}
.fui-toggle.on .fui-toggle-thumb {
  left: 22px;
  background: linear-gradient(135deg, #00e5ff, #006080);
  border-color: #00e5ff;
  box-shadow: 0 0 12px rgba(0, 229, 255, 0.5);
}

/* ── 分段选择器 ── */
.fui-segment-group {
  display: flex;
  border: 1px solid rgba(0, 180, 255, 0.2);
  border-radius: 3px;
  overflow: hidden;
  background: rgba(0, 20, 40, 0.6);
}
.fui-segment {
  flex: 1;
  padding: 5px 4px;
  font-size: 10px;
  font-family: inherit;
  color: #5080a0;
  background: transparent;
  border: none;
  border-right: 1px solid rgba(0, 180, 255, 0.1);
  cursor: pointer;
  transition: all 0.2s;
  letter-spacing: 0.5px;
  text-align: center;
}
.fui-segment:last-child { border-right: none; }
.fui-segment:hover {
  background: rgba(0, 200, 255, 0.08);
  color: #80d0f0;
}
.fui-segment.active {
  background: rgba(0, 210, 255, 0.15);
  color: #00e5ff;
  font-weight: 600;
  box-shadow: inset 0 1px 0 rgba(0, 229, 255, 0.3);
  text-shadow: 0 0 6px rgba(0, 229, 255, 0.3);
}
</style>
