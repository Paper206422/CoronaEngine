<template>
  <div class="navigat-bar">
    <button class="nav-btn" @click="handleNewClick">新建</button>
    <button class="nav-btn" @click="handleExportClick" title="导出积木 (Ctrl+S)">导出</button>
    <button class="nav-btn" @click="handleImportClick" title="导入积木 (Ctrl+O)">导入</button>
    <div class="flex-1"></div>
    <button class="nav-btn" @click="handleSearchClick">查找</button>
    <button class="nav-btn" @click="handleSettingsClick">设置</button>
    <Settings ref="settingsModal" />
  </div>
</template>

<script setup>
import * as Blockly from 'blockly/core';
import { ref } from 'vue';
import { useStore } from '../store/store';
import { currentSceneName, currentActorName } from '../composables/useActorContext';
import Settings from './Settings.vue';

const store = useStore();
const settingsModal = ref();
const emit = defineEmits(['new-canvas']);

function handleNewClick() {
  const actor = currentActorName.value || '未选择物体';
  if (!confirm(`确定要清空「${actor}」的所有积木吗？此操作不可恢复。`)) return;

  // 通知 BlocklyWorkspace 处理持久化状态清理
  emit('new-canvas');
}

function handleSearchClick() {
  store.searchVisible.value = !store.searchVisible.value;
}

function handleSettingsClick() {
  settingsModal.value.handleClick();
}

/** 生成导出文件名（包含 Actor 和场景信息） */
function getExportFilename() {
  const scene = currentSceneName.value || 'unknown';
  const actor = currentActorName.value || 'unknown';
  const ts = new Date().toISOString().slice(0, 10);
  return `${actor}_${scene}_${ts}.blockly`;
}

/** 回退下载方案 */
function fallbackDownload(jsonStr, filename) {
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 150);
}

async function handleExportClick() {
  const ws = store.workspace.value;
  if (!ws) return;
  const blocks = ws.getAllBlocks(false);
  if (blocks.length === 0) {
    alert('当前工作区没有积木，无法导出。');
    return;
  }
  const data = Blockly.serialization.workspaces.save(ws);
  const jsonStr = JSON.stringify(data, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const suggestedName = getExportFilename();

  if (window.showSaveFilePicker) {
    try {
      const opts = {
        types: [{ description: 'Blockly 项目文件', accept: { 'application/json': ['.blockly'] } }],
        suggestedName,
      };
      const handle = await window.showSaveFilePicker(opts);
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
    } catch {
      // 用户取消或 API 不可用 → 回退
      fallbackDownload(jsonStr, suggestedName);
    }
  } else {
    fallbackDownload(jsonStr, suggestedName);
  }
}

function handleImportClick() {
  const ws = store.workspace.value;
  if (!ws) {
    alert('工作区尚未初始化，请先打开积木编辑器。');
    return;
  }
  const input = document.createElement('input');
  input.setAttribute('type', 'file');
  input.setAttribute('accept', '.blockly,.json');
  input.addEventListener('change', function () {
    const file = this.files[0];
    if (!file) return;
    const ext = (file.name || '').split('.').pop()?.toLowerCase();
    if (ext !== 'blockly' && ext !== 'json') {
      alert('仅支持 .blockly 或 .json 格式的文件');
      return;
    }

    // 确认覆盖
    const ws2 = store.workspace.value;
    if (ws2 && ws2.getAllBlocks(false).length > 0) {
      if (!confirm('当前工作区已有积木，导入将替换现有积木。是否继续？')) {
        return;
      }
    }

    const reader = new FileReader();
    reader.addEventListener('load', function () {
      let text = this.result;
      // 移除 BOM（UTF-8: EF BB BF → U+FEFF）
      if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);

      // 解析 JSON
      let json;
      try {
        json = JSON.parse(text);
      } catch (e) {
        console.error('[Blockly] JSON 解析失败：', e, '文件内容前100字符：', text.slice(0, 100));
        alert('文件格式不正确，无法解析 JSON：' + (e.message || ''));
        return;
      }

      // 验证 JSON 结构
      if (!json || typeof json !== 'object') {
        alert('文件格式不正确：JSON 根节点必须是对象');
        return;
      }
      if (!json.blocks) {
        console.warn('[Blockly] JSON 缺少 blocks 字段，尝试直接加载');
      }

      // 加载到工作区
      const ws3 = store.workspace.value;
      if (!ws3) {
        alert('工作区已关闭，无法导入。');
        return;
      }
      try {
        Blockly.serialization.workspaces.load(json, ws3);
      } catch (e) {
        console.error('[Blockly] 工作区加载失败：', e);
        alert('工作区加载失败：' + (e.message || '未知错误'));
      }
    });
    reader.addEventListener('error', function () {
      alert('文件读取失败，请确认文件未损坏');
    });
    reader.readAsText(file, 'UTF-8');
  });
  input.click();
}
</script>

<style scoped>
.navigat-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px 6px;
  background: #2a2a2a;
  border-bottom: 1px solid #444;
}

.nav-btn {
  padding: 2px 10px;
  font-size: 12px;
  color: #ccc;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  line-height: 1.6;
}

.nav-btn:hover {
  color: #fff;
  background: #3a3a3a;
  border-color: #555;
}
</style>