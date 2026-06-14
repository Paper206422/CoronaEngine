<template>
  <div class="tactical-panel">
    <DockTitleBar
      v-if="!isDocked"
      title="编辑器设置"
      extraClass="bg-[#3d4d2e]"
      routePath="/SetUp"
      @close="closeFloat"
    />

    <div class="panel-body">
      <!-- ═══════════ 2×2 GRID ═══════════ -->
      <div class="grid-2x2">
        <!-- Grid dividing lines -->
        <div class="grid-line grid-line-h"></div>
        <div class="grid-line grid-line-v"></div>

        <!-- Center mechanical emblem -->
        <div class="center-emblem">
          <div class="emblem-ring">
            <svg class="emblem-gear" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
              <!-- Outer toothed ring -->
              <circle cx="32" cy="32" r="29" stroke="currentColor" stroke-width="2.5" fill="none" opacity="0.8"/>
              <!-- 8 gear teeth -->
              <g stroke="currentColor" stroke-width="2.2" fill="none" opacity="0.9">
                <line x1="32" y1="1"  x2="32" y2="7"/>
                <line x1="54" y1="10" x2="50" y2="14"/>
                <line x1="63" y1="32" x2="57" y2="32"/>
                <line x1="54" y1="54" x2="50" y2="50"/>
                <line x1="32" y1="63" x2="32" y2="57"/>
                <line x1="10" y1="54" x2="14" y2="50"/>
                <line x1="1"  y1="32" x2="7" y2="32"/>
                <line x1="10" y1="10" x2="14" y2="14"/>
              </g>
              <!-- Inner hexagonal aperture -->
              <polygon points="32,18 44,25 44,39 32,46 20,39 20,25"
                       stroke="currentColor" stroke-width="1.3" fill="none"
                       stroke-linejoin="round" opacity="0.7"/>
              <!-- Center hub dot -->
              <circle cx="32" cy="32" r="4" fill="currentColor" opacity="0.55"/>
              <circle cx="32" cy="32" r="2" fill="#181c13"/>
            </svg>
          </div>
        </div>

        <!-- ═══ Q1: 左上 · 存档设置 ═══ -->
        <div class="quadrant q1">
          <div class="quadrant-header">
            <span class="quadrant-diamond"></span>
            <span class="quadrant-title">存档设置</span>
            <span class="quadrant-subtitle">ARCHIVE</span>
          </div>
          <div class="quadrant-body">
            <!-- Autosave interval stepper -->
            <div class="control-group">
              <label class="control-label">自动保存间隔</label>
              <div class="stepper-row">
                <button class="stepper-btn" @click="stepAutosave(-1)" :disabled="form.autosave_interval <= 1">−</button>
                <div class="stepper-value-box">
                  <span class="stepper-number">{{ form.autosave_interval }}</span>
                </div>
                <button class="stepper-btn" @click="stepAutosave(1)" :disabled="form.autosave_interval >= 60">+</button>
                <span class="stepper-unit">分钟</span>
              </div>
            </div>

            <!-- Hint text -->
            <p class="hint-text">新建存档 · 指定位置、名称</p>

            <!-- Additional: VSync toggle -->
            <div class="control-group">
              <div class="toggle-row">
                <span class="control-label">垂直同步</span>
                <label class="toggle-switch">
                  <input type="checkbox" v-model="form.vsync" />
                  <span class="toggle-track"></span>
                </label>
              </div>
            </div>
          </div>
        </div>

        <!-- ═══ Q2: 右上 · 网络与AI ═══ -->
        <div class="quadrant q2">
          <div class="quadrant-header">
            <span class="quadrant-diamond"></span>
            <span class="quadrant-title">网络与AI</span>
            <span class="quadrant-subtitle">NETWORK · AI</span>
          </div>
          <div class="quadrant-body">
            <!-- LAN Password -->
            <div class="control-group">
              <label class="control-label">局域网密码设置</label>
              <input
                class="input-box"
                type="text"
                v-model="form.lan_password"
                placeholder="输入局域网密码..."
              />
            </div>

            <!-- AI Tips toggle -->
            <div class="control-group">
              <div class="toggle-row">
                <span class="control-label">AI 提示</span>
                <label class="toggle-switch">
                  <input type="checkbox" v-model="form.ai_tips_enabled" />
                  <span class="toggle-track"></span>
                </label>
              </div>
            </div>

            <!-- AI Tips frequency dropdown -->
            <div class="control-group">
              <label class="control-label">AI 提示频率</label>
              <div class="select-wrapper">
                <select v-model="form.ai_tips_frequency">
                  <option value="high">高</option>
                  <option value="medium">中</option>
                  <option value="low">低</option>
                </select>
              </div>
            </div>

            <!-- AI hint time (numerical backing, hidden but kept in sync) -->
            <div class="control-group">
              <label class="control-label">包菜提示间隔</label>
              <div class="slider-row">
                <input
                  type="range"
                  min="0.5" max="10" step="0.1"
                  v-model.number="form.cabbage_hint_time"
                  class="slider"
                />
                <span class="slider-value">{{ form.cabbage_hint_time.toFixed(1) }}s</span>
              </div>
            </div>
          </div>
        </div>

        <!-- ═══ Q3: 左下 · 音频监视 ═══ -->
        <div class="quadrant q3">
          <div class="quadrant-header">
            <span class="quadrant-diamond"></span>
            <span class="quadrant-title">音频监视</span>
            <span class="quadrant-subtitle">AUDIO MONITOR</span>
          </div>
          <div class="quadrant-body">
            <!-- Master Volume -->
            <div class="control-group">
              <div class="slider-label-row">
                <span class="control-label">主音量</span>
                <span class="slider-percent">{{ form.master_volume }}%</span>
              </div>
              <input
                type="range" min="0" max="100" step="1"
                v-model.number="form.master_volume"
                class="slider"
              />
            </div>

            <!-- BGM Volume -->
            <div class="control-group">
              <div class="slider-label-row">
                <span class="control-label">背景音乐</span>
                <span class="slider-percent">{{ form.bgm_volume }}%</span>
              </div>
              <input
                type="range" min="0" max="100" step="1"
                v-model.number="form.bgm_volume"
                class="slider"
              />
            </div>

            <!-- SFX Volume -->
            <div class="control-group">
              <div class="slider-label-row">
                <span class="control-label">效果音</span>
                <span class="slider-percent">{{ form.sfx_volume }}%</span>
              </div>
              <input
                type="range" min="0" max="100" step="1"
                v-model.number="form.sfx_volume"
                class="slider"
              />
            </div>
          </div>
        </div>

        <!-- ═══ Q4: 右下 · 外观与操作 ═══ -->
        <div class="quadrant q4">
          <div class="quadrant-header">
            <span class="quadrant-diamond"></span>
            <span class="quadrant-title">外观与操作</span>
            <span class="quadrant-subtitle">APPEARANCE</span>
          </div>
          <div class="quadrant-body">
            <!-- Theme dropdown -->
            <div class="control-group">
              <label class="control-label">界面主题</label>
              <div class="select-wrapper">
                <select v-model.number="form.theme_index">
                  <option :value="0">暗色</option>
                  <option :value="1">亮色</option>
                  <option :value="2">古典</option>
                </select>
              </div>
            </div>

            <!-- Language dropdown -->
            <div class="control-group">
              <label class="control-label">界面语言</label>
              <div class="select-wrapper">
                <select v-model.number="form.language_index">
                  <option :value="0">中文</option>
                  <option :value="1">English</option>
                </select>
              </div>
            </div>

            <!-- UI Scale (text display) -->
            <div class="control-group">
              <label class="control-label">UI 缩放</label>
              <div class="scale-display">
                <span class="scale-value">{{ form.ui_scale.toFixed(1) }}x</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ═══════════ BUTTON ROW ═══════════ -->
      <div class="button-row">
        <button class="btn btn-cancel" @click="handleExit">退出</button>
        <button class="btn btn-ghost" @click="goHome">回到主页</button>
        <button class="btn btn-primary" @click="handleSaveArchive">保存（新建存档）</button>
      </div>
    </div>

    <!-- 保存提示 badge -->
    <div class="save-badge" :class="{ show: saveVisible }">设置已保存</div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue';
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

