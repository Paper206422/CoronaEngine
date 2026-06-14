<template>
  <div
    class="relative min-h-screen border-2 border-[#84a65b] bg-[#282828]/95 text-white overflow-hidden flex flex-col font-sans"
  >
    <DockTitleBar
      title="创建游戏"
      extraClass="bg-[#84A65B]"
      routePath="/CreateGame"
      @close="closeFloat"
    />

    <!-- Tab content -->
    <div class="flex-1 p-12 bg-[#252525] flex flex-col overflow-y-auto">
      <div class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">创造模式</h2>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">项目名称</label>
          <input v-model="projectName" type="text"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all"
            placeholder="请输入项目名称..." />
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">存储位置</label>
          <div class="flex gap-2">
            <input v-model="projectPath" type="text" readonly
              class="flex-1 bg-[#1a1a1a] border border-[#444] rounded p-3 text-base text-gray-400" />
            <button class="px-6 bg-[#3d3d3d] hover:bg-[#4d4d4d] rounded transition-colors text-base" @click="browseFolder">浏览</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom buttons -->
    <div class="shrink-0 px-12 py-6 bg-[#1e1e1e] border-t border-[#333] flex justify-between items-center">
      <button class="px-5 py-3 text-base text-gray-400 hover:text-white hover:bg-[#333] rounded transition-colors inline-flex items-center gap-1 w-fit" @click="goBack">
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
        返回
      </button>
      <div class="flex gap-4 items-center">
        <button class="px-10 py-3 text-base text-gray-400 hover:text-white transition-colors" @click="closeFloat">取消</button>
        <button
          :disabled="!projectName || !projectPath"
          class="px-14 py-3 bg-[#84a65b] hover:bg-[#95b86c] disabled:bg-gray-600 disabled:cursor-not-allowed rounded font-bold transition-all shadow-lg text-base"
          @click="handleCreateProject">
          创建项目
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { projectLauncherService, appService } from '@/utils/bridge';
import DockTitleBar from '@/components/ui/DockTitleBar.vue';

const router = useRouter();

const projectName = ref('New_Corona_Project');
const projectPath = ref('');
const activeTab = ref('basic');

const tabs = [
  { id: 'basic', label: '基础信息' },
  { id: 'world', label: '世界构建' },
  { id: 'physics', label: '物理系统' },
  { id: 'rendering', label: '渲染管线' },
  { id: 'gameplay', label: '玩法模板' },
];

const activeTabLabel = computed(() => {
  const t = tabs.find(t => t.id === activeTab.value);
  return t ? `步骤 ${tabs.indexOf(t) + 1}/${tabs.length}` : '';
});

const terrainTypes = [
  { id: 'flat', label: '平面地形', desc: '初始为完全平面' },
  { id: 'procedural', label: '程序化生成', desc: '噪声算法自动生成' },
  { id: 'heightmap', label: '高度图导入', desc: '从外部高度图导入' },
];

const worldSizes = [
  { id: 'small', label: '小型', desc: '512×512m' },
  { id: 'medium', label: '中型', desc: '2×2km' },
  { id: 'large', label: '大型', desc: '8×8km' },
  { id: 'custom', label: '自定义', desc: '后续指定' },
];

const physicsEngines = [
  { id: 'builtin', label: '内置物理', desc: '轻量级，适合简单场景' },
  { id: 'advanced', label: '高级物理', desc: '完整物理模拟' },
  { id: 'none', label: '无物理', desc: '纯静态场景' },
];

const gravityPresets = [
  { id: 'earth', label: '地球 (9.8)', desc: '标准重力' },
  { id: 'moon', label: '月球 (1.6)', desc: '低重力漂浮感' },
  { id: 'zero', label: '零重力', desc: '太空/无重力' },
];

const characterControllers = [
  { id: 'capsule', label: '胶囊体', desc: '通用FPS/TPS角色' },
  { id: 'rigidbody', label: '刚体', desc: '物理驱动角色' },
  { id: 'kinematic', label: '运动学', desc: '脚本完全控制' },
];

