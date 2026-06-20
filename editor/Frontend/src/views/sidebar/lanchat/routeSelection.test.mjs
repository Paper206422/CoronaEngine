import assert from 'node:assert/strict';

import {
  resolveSelectedTargetKey,
  routeGuardMessage,
  targetPayloadForKey,
} from './routeSelection.js';

const options = [
  { key: 'agent:elder', label: '长者', scope: 'agent', agentId: 'agent-elder', agentName: '长者' },
  { key: 'agent:girl', label: '小女孩', scope: 'agent', agentId: 'agent-girl', agentName: '小女孩' },
  { key: 'agent:merchant', label: '商人', scope: 'agent', agentId: 'agent-merchant', agentName: '商人' },
  { key: 'group', label: '专家组', scope: 'group' },
  { key: 'scene', label: '当前场景', scope: 'scene' },
];

assert.equal(resolveSelectedTargetKey('scene', options), 'scene');
assert.equal(resolveSelectedTargetKey('agent:merchant', options), 'agent:merchant');
assert.equal(resolveSelectedTargetKey('missing', options), 'agent:elder');

assert.deepEqual(targetPayloadForKey('agent:merchant', options), {
  scope: 'agent',
  agentId: 'agent-merchant',
  agentName: '商人',
  planId: '',
});

assert.deepEqual(targetPayloadForKey('scene', options), {
  scope: 'scene',
  agentId: '',
  agentName: '',
  planId: '',
});

assert.equal(routeGuardMessage('chat', options[0]), '');
assert.equal(routeGuardMessage('plan', options[0]), '');
assert.equal(
  routeGuardMessage('plan', { key: 'group', label: '专家组', scope: 'group' }),
  '生成方案需要先选择一个负责整理方案的 Agent。'
);
assert.equal(
  routeGuardMessage('generate', { key: 'scene', label: '当前场景', scope: 'scene' }),
  '确认生成需要选择已有方案对应的 Agent。'
);
assert.equal(
  routeGuardMessage('supplement', { key: 'group', label: '专家组', scope: 'group' }),
  '补充要求需要选择已有方案对应的 Agent。'
);
assert.equal(
  routeGuardMessage('plan', { key: 'group', label: '专家组', scope: 'group' }, '@长者 帮我设计客厅'),
  ''
);

console.log('[OK] lanchat route selection keeps explicit target stable');