const STORAGE_KEY = 'corona_editor_settings';

const defaultSettings = {
  // ── 存档 ──
  autosave_interval: 15,
  // ── 网络与AI ──
  lan_password: '',
  ai_tips_enabled: true,
  ai_tips_frequency: 'medium',   // 'high' | 'medium' | 'low'
  cabbage_hint_time: 3.0,
  // ── 引擎与图形 ──
  vsync: true,
  camera_speed: 2.5,
  grid_snap_size: 50,
  // ── 音频 ──
  master_volume: 80,
  bgm_volume: 70,
  sfx_volume: 100,
  // ── 外观 ──
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

// ── Stepper for autosave interval ──
function stepAutosave(delta) {
  const next = form.autosave_interval + delta;
  if (next >= 1 && next <= 60) {
    form.autosave_interval = next;
  }
}

// ── Save archive action ──
function handleSaveArchive() {
  persist();
  notifyEngine();
  showSaved();
}

// ── Exit action ──
function handleExit() {
  if (closeDockPanel) {
    closeDockPanel();
  } else {
    window.__settingsOpen = false;
  }
}

const closeFloat = () => {
  window.__settingsOpen = false;
  if (closeDockPanel) { closeDockPanel(); return; }
};

onMounted(() => {
  notifyEngine();
});
</script>

<style scoped>
/* ═══════════════════════════════════════════
   TACOM · 军工战术终端 — 编辑器设置面板
   ═══════════════════════════════════════════ */

/* ── CSS Variables ── */
.tactical-panel {
  --bg-root:       #131610;
  --bg-surface:    #1a1e16;
  --bg-input:      #161a12;
  --bg-btn:        #2e3824;
  --bg-btn-hover:  #3d4a32;
  --grid-color:    #2a3520;
  --border:        #38442c;
  --border-thick:  #465636;
  --text-primary:  #c4d0a8;
  --text-muted:    #6e7d56;
  --text-label:    #8a9a6e;
  --accent:        #5a7042;
  --accent-hover:  #6d8552;
  --toggle-off:    #2c3022;
  --toggle-on:     #4e6636;
  --slider-track:  #222817;
  --slider-fill:   #4e6636;
  --danger-border: #5a4038;
  --danger-bg:     #3d2822;
  --danger-hover:  #5a3830;
  --emblem:        #4e6438;

  flex: 1;
  min-height: 0;
  width: 100%;
  border-radius: 4px;
  overflow: hidden;
  position: relative;
  background: var(--bg-root);
  display: flex;
  flex-direction: column;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', 'PingFang SC', sans-serif;
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
}

/* CRT scanline texture */
.tactical-panel::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 50;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.025) 2px,
    rgba(0,0,0,0.025) 4px
  );
  border-radius: inherit;
}

