<template>
  <div
    class="relative min-h-screen border-2 border-[#84a65b] bg-[#282828]/95 text-white overflow-hidden flex flex-col font-sans"
  >
    <DockTitleBar
      title="最近游戏"
      extraClass="bg-[#84A65B]"
      routePath="/RecentGames"
      @close="closeFloat"
    />

    <div class="flex-1 p-20 bg-[#1e1e1e] flex flex-col">
      <div class="mb-10">
        <h2 class="text-5xl font-bold text-[#84a65b] mb-2">Corona Editor</h2>
        <p class="text-base text-gray-500">版本: {{ appVersion }}</p>
      </div>

      <div class="flex-1 overflow-y-auto">
        <h3 class="text-base font-semibold text-gray-400 uppercase tracking-wider mb-6">
          最近项目
        </h3>
        <div v-if="recentProjects.length > 0" class="space-y-3">
          <div
            v-for="proj in recentProjects"
            :key="proj.path"
            class="p-5 rounded bg-[#2d2d2d] transition-colors group"
            :class="[
              proj.if_exists
                ? 'cursor-pointer hover:bg-[#3d3d3d]'
                : 'cursor-not-allowed opacity-60',
            ]"
            @dblclick="proj.if_exists && handleOpenProject(proj.path)"
          >
            <div class="text-base font-medium truncate">
              <span v-if="proj.if_exists">{{ proj.name }}</span>
              <span v-else class="text-red-500">{{ proj.name }} (路径异常)</span>
            </div>
            <div class="text-xs text-gray-500 truncate mt-1">{{ proj.path }}</div>
          </div>
        </div>
        <div
          v-else
          class="text-sm text-gray-600 italic p-6 text-center border border-dashed border-[#333] rounded"
        >
          暂无最近记录
        </div>
      </div>

      <div class="mt-6 pt-6 border-t border-[#333] space-y-3">
        <button
          class="w-full py-3 px-6 text-left text-base hover:bg-[#333] rounded flex items-center gap-3"
          @click="handleImport"
        >
          <span class="text-xl">📁</span>
          打开现有项目...
        </button>
      </div>

      <div class="mt-6">
        <button
          class="px-5 py-3 text-base text-gray-400 hover:text-white hover:bg-[#333] rounded transition-colors inline-flex items-center gap-1 w-fit"
          @click="goBack"
        >
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
          返回
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { projectLauncherService, appService } from '@/utils/bridge';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';

const router = useRouter();

const appVersion = ref('V1.0.0');
const recentProjects = ref([]);

const goBack = () => {
  router.push('/StartScreen');
};

onMounted(async () => {
  try {
    const version = await projectLauncherService.getAppVersion();
    if (version) appVersion.value = version.data;

    const saved = await projectLauncherService.getRecentProjects();
    if (saved) recentProjects.value = saved.data;
  } catch (error) {
    console.error('RecentGames 初始化失败:', error);
  }
});

const handleOpenProject = async (path) => {
  try {
    const success = await projectLauncherService.openProject(path);
    if (success.data) {
      await appService.start_engine();
      router.push('/');
    }
  } catch (error) {
    console.error('打开项目失败:', error);
  }
};

const handleImport = async () => {
  const result = await projectLauncherService.openProjectFile();
  if (result && result.data.path) {
    handleOpenProject(result.data.path);
  }
};

const closeFloat = async () => {
  window.close();
};
</script>

<style scoped>
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
