<template>
  <div
    class="relative min-h-screen border-2 border-[#84a65b] bg-[#282828]/95 text-white overflow-hidden flex flex-col font-sans"
  >
    <DockTitleBar
      title="剧情模式"
      extraClass="bg-[#84A65B]"
      routePath="/StoryMode"
      @close="closeFloat"
    />

    <!-- Tab bar -->
    <div class="flex border-b border-[#444] bg-[#1e1e1e] shrink-0">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="px-6 py-3 text-sm font-medium transition-colors relative"
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
        <div class="space-y-2">
          <label class="text-sm text-gray-400">游戏标题</label>
          <input v-model="storySettings.gameTitle" type="text"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all"
            placeholder="在此显示的游戏标题..." />
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">作者 / 团队</label>
          <input v-model="storySettings.author" type="text"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all"
            placeholder="作者或团队名称..." />
        </div>
      </div>

      <!-- Tab 2: 叙事设定 -->
      <div v-show="activeTab === 'narrative'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">叙事设定</h2>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">叙事类型</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="nt in narrativeTypes" :key="nt.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                storySettings.narrativeType === nt.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="storySettings.narrativeType = nt.id">
              <div class="text-lg font-medium">{{ nt.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ nt.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">对话系统</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="ds in dialogueStyles" :key="ds.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                storySettings.dialogueStyle === ds.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="storySettings.dialogueStyle = ds.id">
              <div class="text-lg font-medium">{{ ds.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ ds.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">选择影响范围</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="cs in consequenceScopes" :key="cs.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                storySettings.consequenceScope === cs.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="storySettings.consequenceScope = cs.id">
              <div class="text-lg font-medium">{{ cs.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ cs.desc }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 3: 演出配置 -->
      <div v-show="activeTab === 'cinematics'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">演出配置</h2>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">过场镜头风格</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="cs in cameraStyles" :key="cs.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                storySettings.cameraStyle === cs.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="storySettings.cameraStyle = cs.id">
              <div class="text-lg font-medium">{{ cs.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ cs.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">文字显示速度</label>
          <div class="flex items-center gap-3">
            <span class="text-xs text-gray-500 w-8">慢</span>
            <input v-model.number="storySettings.textSpeed" type="range" min="1" max="5" step="1"
              class="flex-1 accent-[#84a65b]" />
            <span class="text-xs text-gray-500 w-8">快</span>
            <span class="text-xs text-[#84a65b] w-6 text-right">{{ storySettings.textSpeed }}</span>
          </div>
        </div>
        <div class="flex items-center gap-6">
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="storySettings.autoPlay" type="checkbox" class="accent-[#84a65b] w-4 h-4" />
            <span class="text-sm text-gray-400">启用自动播放</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="storySettings.skipEnabled" type="checkbox" class="accent-[#84a65b] w-4 h-4" />
            <span class="text-sm text-gray-400">允许跳过</span>
          </label>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">UI 主题</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="ut in uiThemes" :key="ut.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                storySettings.uiTheme === ut.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="storySettings.uiTheme = ut.id">
              <div class="text-lg font-medium">{{ ut.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ ut.desc }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 4: 音频设计 -->
      <div v-show="activeTab === 'audio'" class="max-w-3xl space-y-8">
        <h2 class="text-2xl font-light mb-4">音频设计</h2>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">背景音乐默认音量</label>
          <div class="flex items-center gap-3">
            <span class="text-xs text-gray-500">0</span>
            <input v-model.number="storySettings.bgmVolume" type="range" min="0" max="100" step="5"
              class="flex-1 accent-[#84a65b]" />
            <span class="text-xs text-gray-500">100</span>
            <span class="text-xs text-[#84a65b] w-10 text-right">{{ storySettings.bgmVolume }}%</span>
          </div>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">音效默认音量</label>
          <div class="flex items-center gap-3">
            <span class="text-xs text-gray-500">0</span>
            <input v-model.number="storySettings.sfxVolume" type="range" min="0" max="100" step="5"
              class="flex-1 accent-[#84a65b]" />
            <span class="text-xs text-gray-500">100</span>
            <span class="text-xs text-[#84a65b] w-10 text-right">{{ storySettings.sfxVolume }}%</span>
          </div>
        </div>
        <div class="space-y-4">
          <label class="text-sm text-gray-400">语音支持</label>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="vo in voiceOptions" :key="vo.id"
              :class="['p-4 border rounded-lg cursor-pointer transition-all text-center',
                storySettings.voiceOption === vo.id ? 'border-[#84a65b] bg-[#84a65b]/10' : 'border-[#444] hover:border-[#666]']"
              @click="storySettings.voiceOption = vo.id">
              <div class="text-lg font-medium">{{ vo.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ vo.desc }}</div>
            </div>
          </div>
        </div>
        <div class="space-y-2">
          <label class="text-sm text-gray-400">环境音效预设</label>
          <select v-model="storySettings.ambientPreset"
            class="w-full bg-[#1a1a1a] border border-[#444] rounded p-3 text-base focus:border-[#84a65b] outline-none transition-all">
            <option value="none">无</option>
            <option value="forest">森林</option>
            <option value="city">城市</option>
            <option value="indoor">室内</option>
            <option value="underground">地下</option>
            <option value="ocean">海洋</option>
          </select>
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
  { id: 'narrative', label: '叙事设定' },
  { id: 'cinematics', label: '演出配置' },
  { id: 'audio', label: '音频设计' },
];

const activeTabLabel = computed(() => {
  const t = tabs.find(t => t.id === activeTab.value);
  return t ? `步骤 ${tabs.indexOf(t) + 1}/${tabs.length}` : '';
});

const narrativeTypes = [
  { id: 'linear', label: '线性叙事', desc: '单线剧情，无分支' },
  { id: 'branching', label: '分支叙事', desc: '多分支路线与结局' },
  { id: 'open', label: '开放叙事', desc: '碎片化叙事，自由探索' },
];

const dialogueStyles = [
  { id: 'vn', label: '视觉小说', desc: '立绘+文本框经典AVG' },
  { id: 'free', label: '自由对话', desc: '非固定位置对话气泡' },
  { id: 'timeline', label: '时间轴', desc: '时间线驱动对话事件' },
];

const consequenceScopes = [
  { id: 'chapter', label: '章节内影响', desc: '选择仅影响当前章节' },
  { id: 'global', label: '全局影响', desc: '选择贯穿整个故事' },
  { id: 'none', label: '无影响', desc: '纯观赏性选择' },
];

const cameraStyles = [
  { id: 'static', label: '静态镜头', desc: '固定视角切换' },
  { id: 'cinematic', label: '电影化运镜', desc: '推拉摇移动态镜头' },
  { id: 'first_person', label: '第一人称', desc: '主角视角叙事' },
];

const uiThemes = [
  { id: 'dark', label: '暗色主题', desc: '深色背景适配剧情' },
  { id: 'light', label: '亮色主题', desc: '浅色清新风格' },
  { id: 'custom', label: '自定义', desc: '后续自行配置' },
];

const voiceOptions = [
  { id: 'none', label: '仅文本', desc: '无语音，纯文字演出' },
  { id: 'partial', label: '部分语音', desc: '关键场景配音' },
  { id: 'full', label: '全程语音', desc: '全文本配音覆盖' },
];

const storySettings = ref({
  gameTitle: '',
  author: '',
  narrativeType: 'linear',
  dialogueStyle: 'vn',
  consequenceScope: 'chapter',
  cameraStyle: 'static',
  textSpeed: 3,
  autoPlay: false,
  skipEnabled: true,
  uiTheme: 'dark',
  bgmVolume: 80,
  sfxVolume: 100,
  voiceOption: 'partial',
  ambientPreset: 'none',
});

onMounted(async () => {
  try {
    const path = await projectLauncherService.getDefaultProjectPath();
    if (path) projectPath.value = path.data;
  } catch (error) {
    console.error('StoryMode 初始化失败:', error);
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
      mode: 'story',
      settings: {
        ...storySettings.value,
        defaultScene: 'story_basic',
        realTimeRender: false,
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
    await projectLauncherService.setProjectMode('story', storySettings.value);
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