/* ── Panel Body ── */
.panel-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* ═══════════════════════════════════════════
   2×2 GRID
   ═══════════════════════════════════════════ */
.grid-2x2 {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  position: relative;
  min-height: 0;
}

/* ── Grid Dividing Lines ── */
.grid-line {
  position: absolute;
  background: var(--grid-color);
  pointer-events: none;
  z-index: 5;
}
.grid-line-h {
  left: 0;
  right: 0;
  top: 50%;
  height: 2px;
  transform: translateY(-1px);
}
.grid-line-v {
  top: 0;
  bottom: 0;
  left: 50%;
  width: 2px;
  transform: translateX(-1px);
}

/* Hash marks at edges of grid lines */
.grid-line-h::before,
.grid-line-h::after {
  content: '';
  position: absolute;
  background: var(--grid-color);
  top: -4px;
  width: 10px;
  height: 10px;
}
.grid-line-h::before { left: 0; }
.grid-line-h::after  { right: 0; }

.grid-line-v::before,
.grid-line-v::after {
  content: '';
  position: absolute;
  background: var(--grid-color);
  left: -4px;
  width: 10px;
  height: 10px;
}
.grid-line-v::before { top: 0; }
.grid-line-v::after  { bottom: 0; }

/* ── Center Emblem ── */
.center-emblem {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 10;
  pointer-events: none;
}
.emblem-ring {
  width: 56px;
  height: 56px;
  background: var(--bg-surface);
  border: 2px solid var(--border-thick);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 0 5px var(--bg-root);
}
.emblem-gear {
  width: 32px;
  height: 32px;
  color: var(--emblem);
  animation: gear-spin 24s linear infinite;
}
@keyframes gear-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* ═══════════════════════════════════════════
   QUADRANTS
   ═══════════════════════════════════════════ */
