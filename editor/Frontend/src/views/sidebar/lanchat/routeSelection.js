export function resolveSelectedTargetKey(currentKey, options = []) {
  const key = String(currentKey || '').trim();
  const list = Array.isArray(options) ? options : [];
  if (key && list.some((item) => item.key === key)) return key;
  return list[0]?.key || 'scene';
}

export function targetPayloadForKey(key, options = []) {
  const list = Array.isArray(options) ? options : [];
  const target = list.find((item) => item.key === key) || list[0] || {};
  return {
    scope: target.scope || 'scene',
    agentId: target.agentId || '',
    agentName: target.agentName || '',
    planId: target.planId || '',
  };
}

export function routeGuardMessage(action, target = {}, text = '') {
  if (/^@([^\s，,：:]+)/.test(String(text || '').trim())) return '';
  const draftAction = String(action || '').trim();
  const scope = String(target?.scope || '').trim();
  if (draftAction === 'plan' && scope === 'group') {
    return '生成方案需要先选择一个负责整理方案的 Agent。';
  }
  if (draftAction === 'supplement' && scope !== 'agent' && scope !== 'plan') {
    return '补充要求需要选择已有方案对应的 Agent。';
  }
  if (draftAction === 'generate' && scope !== 'agent' && scope !== 'plan') {
    return '确认生成需要选择已有方案对应的 Agent。';
  }
  return '';
}
