/**
 * 面板静态注册表 - 替代 Python register_web 装饰器中的 UI 元数据
 * 每个面板的 id 必须与 Python 端 module_name 一致（用于 cefQuery 路由）
 */
import SceneBar from '@/views/sidebar/SceneBar.vue';
import ObjectPanel from '@/views/sidebar/Object.vue';
import Pet from '@/views/tools/Pet.vue';
import LogView from '@/views/sidebar/LogView.vue';
import FileManager from '@/views/sidebar/FileManager.vue';
import ProjectSettings from '@/views/sidebar/ProjectSettings.vue';
import AITalkBar from '@/views/sidebar/AITalkBar.vue';
import EditorSettings from '@/views/sidebar/EditorSettings.vue';
import NetworkPanel from '@/views/sidebar/Network.vue';
import LightFieldCalibrationPanel from '@/components/panels/LightFieldCalibrationPanel.vue';

export const PLUGIN_MANIFEST = [
  {
    id: 'SceneTools',
    routePath: '/SceneBar',
    displayName: '场景工具',
    pageType: 'view',
    defaultDock: 'right',
    defaultWidth: 300,
    defaultHeight: 600,
    autoInit: true,
    component: SceneBar,
  },
  {
    id: 'LightFieldCalibration',
    routePath: '/LightFieldCalibration',
    displayName: '光场3D UI标定',
    pageType: 'view',
    defaultDock: 'right',
    defaultWidth: 300,
    defaultHeight: 300,
    autoInit: false,
    component: LightFieldCalibrationPanel,
  },
  {
    id: 'SceneDatas',
    routePath: '/Object',
    displayName: '详情工具',
    pageType: 'view',
    defaultDock: 'right',
    defaultWidth: 300,
    defaultHeight: 400,
    autoInit: true,
    component: ObjectPanel,
  },
  {
    id: 'AITool',
    routePath: '/Pet',
    displayName: '白菜助手',
    pageType: 'plugin',
    defaultDock: 'bottom',
    defaultWidth: 200,
    defaultHeight: 200,
    autoInit: true,
    component: Pet,
  },
  {
    id: 'LogTool',
    routePath: '/LogView',
    displayName: '日志工具',
    pageType: 'view',
    defaultDock: 'bottom',
    defaultWidth: 1100,
    defaultHeight: 200,
    autoInit: true,
    component: LogView,
  },
  {
    id: 'FileManager',
    routePath: '/FileManager',
    displayName: '文件管理器',
    pageType: 'view',
    defaultDock: 'left',
    defaultWidth: 300,
    defaultHeight: 600,
    autoInit: false,
    component: FileManager,
  },
  {
    id: 'ProjectSettings',
    routePath: '/ProjectSettings',
    displayName: '项目设置',
    pageType: 'special',
    defaultDock: 'center',
    defaultWidth: 600,
    defaultHeight: 800,
    autoInit: false,
    component: ProjectSettings,
  },
  {
    id: 'AITalkBar',
    routePath: '/AITalkBar',
    displayName: 'AI 对话',
    pageType: 'plugin',
    defaultDock: 'right',
    defaultWidth: 400,
    defaultHeight: 600,
    autoInit: false,
    component: AITalkBar,
  },
  {
    id: 'EditorSettings',
    routePath: '/SetUp',
    displayName: '编辑器设置',
    pageType: 'special',
    defaultDock: 'center',
    defaultWidth: 450,
    defaultHeight: 550,
    autoInit: false,
    component: EditorSettings,
  },
  {
    id: 'Network',
    routePath: '/Network',
    displayName: '网络协作',
    pageType: 'plugin',
    defaultDock: 'right',
    defaultWidth: 300,
    defaultHeight: 400,
    autoInit: false,
    component: NetworkPanel,
  },
];

/** 按 id 快速查找 */
export function getPluginManifest(id) {
  return PLUGIN_MANIFEST.find((p) => p.id === id);
}
