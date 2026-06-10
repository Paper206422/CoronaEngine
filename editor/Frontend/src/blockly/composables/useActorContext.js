/**
 * 共享的 Actor 上下文状态
 * 用于在 Object.vue / SceneBar.vue（场景物体选择）和 BlocklyWorkspace.vue（积木编辑器）之间
 * 传递当前选中的 scene_name + actor_name。
 *
 * 使用模块级响应式变量 + localStorage 双写，兼容 CEF 多标签页架构下跨实例通信。
 */

import { ref } from 'vue';

const STORAGE_KEY_SCENE = '__bl_actor_ctx_scene__';
const STORAGE_KEY_ACTOR = '__bl_actor_ctx_actor__';
const STORAGE_KEY_TARGET_TYPE = '__bl_target_type__';

/** 当前选中的场景名称 */
export const currentSceneName = ref(localStorage.getItem(STORAGE_KEY_SCENE) || '');

/** 当前选中的 Actor 名称 */
export const currentActorName = ref(localStorage.getItem(STORAGE_KEY_ACTOR) || '');

/** 当前积木目标类型：actor | project */
export const currentTargetType = ref(localStorage.getItem(STORAGE_KEY_TARGET_TYPE) || 'actor');

/**
 * 设置当前目标 Actor。
 * 同时写入模块级 ref（同路由组件内共享）和 localStorage（跨 CEF 标签页共享）。
 */
export function setActorContext(sceneName, actorName) {
  const s = sceneName || '';
  const a = actorName || '';
  currentTargetType.value = 'actor';
  currentSceneName.value = s;
  currentActorName.value = a;
  localStorage.setItem(STORAGE_KEY_TARGET_TYPE, 'actor');
  localStorage.setItem(STORAGE_KEY_SCENE, s);
  localStorage.setItem(STORAGE_KEY_ACTOR, a);
}

/**
 * 切换到项目级全局积木目标。
 */
export function setProjectGlobalContext() {
  currentTargetType.value = 'project';
  currentSceneName.value = '';
  currentActorName.value = '';
  localStorage.setItem(STORAGE_KEY_TARGET_TYPE, 'project');
  localStorage.removeItem(STORAGE_KEY_SCENE);
  localStorage.removeItem(STORAGE_KEY_ACTOR);
}

/**
 * 清除 Actor 上下文。
 */
export function clearActorContext() {
  currentTargetType.value = 'actor';
  currentSceneName.value = '';
  currentActorName.value = '';
  localStorage.setItem(STORAGE_KEY_TARGET_TYPE, 'actor');
  localStorage.removeItem(STORAGE_KEY_SCENE);
  localStorage.removeItem(STORAGE_KEY_ACTOR);
}

/**
 * 从 localStorage 同步上下文到模块级 ref。
 * 用于 BlocklyWorkspace 等跨标签页实例在挂载或运行前拉取最新状态。
 */
export function syncActorContextFromStorage() {
  currentTargetType.value = localStorage.getItem(STORAGE_KEY_TARGET_TYPE) || 'actor';
  currentSceneName.value = localStorage.getItem(STORAGE_KEY_SCENE) || '';
  currentActorName.value = localStorage.getItem(STORAGE_KEY_ACTOR) || '';
}

/**
 * 以纯对象形式获取当前上下文（优先 ref，兜底 localStorage）。
 * 用于 handleRunCode 等需要可靠读取 Actor 上下文的场景。
 */
export function getActorContext() {
  const scene =
    currentSceneName.value || localStorage.getItem(STORAGE_KEY_SCENE) || '';
  const actor =
    currentActorName.value || localStorage.getItem(STORAGE_KEY_ACTOR) || '';
  return { scene, actor };
}

/**
 * 获取当前积木目标。项目全局目标不携带 scene/actor。
 */
export function getBlockTargetContext() {
  const targetType =
    currentTargetType.value || localStorage.getItem(STORAGE_KEY_TARGET_TYPE) || 'actor';
  if (targetType === 'project') {
    return { targetType: 'project', scene: '', actor: '' };
  }
  const { scene, actor } = getActorContext();
  return { targetType: 'actor', scene, actor };
}
