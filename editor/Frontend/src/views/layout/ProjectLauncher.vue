<template>
  <div
    class="relative min-h-screen border-2 border-[#84a65b] bg-[#282828]/95 text-white overflow-hidden flex flex-col font-sans"
  >
    <DockTitleBar
      title="Corona Project Launcher"
      extraClass="bg-[#84A65B]"
      routePath="/ProjectLauncher"
      @close="closeFloat"
    />

    <div class="flex-1 flex overflow-hidden">
      <div class="w-72 bg-[#1e1e1e] border-r border-[#333] flex flex-col p-4">
        <div class="mb-8">
          <h2 class="text-xl font-bold text-[#84a65b] mb-1">Corona Editor</h2>
          <p class="text-xs text-gray-500">版本: {{ appVersion }}</p>
        </div>

        <div class="flex-1 overflow-y-auto">
          <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
            最近项目
          </h3>
          <div v-if="recentProjects.length > 0" class="space-y-2">
            <div
              v-for="proj in recentProjects"
              :key="proj.path"
              class="p-3 rounded bg-[#2d2d2d] transition-colors group"
              :class="[
                proj.if_exists
                  ? 'cursor-pointer hover:bg-[#3d3d3d]'
                  : 'cursor-not-allowed opacity-60',
              ]"
              @dblclick="proj.if_exists && handleOpenProject(proj.path)"
            >
              <div class="text-sm font-medium truncate">
                <span v-if="proj.if_exists">{{ proj.name }}</span>
                <span v-else class="text-red-500">{{ proj.name }} (路径异常)</span>
              </div>
              <div class="text-[10px] text-gray-500 truncate mt-1">{{ proj.path }}</div>
            </div>
          </div>
          <div
            v-else
            class="text-xs text-gray-600 italic p-4 text-center border border-dashed border-[#333] rounded"
          >
            暂无最近记录
          </div>
        </div>

        <div class="mt-4 pt-4 border-t border-[#333] space-y-2">
          <button
            class="w-full py-2 px-4 text-left text-sm hover:bg-[#333] rounded flex items-center gap-2"
            @click="handleSideAction('import')"
          >
            <span>📁</span>
            打开现有项目...
          </button>
        </div>
      </div>

      <div class="flex-1 p-10 bg-[#252525] flex flex-col">
        <h2 class="text-2xl font-light mb-8">创建新项目</h2>

        <div class="max-w-2xl space-y-8">
          <div class="space-y-2">
            <label class="text-sm text-gray-400">项目名称</label>
            <input
              v-model="projectName"
              type="text"
              class="w-full bg-[#1a1a1a] border border-[#333] rounded p-3 focus:border-[#84a65b] outline-none transition-all"
              placeholder="请输入项目名称..."
            />
          </div>

          <div class="space-y-2">
            <label class="text-sm text-gray-400">存储位置</label>
            <div class="flex gap-2">
              <input
                v-model="projectPath"
                type="text"
                readonly
                class="flex-1 bg-[#1a1a1a] border border-[#333] rounded p-3 text-sm text-gray-400"
              />
              <button
                class="px-6 bg-[#3d3d3d] hover:bg-[#4d4d4d] rounded transition-colors"
                @click="browseFolder"
              >
                浏览
              </button>
            </div>
          </div>

          <div class="space-y-4">
            <label class="text-sm text-gray-400">项目类型</label>
            <div class="grid grid-cols-3 gap-4">
              <div
                v-for="mode in modes"
                :key="mode.id"
                :class="[
                  'p-4 border rounded-lg cursor-pointer transition-all flex flex-col items-center gap-2',
                  selectedMode === mode.id
                    ? 'border-[#84a65b] bg-[#84a65b]/10'
                    : 'border-[#333] hover:border-[#666]',
                ]"
                @click="selectedMode = mode.id"
              >
                <span class="text-2xl">{{ mode.icon }}</span>
                <span class="font-medium text-sm">{{ mode.label }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-auto pt-10 flex justify-end gap-4">
          <button
            class="px-8 py-2 text-gray-400 hover:text-white transition-colors"
            @click="closeFloat"
          >
            取消
          </button>
          <button
            :disabled="!projectName || !projectPath"
            class="px-10 py-2 bg-[#84a65b] hover:bg-[#95b86c] disabled:bg-gray-600 disabled:cursor-not-allowed rounded font-bold transition-all shadow-lg"
            @click="handleCreateProject"
          >
            创建项目
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import { useRouter } from 'vue-router';
import { projectLauncherService, appService } from '@/utils/bridge';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';

const router = useRouter();

// --- 状态数据 ---
const projectName = ref('New_Corona_Project');
const projectPath = ref('');
const selectedMode = ref('3d');
const appVersion = ref('V1.0.0');
const recentProjects = ref([]);

const modes = [
  { id: '2d', label: '2D 平面设计', icon: '🎨' },
  { id: '3d', label: '3D 场景渲染', icon: '🧊' },
  { id: 'render', label: '高质量离线渲染', icon: '📸' },
];

// 默认设置
const modeSettings = ref({
  defaultScene: 'basic',
  realTimeRender: false,
});

// --- 初始化加载 ---
onMounted(async () => {
  try {
    // 获取默认路径
    const path = await projectLauncherService.getDefaultProjectPath();
    if (path) projectPath.value = path.data;

    // 获取版本
    const version = await projectLauncherService.getAppVersion();
    if (version) appVersion.value = version.data;

    // 模拟从本地缓存加载最近项目（实际可从后端读取）
    const saved = await projectLauncherService.getRecentProjects();
    if (saved) recentProjects.value = saved.data;
  } catch (error) {
    console.error('ProjectLauncher 初始化失败:', error);
  }
});

// --- 业务方法 ---

// 浏览文件夹
const browseFolder = async () => {
  const path = await projectLauncherService.browseFolder(projectPath.value);
  if (path.data) projectPath.value = path.data;
};

// 创建新项目
const handleCreateProject = async () => {
  if (!projectName.value || !projectPath.value) return;

  try {
    const projectData = {
      name: projectName.value,
      path: projectPath.value,
      mode: selectedMode.value,
      settings: modeSettings.value,
    };

    const result = await projectLauncherService.createProject(projectData);

    if (result.success === true) {
      // 打开项目
      await handleOpenProject(result.data);
    } else {
      alert('创建失败: ' + result.message);
    }
  } catch (error) {
    console.error('创建项目异常:', error);
  }
};

// 打开指定项目
const handleOpenProject = async (path) => {
  try {
    // 切换模式
    await projectLauncherService.setProjectMode(selectedMode.value, modeSettings.value);
    // 执行打开
    const success = await projectLauncherService.openProject(path);
    if (success.data) {
      await appService.start_engine();
      router.push('/');
    }
  } catch (error) {
    console.error('打开项目失败:', error);
  }
};

// 侧边栏辅助操作
const handleSideAction = async (type) => {
  if (type === 'import') {
    const result = await projectLauncherService.openProjectFile();
    if (result && result.data.path) {
      handleOpenProject(result.data.path);
    }
  }
};

const closeFloat = async () => {
  window.close();
};

// 监听模式切换以更新默认设置
watch(selectedMode, (newMode) => {
  if (newMode === 'render') {
    modeSettings.value.realTimeRender = true;
    modeSettings.value.defaultScene = 'studio';
  } else {
    modeSettings.value.realTimeRender = false;
    modeSettings.value.defaultScene = 'basic';
  }
});
</script>

<style scoped>
/* 针对 Webkit 优化滚动条 */
::-webkit-scrollbar {
  width: 4px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #444;
  border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover {
  background: #84a65b;
}
</style>
