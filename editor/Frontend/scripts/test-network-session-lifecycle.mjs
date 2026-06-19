import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const networkVuePath = resolve('src/views/sidebar/Network.vue');
const source = readFileSync(networkVuePath, 'utf8');

const startSessionBody = source.match(/async function startSessionAsRole\(role\) \{([\s\S]*?)\n\}/);
assert.ok(startSessionBody, 'Network.vue should define startSessionAsRole');

const attachBody = source.match(/async function attachExistingSession\([^)]*\) \{([\s\S]*?)\n\}/);
assert.ok(attachBody, 'Network.vue should define attachExistingSession');
assert.ok(
  attachBody[1].includes('networkService.getSessionInfo'),
  'attachExistingSession should inspect the existing native session'
);
assert.ok(
  attachBody[1].includes('applySessionInfo') && attachBody[1].includes('startPolling'),
  'attachExistingSession should apply active session info and start polling'
);

const startBody = startSessionBody[1];
assert.ok(
  startBody.includes('attachExistingSession'),
  'startSessionAsRole should inspect an existing native session before starting'
);
assert.ok(
  startBody.indexOf('attachExistingSession') < startBody.indexOf('networkService.startSession'),
  'startSessionAsRole should attach or reject before calling startSession'
);
assert.ok(
  startBody.includes('已有网络会话正在运行'),
  'startSessionAsRole should surface a role mismatch instead of overwriting the native role'
);

const mountedBody = source.match(/onMounted\(\(\) => \{([\s\S]*?)\n\}\);/);
assert.ok(mountedBody, 'Network.vue should define onMounted');

assert.ok(
  mountedBody[1].includes('attachExistingSession'),
  'Network.vue should attach to an active native session when the panel is mounted'
);