.quadrant {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  padding: 18px 16px;
  min-height: 0;
  overflow: hidden;
}

/* Inner padding offsets so content doesn't overlap center emblem */
.q1 { padding-right:  44px; padding-bottom: 44px; }
.q2 { padding-left:   44px; padding-bottom: 44px; }
.q3 { padding-right:  44px; padding-top:    44px; }
.q4 { padding-left:   44px; padding-top:    44px; }

/* ── Quadrant Header ── */
.quadrant-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  padding-bottom: 7px;
  border-bottom: 1px solid var(--grid-color);
  flex-shrink: 0;
}
.quadrant-diamond {
  width: 7px;
  height: 7px;
  background: var(--accent);
  transform: rotate(45deg);
  flex-shrink: 0;
}
.quadrant-title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-primary);
}
.quadrant-subtitle {
  font-family: 'Share Tech Mono', 'Courier New', monospace;
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  margin-left: auto;
  text-transform: uppercase;
}

/* ── Quadrant Body ── */
.quadrant-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  min-height: 0;
}
.quadrant-body::-webkit-scrollbar {
  width: 3px;
}
.quadrant-body::-webkit-scrollbar-thumb {
  background: var(--border);
}

/* ═══════════════════════════════════════════
   CONTROLS
   ═══════════════════════════════════════════ */
.control-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.control-label {
  font-size: 12px;
  color: var(--text-label);
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

/* ── Horizontal Slider ── */
.slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.slider-label-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.slider-percent,
.slider-value {
  font-family: 'Share Tech Mono', 'Courier New', monospace;
  font-size: 12px;
  color: var(--text-muted);
  min-width: 36px;
  text-align: right;
}

input[type="range"].slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 5px;
  background: var(--slider-track);
  border: 1px solid var(--border);
  outline: none;
  cursor: pointer;
}
input[type="range"].slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 13px;
  height: 18px;
  background: var(--accent);
  border: 1px solid var(--border-thick);
  cursor: pointer;
  transition: background 0.15s;
}
input[type="range"].slider::-webkit-slider-thumb:hover {
  background: var(--accent-hover);
}

/* ── Stepper ── */
.stepper-row {
  display: flex;
  align-items: center;
  gap: 0;
}
.stepper-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-input);
  border: 2px solid var(--border-thick);
  color: var(--text-primary);
  font-size: 16px;
  font-family: 'Share Tech Mono', monospace;
  cursor: pointer;
  transition: all 0.15s;
  outline: none;
  padding: 0;
  line-height: 1;
}
.stepper-btn:first-of-type {
  border-right: none;
}
.stepper-btn:last-of-type {
  border-left: none;
}
.stepper-btn:hover:not(:disabled) {
  background: var(--bg-btn);
  border-color: var(--accent);
  color: var(--accent-hover);
}
.stepper-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.stepper-value-box {
  width: 48px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-input);
  border-top: 2px solid var(--border-thick);
  border-bottom: 2px solid var(--border-thick);
}
.stepper-number {
  font-family: 'Share Tech Mono', 'Courier New', monospace;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.05em;
}
.stepper-unit {
  margin-left: 10px;
  font-size: 12px;
  color: var(--text-label);
}

