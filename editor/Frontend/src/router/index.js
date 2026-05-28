// 路由文件
import { createRouter, createWebHashHistory } from 'vue-router';

const routes = [
  {
    path: '/',
    name: 'MainPage',
    component: () => import('../views/layout/MainPage.vue'),
  },
  {
    path: '/StartScreen',
    name: 'StartScreen',
    component: () => import('../views/layout/StartScreen.vue'),
  },
  {
    path: '/ProjectLauncher',
    name: 'ProjectLauncher',
    component: () => import('../views/layout/ProjectLauncher.vue'),
  },
  {
    path: '/StoryMode',
    name: 'StoryMode',
    component: () => import('../views/layout/StoryMode.vue'),
  },
  {
    path: '/CreateGame',
    name: 'CreateGame',
    component: () => import('../views/layout/CreateGame.vue'),
  },
  {
    path: '/RecentGames',
    name: 'RecentGames',
    component: () => import('../views/layout/RecentGames.vue'),
  },
  {
    path: '/AITalkBar',
    name: 'AITalkBar',
    component: () => import('../views/sidebar/AITalkBar.vue'),
  },
  {
    path: '/SceneBar',
    name: 'SceneBar',
    component: () => import('../views/sidebar/SceneBar.vue'),
  },
  {
    path: '/Object',
    name: 'Object',
    component: () => import('../views/sidebar/Object.vue'),
  },
  {
    path: '/Pet',
    name: 'Pet',
    component: () => import('../views/tools/Pet.vue'),
  },
  {
    path: '/LogView',
    name: 'LogView',
    component: () => import('../views/sidebar/LogView.vue'),
  },
  {
    path: '/FileManager',
    name: 'FileManager',
    component: () => import('../views/sidebar/FileManager.vue'),
  },
  {
    path: '/SetUp',
    name: 'SetUp',
    component: () => import('../views/sidebar/EditorSettings.vue'),
  },
  {
    path: '/ProjectSettings',
    name: 'ProjectSettings',
    component: () => import('../views/sidebar/ProjectSettings.vue'),
  },
  {
    path: '/ScratchTool',
    name: 'ScratchTool',
    component: () => import('../blockly/components/BlocklyWorkspace.vue'),
  },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
});

router.beforeEach((to, from) => {});

window.__ROUTES__ = routes;

export default router;
