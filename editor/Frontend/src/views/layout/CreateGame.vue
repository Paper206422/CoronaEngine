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

    <!-- Tab bar -->
    <div class="flex border-b border-[#444] bg-[#1e1e1e] shrink-0">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="px-5 py-3 text-sm font-medium transition-colors relative"
        :class="activeTab === tab.id ? 'text-[#84a65b]' : 'text-gray-400 hover:text-gray-200'"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
        <span
          v-if="activeTab === tab.id"
          class="absolute bottom-0 left-0 right-0 h-0.5 bg-[#84a65b]"
        ></span>
      </button>
    </div>

    <!-- Tab content -->
    <div class="flex-1 p-12 bg-[#252525] flex flex-col overflow-y-auto">

      <!-- Tab 1: 基础信息 -->
      <div v-show="activeTab === 'basic'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">基础信息</h2>
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

      <!-- Tab 2: 世界构建 -->
      <div v-show="activeTab === 'world'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">世界构建</h2>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">地形类型</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="tt in terrainTypes" :key="tt.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.terrainType === tt.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.terrainType = tt.id">
              <div class="text-lg font-medium">{{ tt.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ tt.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">世界尺寸</label>
          <div class="grid grid-cols-4 gap-3">
            <div v-for="ws in worldSizes" :key="ws.id"
              :class="['p-3 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.worldSize === ws.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.worldSize = ws.id">
              <div class="text-base font-medium">{{ ws.label }}</div>
              <div class="text-xs text-gray-500 mt-0.5">{{ ws.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">生态群落</label>
          <select v-model="gameSettings.biome"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all">
            <option value="temperate">温带</option>
            <option value="tropical">热带</option>
            <option value="desert">沙漠</option>
            <option value="arctic">极地</option>
            <option value="mixed">混合</option>
          </select>
        </div>
        <div class="flex items-center gap-6">
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="gameSettings.waterSystem" type="checkbox" class="accent-[#84a65b] w-4 h-4" />
            <span class="text-sm text-gray-400">水体系统（河流/湖泊/海洋）</span>
          </label>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">天空盒预设</label>
          <select v-model="gameSettings.skybox"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all">
            <option value="day_clear">晴朗白昼</option>
            <option value="day_cloudy">多云</option>
            <option value="sunset">日落</option>
            <option value="night_starry">星夜</option>
            <option value="procedural">程序化动态天空</option>
          </select>
        </div>
      </div>

      <!-- Tab 3: 物理系统 -->
      <div v-show="activeTab === 'physics'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">物理系统</h2>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">物理引擎</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="pe in physicsEngines" :key="pe.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.physicsEngine === pe.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.physicsEngine = pe.id">
              <div class="text-lg font-medium">{{ pe.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ pe.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">重力方案</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="gp in gravityPresets" :key="gp.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.gravityPreset === gp.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.gravityPreset = gp.id">
              <div class="text-lg font-medium">{{ gp.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ gp.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">角色控制器</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="cc in characterControllers" :key="cc.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.characterController === cc.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.characterController = cc.id">
              <div class="text-lg font-medium">{{ cc.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ cc.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">碰撞精度</label>
          <select v-model="gameSettings.collisionDetail"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all">
            <option value="low">低（简单碰撞体）</option>
            <option value="medium">中（凸包近似）</option>
            <option value="high">高（精确网格碰撞）</option>
          </select>
        </div>
      </div>

      <!-- Tab 4: 渲染管线 -->
      <div v-show="activeTab === 'rendering'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">渲染管线</h2>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">渲染管线</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="rp in renderPipelines" :key="rp.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.renderPipeline === rp.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.renderPipeline = rp.id">
              <div class="text-lg font-medium">{{ rp.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ rp.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">画质预设</label>
          <div class="grid grid-cols-4 gap-3">
            <div v-for="qp in qualityPresets" :key="qp.id"
              :class="['p-3 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.qualityPreset === qp.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.qualityPreset = qp.id">
              <div class="text-base font-medium">{{ qp.label }}</div>
              <div class="text-xs text-gray-500 mt-0.5">{{ qp.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">阴影质量</label>
          <select v-model="gameSettings.shadowQuality"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all">
            <option value="off">关闭</option>
            <option value="low">低（512px）</option>
            <option value="medium">中（1024px）</option>
            <option value="high">高（2048px）</option>
            <option value="ultra">极高（4096px）</option>
          </select>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400 mb-3">后处理效果</label>
          <div class="flex flex-wrap gap-3">
            <label v-for="pp in postProcessOptions" :key="pp.id"
              class="flex items-center gap-2 cursor-pointer bg-[#1a1a1a] border border-[#444] rounded px-4 py-2 hover:border-[#666] transition-all">
              <input v-model="gameSettings.postProcessing" type="checkbox" :value="pp.id" class="accent-[#84a65b] w-4 h-4" />
              <span class="text-sm text-gray-300">{{ pp.label }}</span>
            </label>
          </div>
        </div>
      </div>

      <!-- Tab 5: 玩法模板 -->
      <div v-show="activeTab === 'gameplay'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">玩法模板</h2>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">玩法模板</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="gt in gameplayTemplates" :key="gt.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.template === gt.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.template = gt.id">
              <div class="text-2xl mb-1">{{ gt.icon }}</div>
              <div class="text-base font-medium">{{ gt.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ gt.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">输入预设</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="ip in inputPresets" :key="ip.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.inputPreset === ip.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.inputPreset = ip.id">
              <div class="text-lg font-medium">{{ ip.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ ip.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">相机类型</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="ct in cameraTypes" :key="ct.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                gameSettings.cameraType === ct.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="gameSettings.cameraType = ct.id">
              <div class="text-lg font-medium">{{ ct.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ ct.desc }}</div>
            </div>
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
        <span class="text-xs text-gray-500">{{ activeTabLabel }}</span>
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
  try {
    await appService.removeDockWidget('CreateGame');
  } catch (e) {
    window.close();
  }
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