/* ── Hint Text ── */
.hint-text {
  font-size: 10px;
  color: var(--text-muted);
  letter-spacing: 0.03em;
  margin: 0;
  padding: 2px 0;
  opacity: 0.7;
}

/* ── Input Box ── */
.input-box {
  width: 100%;
  padding: 7px 10px;
  background: var(--bg-input);
  border: 2px solid var(--border-thick);
  color: var(--text-primary);
  font-family: 'Share Tech Mono', 'Courier New', monospace;
  font-size: 12px;
  letter-spacing: 0.04em;
  outline: none;
  transition: border-color 0.18s;
}
.input-box::placeholder {
  color: var(--text-muted);
  opacity: 0.4;
}
.input-box:focus {
  border-color: var(--accent);
}

/* ── Toggle Switch ── */
.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.toggle-switch {
  position: relative;
  width: 42px;
  height: 22px;
  flex-shrink: 0;
  cursor: pointer;
}
.toggle-switch input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}
.toggle-track {
  position: absolute;
  inset: 0;
  background: var(--toggle-off);
  border: 1px solid var(--border);
  transition: background 0.2s;
}
.toggle-switch input:checked + .toggle-track {
  background: var(--toggle-on);
}
.toggle-track::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 3px;
  width: 16px;
  height: 16px;
  background: var(--text-label);
  transition: transform 0.2s;
}
.toggle-switch input:checked + .toggle-track::after {
  transform: translateX(18px);
  background: var(--text-primary);
}

/* ── Dropdown / Select ── */
.select-wrapper {
  position: relative;
}
.select-wrapper::after {
  content: '';
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 0;
  height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid var(--accent);
  pointer-events: none;
}
select {
  width: 100%;
  padding: 7px 32px 7px 10px;
  background: var(--bg-input);
  border: 2px solid var(--border-thick);
  color: var(--text-primary);
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  letter-spacing: 0.04em;
  outline: none;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  transition: border-color 0.18s;
}
select:focus {
  border-color: var(--accent);
}
select option {
  background: var(--bg-surface);
  color: var(--text-primary);
}

/* ── Scale Display ── */
.scale-display {
  padding: 7px 10px;
  background: var(--bg-input);
  border: 2px solid var(--border-thick);
  display: flex;
  align-items: center;
}
.scale-value {
  font-family: 'Share Tech Mono', 'Courier New', monospace;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.06em;
}

/* ═══════════════════════════════════════════
   BUTTON ROW
   ═══════════════════════════════════════════ */
.button-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 18px;
  border-top: 2px solid var(--border);
  background: var(--bg-surface);
  flex-shrink: 0;
}

.btn {
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.05em;
  padding: 8px 22px;
  border: 1px solid var(--border-thick);
  border-radius: 22px;
  cursor: pointer;
  transition: all 0.18s;
  outline: none;
  white-space: nowrap;
  line-height: 1.3;
}
.btn:active {
  transform: scale(0.97);
}

.btn-primary {
  background: var(--bg-btn);
  color: var(--text-primary);
  border-color: var(--accent);
}
.btn-primary:hover {
  background: var(--bg-btn-hover);
  border-color: var(--accent-hover);
  color: #dde8c8;
}

.btn-ghost {
  background: transparent;
  color: var(--text-label);
}
.btn-ghost:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
  border-color: var(--accent);
}

.btn-cancel {
  background: transparent;
  color: #b89888;
  border-color: var(--danger-border);
}
.btn-cancel:hover {
  background: var(--danger-bg);
  border-color: var(--danger-hover);
  color: #d8b8a8;
}

/* ═══════════════════════════════════════════
   SAVE BADGE
   ═══════════════════════════════════════════ */
.save-badge {
  position: absolute;
  bottom: 8px;
  right: 14px;
  background: var(--accent);
  color: #e0ecc8;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.05em;
  padding: 4px 10px;
  border-radius: 3px;
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.3s, transform 0.3s;
  pointer-events: none;
  z-index: 30;
}
.save-badge.show {
  opacity: 1;
  transform: translateY(0);
}
</style>
