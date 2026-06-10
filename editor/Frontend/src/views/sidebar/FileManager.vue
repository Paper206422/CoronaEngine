<template>
  <div
    class="flex-1 min-h-0 w-full rounded-lg overflow-hidden relative bg-[#282828]/90 flex flex-col text-white font-sans"
  >
    <DockTitleBar
      v-if="!isDocked"
      title="文件管理"
      extraClass="bg-[#84A65B]"
      routePath="/FileManager"
      @close="closeFloat"
    />

    <div class="flex items-center gap-2 p-2 bg-[#1a1a1a]/50 border-b border-[#333]">
      <div class="text-[10px] text-gray-400 truncate flex-1">
        <span class="text-[#84a65b] font-bold">{{ projectName }}</span>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto custom-scrollbar p-2">
      <FileTreeNode
        v-if="fileTree.children"
        :nodes="fileTree.children"
        :level="0"
        @node-click="handleNodeClick"
        @node-dblclick="handleNodeDblClick"
        @contextmenu="handleContextMenu"
        @refresh="loadFileTree"
      />

      <div v-else-if="loading" class="flex justify-center items-center h-32">
        <div class="text-[#84a65b]">加载中...</div>
      </div>

      <div
        v-else
        class="h-full flex flex-col items-center justify-center text-gray-500 italic text-xs"
      >
        <div class="text-3xl mb-2">🍃</div>
        <p>暂无文件或未打开项目</p>
      </div>
    </div>

    <!-- 右键菜单 -->
    <div
      v-if="contextMenu.show"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      class="fixed z-[100] bg-[#1e1e1e] border border-[#444] shadow-xl py-1 min-w-[150px] text-xs"
    >
      <!-- 文件夹特有菜单 -->
      <template v-if="contextMenu.item?.isDirectory">
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleNewFolder">
          新建文件夹
        </div>
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleNewScene">
          新建场景
        </div>
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleNewActor">
          新建单位
        </div>
        <div class="h-[1px] bg-[#333] my-1"></div>
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleRename">重命名</div>
        <div
          class="px-4 py-2 hover:bg-red-600 cursor-pointer text-red-400 hover:text-white"
          @click="handleDelete"
        >
          删除
        </div>
      </template>

      <!-- 文件特有菜单 -->
      <template v-else-if="contextMenu.item">
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleOpenFile">打开</div>
        <div class="h-[1px] bg-[#333] my-1"></div>
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleRename">重命名</div>
        <div
          class="px-4 py-2 hover:bg-red-600 cursor-pointer text-red-400 hover:text-white"
          @click="handleDelete"
        >
          删除
        </div>
      </template>

      <!-- 空白区域菜单 -->
      <template v-else>
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleNewFolder">
          新建文件夹
        </div>
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleNewScene">
          新建场景
        </div>
        <div class="px-4 py-2 hover:bg-[#84a65b] cursor-pointer" @click="handleNewActor">
          新建单位
        </div>
      </template>
    </div>

    <!-- 新建/重命名对话框 -->
    <div
      v-if="dialog.show"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-[200]"
    >
      <div class="bg-[#1e1e1e] border border-[#444] p-4 rounded w-80">
        <div class="text-[#84a65b] font-bold mb-3">{{ dialog.title }}</div>
        <input
          v-model="dialog.value"
          type="text"
          class="w-full bg-[#333] border border-[#555] px-3 py-2 text-sm text-white rounded outline-none focus:border-[#84a65b]"
          :placeholder="dialog.placeholder"
          @keyup.enter="handleDialogConfirm"
        />
        <div class="flex justify-end gap-2 mt-4">
          <button
            class="px-3 py-1 text-sm bg-[#333] hover:bg-[#444] rounded"
            @click="dialog.show = false"
          >
            取消
          </button>
          <button
            class="px-3 py-1 text-sm bg-[#84a65b] hover:bg-[#6b8a4a] rounded"
            @click="handleDialogConfirm"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue';
import { fileService } from '@/utils/bridge';
import { useDockPanel } from '@/composables/useDockPanel.js';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';
import FileTreeNode from '@/components/ui/FileTreeNode.vue';

const { closePanel: closeDockPanel, isDocked } = useDockPanel();

const projectName = ref('Corona Project');
const fileTree = ref({ children: [] });
const loading = ref(false);
const contextMenu = ref({ show: false, x: 0, y: 0, item: null });
const dialog = ref({
  show: false,
  title: '',
  placeholder: '',
  value: '',
  type: '', // 'newFolder', 'newScene', 'newActor', 'rename'
  targetPath: '',
});