const renderPipelines = [
  { id: 'forward', label: '前向渲染', desc: '兼容性好，适合移动端' },
  { id: 'deferred', label: '延迟渲染', desc: '多光源，高画质' },
  { id: 'forward_plus', label: '前向+', desc: '前向渲染增强版' },
];

const qualityPresets = [
  { id: 'low', label: '低', desc: '集显/移动端' },
  { id: 'medium', label: '中', desc: '主流配置' },
  { id: 'high', label: '高', desc: '高端配置' },
  { id: 'ultra', label: '极致', desc: '旗舰配置' },
];

const postProcessOptions = [
  { id: 'ao', label: '环境光遮蔽' },
  { id: 'bloom', label: '泛光' },
  { id: 'motion_blur', label: '运动模糊' },
  { id: 'dof', label: '景深' },
  { id: 'color_grading', label: '色彩校正' },
  { id: 'vignette', label: '暗角' },
];

const gameplayTemplates = [
  { id: 'fps', label: '第一人称', desc: 'FPS视角与控制', icon: '🔫' },
  { id: 'tps', label: '第三人称', desc: '越肩/跟随视角', icon: '🏃' },
  { id: 'platformer', label: '平台跳跃', desc: '2D/3D平台动作', icon: '🦘' },
  { id: 'topdown', label: '俯视角', desc: '自上而下视角', icon: '🗺️' },
  { id: 'sandbox', label: '沙盒自由', desc: '无预设约束', icon: '🧱' },
  { id: 'vehicle', label: '载具模拟', desc: '车辆/飞行器', icon: '🚗' },
];

const inputPresets = [
  { id: 'standard', label: '标准键鼠', desc: 'WASD+鼠标' },
  { id: 'gamepad', label: '手柄优先', desc: 'XInput手柄映射' },
  { id: 'custom', label: '自定义', desc: '后续自行绑定' },
];

const cameraTypes = [
  { id: 'free', label: '自由相机', desc: '无约束操控' },
  { id: 'follow', label: '跟随相机', desc: '跟踪目标对象' },
  { id: 'fixed', label: '固定相机', desc: '预设视角点位' },
];

const gameSettings = ref({
  terrainType: 'flat',
  worldSize: 'medium',
  biome: 'temperate',
  waterSystem: false,
  skybox: 'day_clear',
  physicsEngine: 'builtin',
  gravityPreset: 'earth',
  characterController: 'capsule',
  collisionDetail: 'medium',
  renderPipeline: 'forward',
  qualityPreset: 'high',
  shadowQuality: 'medium',
  postProcessing: ['ao', 'bloom'],
  template: 'tps',
  inputPreset: 'standard',
  cameraType: 'follow',
});

onMounted(async () => {
  try {
    const path = await projectLauncherService.getDefaultProjectPath();
    if (path) projectPath.value = path.data;
  } catch (error) {
    console.error('CreateGame 初始化失败:', error);
  }
});

const goBack = () => {
  router.push('/StartScreen');
};

const browseFolder = async () => {
  const path = await projectLauncherService.browseFolder(projectPath.value);
  if (path.data) projectPath.value = path.data;
};

const handleCreateProject = async () => {
  if (!projectName.value || !projectPath.value) return;

  try {
    const projectData = {
      name: projectName.value,
      path: projectPath.value,
      mode: 'creative',
      settings: {
        ...gameSettings.value,
        defaultScene: 'creative_basic',
        realTimeRender: gameSettings.value.renderPipeline !== 'forward',
      },
    };

    const result = await projectLauncherService.createProject(projectData);

    if (result.success === true) {
      await handleOpenProject(result.data);
    } else {
      alert('创建失败: ' + result.message);
    }
  } catch (error) {
    console.error('创建项目异常:', error);
  }
};

const handleOpenProject = async (path) => {
  try {
    await projectLauncherService.setProjectMode('creative', gameSettings.value);
    const success = await projectLauncherService.openProject(path);
    if (success.data) {
      await appService.start_engine();
      router.push('/');
    }
  } catch (error) {
    console.error('打开项目失败:', error);
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
