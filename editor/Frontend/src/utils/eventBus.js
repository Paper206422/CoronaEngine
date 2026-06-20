import { Bridge } from '@/utils/bridge.js';

/**
 * 事件总线 —— 同一 JS 上下文内的发布-订阅
 *
 * 消息流：
 *   C++/Python → ExecuteJavaScript
 *     → window.__coronaEmit(event, ...args)        ← 仅主 Tab 收到
 *     → 内部 emit → dock 内所有面板组件收到
 *     → 自动 relay 到 C++ DockCommand broadcast  → 所有 pop-out Tab 也收到
 *   pop-out Tab 收到 C++ cross-tab broadcast:
 *     → window.__coronaEmit(event, ...args, {_fromCross:1})
 *     → 内部 emit → pop-out Tab 内的面板组件收到
 *     → 不再 relay（避免广播风暴）
 */
export const coronaEventBus = {
  _handlers: {},

  on(event, handler) {
    if (!this._handlers[event]) {
      this._handlers[event] = [];
    }
    this._handlers[event].push(handler);
  },

  off(event, handler) {
    if (!this._handlers[event]) return;
    if (!handler) {
      delete this._handlers[event];
    } else {
      this._handlers[event] = this._handlers[event].filter((h) => h !== handler);
    }
  },

  emit(event, ...args) {
    if (!this._handlers[event]) return;
    for (const h of this._handlers[event]) {
      try {
        h(...args);
      } catch (e) {
        console.error(`[coronaEventBus] handler error for "${event}":`, e);
      }
    }
  },
};

/**
 * 统一入口：C++ ExecuteJavaScript 或 Python execute_javascript 调用
 * 主 Tab 收到本地推送后，通过 C++ DockCommand 中转给所有 pop-out Tab
 */
window.__coronaEmit = (event, ...rest) => {
  // 检查最后一个参数是否为选项对象 {_fromCross: 1}
  const last = rest.length > 0 ? rest[rest.length - 1] : undefined;
  const isCross = last && typeof last === 'object' && last._fromCross;
  const args = isCross ? rest.slice(0, -1) : rest;

  // 1. 本地 emit（所有在同一 Tab 内的 Vue 组件都会收到）
  coronaEventBus.emit(event, ...args);

  // 2. 如果是本地推送（不是 cross-tab 中继），则通过 C++ 广播给其他 Tab
  if (!isCross && (event === 'actor-change' || event === 'log-batch' ||
      event === 'scene-tree-changed' || event === 'scene-rename' ||
      event === 'scene-add' || event === 'transform-update' ||
      event === 'ai-chunk' || event === 'engine-started' ||
      event === 'lanchat-event' || event === 'actor-sync-broadcast' ||
      event === 'actor-transform-sync-broadcast' ||
      event === 'actor-delete-sync-broadcast' ||
      event === 'actor-state-sync-broadcast' ||
      event === 'actor-ownership-claim' ||
      event === 'file-sync-status' || event === 'import-asset-complete')) {
    Bridge.callDockCommand({ cmd: 'broadcast', event, payload: args })
      .catch(() => {});
  }
};