// 加载文件树
const loadFileTree = async () => {
  loading.value = true;
  const res = await fileService.getFileTree('');
  if (res && res.data) {
    fileTree.value = res.data;
  }
  loading.value = false;
};

// 初始化
const init = async () => {
  const info = await fileService.getProjectInfo();
  if (info?.data?.exists) {
    projectName.value = info.data.name;
    await loadFileTree();
  }
};

// 处理节点单击（只处理文件夹展开/收起）
const handleNodeClick = (node) => {
  if (node.isDirectory) {
    // 切换展开/收起状态
    node.expanded = !node.expanded;
  }
  // 文件单击不做任何事
};

// 处理节点双击（打开文件）
const handleNodeDblClick = (node) => {
  if (!node.isDirectory) {
    if (node.name.endsWith('.scene')) {
      fileService.openFile(node.path, 'scene');
    } else if (node.name.endsWith('.actor')) {
      fileService.openFile(node.path, 'actor');
    }
  }
};

// 处理右键菜单
const handleContextMenu = (event, item) => {
  event.preventDefault();
  event.stopPropagation(); // 防止事件冒泡

  // 关闭已有的右键菜单
  contextMenu.value.show = false;

  // 使用 nextTick 确保上一个菜单关闭后再打开新的
  nextTick(() => {
    contextMenu.value = {
      show: true,
      x: event.clientX,
      y: event.clientY,
      item: item || null,
    };
  });
};

// 关闭右键菜单
const closeContextMenu = () => {
  contextMenu.value.show = false;
};

// 打开新建文件夹对话框
const handleNewFolder = () => {
  dialog.value = {
    show: true,
    title: '新建文件夹',
    placeholder: '输入文件夹名称',
    value: '',
    type: 'newFolder',
    targetPath: contextMenu.value.item?.path || '',
  };
  closeContextMenu();
};

// 打开新建场景对话框
const handleNewScene = () => {
  dialog.value = {
    show: true,
    title: '新建场景',
    placeholder: '输入场景名称 (.scene)',
    value: '',
    type: 'newScene',
    targetPath: contextMenu.value.item?.path || '',
  };
  closeContextMenu();
};

// 打开新建单位对话框
const handleNewActor = () => {
  dialog.value = {
    show: true,
    title: '新建单位',
    placeholder: '输入单位名称 (.actor)',
    value: '',
    type: 'newActor',
    targetPath: contextMenu.value.item?.path || '',
  };
  closeContextMenu();
};

// 打开重命名对话框
const handleRename = () => {
  if (!contextMenu.value.item) return;

  dialog.value = {
    show: true,
    title: '重命名',
    placeholder: '输入新名称',
    value: contextMenu.value.item.name,
    type: 'rename',
    targetPath: contextMenu.value.item.path,
    oldName: contextMenu.value.item.name,
  };
  closeContextMenu();
};

// 处理删除
const handleDelete = async () => {
  if (!contextMenu.value.item) return;

  if (confirm(`确定要删除 "${contextMenu.value.item.name}" 吗？`)) {
    const res = await fileService.deleteItem(contextMenu.value.item.path);
    if (res?.data) {
      await loadFileTree();
    }
  }
  closeContextMenu();
};

// 处理打开文件（从右击调用）
const handleOpenFile = (node) => {
  if (node && !node.isDirectory) {
    if (node.name.endsWith('.scene')) {
      fileService.openFile(node.path, 'scene');
    } else if (node.name.endsWith('.actor')) {
      fileService.openFile(node.path, 'actor');
    }
  }
  closeContextMenu();
};

// 处理对话框确认
const handleDialogConfirm = async () => {
  if (!dialog.value.value.trim()) {
    alert('名称不能为空');
    return;
  }

  const name = dialog.value.value.trim();

  switch (dialog.value.type) {
    case 'newFolder':
      await fileService.createFolder(dialog.value.targetPath, name);
      break;
    case 'newScene':
      // 创建.scene文件
      await fileService.createFile(
        dialog.value.targetPath,
        name.endsWith('.scene') ? name : name + '.scene',
        'scene'
      );
      break;
    case 'newActor':
      // 创建.actor文件
      await fileService.createFile(
        dialog.value.targetPath,
        name.endsWith('.actor') ? name : name + '.actor',
        'actor'
      );
      break;
    case 'rename':
      await fileService.renameItem(dialog.value.targetPath, name);
      break;
  }

  dialog.value.show = false;
  await loadFileTree();
};

// 关闭浮动窗口
const closeFloat = () => {
  if (closeDockPanel) { closeDockPanel(); return; }
};

onMounted(() => {
  init();
  window.addEventListener('click', closeContextMenu);
});
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #444;
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #84a65b;
}
</style>
