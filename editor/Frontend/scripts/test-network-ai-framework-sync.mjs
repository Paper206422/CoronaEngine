import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(join(root, path), 'utf8');
const fail = (message) => {
  throw new Error(message);
};
const assertIncludes = (source, needle, message) => {
  if (!source.includes(needle)) fail(message);
};

const networkPanel = read('src/views/sidebar/Network.vue');
const syncPolicy = read('../CoronaCore/core/network_sync_policy.py');
const networkSystem = read('../../src/systems/network/network_system.cpp');

for (const name of [
  '__room_box',
  '__room_terrain',
  '__terrain_grass',
  '__terrain_boundary',
  '__interior_floor',
  '__foundation_surface',
]) {
  assertIncludes(syncPolicy, name, `Python sync policy must whitelist ${name}`);
  assertIncludes(
    networkPanel,
    name,
    `Network panel must mirror the AI framework whitelist for ${name}`
  );
}

assertIncludes(syncPolicy, '__shell_', 'Python sync policy must whitelist shell actor prefixes');
assertIncludes(
  networkPanel,
  '__shell_',
  'Network panel must mirror the shell actor prefix whitelist'
);
assertIncludes(
  networkPanel,
  'function isAiSceneFrameworkSyncName',
  'Network panel must distinguish AI framework actors from generic internal __ actors'
);
assertIncludes(
  networkPanel,
  'function isInternalActorSyncName',
  'Network panel must keep filtering non-syncable internal actors'
);

const isActorSyncableStart = networkPanel.indexOf('function isActorSyncable');
const broadcastSnapshotStart = networkPanel.indexOf('async function broadcastCurrentSceneSnapshot');
const isActorSyncableBody = networkPanel.slice(isActorSyncableStart, broadcastSnapshotStart);
assertIncludes(
  isActorSyncableBody,
  'isInternalActorSyncName(actorData.name)',
  'Actor create broadcasts must allow whitelisted AI framework names through the internal-name filter'
);
assertIncludes(
  isActorSyncableBody,
  "actorData.actor_type === 'actor'",
  'Frontend actor sync policy must mirror Python actor_type filtering'
);
assertIncludes(
  isActorSyncableBody,
  'actorData.geometry',
  'Frontend actor sync policy must require geometry data like Python snapshot policy'
);

assertIncludes(
  networkPanel,
  'broadcastCurrentSceneSnapshot(currentSceneName.value, false, false)',
  'Host periodic snapshots must not resend actor create events every calibration tick'
);
assertIncludes(
  networkPanel,
  'broadcastCurrentSceneSnapshot(sceneName, true, true)',
  'Host must still include actor create events when answering explicit snapshot requests'
);
assertIncludes(
  networkPanel,
  'const PENDING_POLL_BATCH_LIMIT = 16',
  'Network panel must drain multiple pending collaboration events per poll tick'
);
assertIncludes(
  networkPanel,
  'for (let i = 0; i < PENDING_POLL_BATCH_LIMIT; i += 1)',
  'Network panel must process pending collaboration queues in bounded batches'
);

const createPollIndex = networkPanel.indexOf('pollPendingActorCreate');
const snapshotPollIndex = networkPanel.indexOf('pollPendingSceneSnapshot');
const statePollIndex = networkPanel.indexOf('pollPendingActorStateUpdate');
if (!(createPollIndex >= 0 && snapshotPollIndex >= 0 && statePollIndex >= 0)) {
  fail('Network panel must poll actor create, snapshot, and actor state queues');
}
if (!(createPollIndex < snapshotPollIndex && createPollIndex < statePollIndex)) {
  fail('Network panel must apply completed actor creates before snapshots and state updates');
}

assertIncludes(
  networkPanel,
  'remoteRegisteredActorIdentities',
  'Network panel must remember remote identity registrations and skip duplicate register calls'
);
assertIncludes(
  networkPanel,
  'snapshotActorCreateKeys',
  'Network panel must dedupe actor-create packets sent as snapshot request fallback'
);
assertIncludes(
  networkPanel,
  "const identityKey = `${actorGuid}:${actorHandle}:${locallyOwned ? 'local' : 'remote'}`",
  'Network panel must key identity dedupe by guid, handle, and ownership'
);
assertIncludes(
  networkPanel,
  'const registered = await networkService.registerActorIdentity',
  'Network panel must inspect actor identity registration results'
);
assertIncludes(
  networkPanel,
  'registered?.ok !== true',
  'Network panel must not mark identity registration deduped when registration fails'
);

assertIncludes(
  networkSystem,
  'upsert_pending_actor_create',
  'NetworkSystem must dedupe pending actor create actions by actor_guid/scene/model'
);
assertIncludes(
  networkSystem,
  'upsert_pending_actor_scene_snapshot',
  'NetworkSystem must overwrite pending snapshots per scene instead of queueing duplicates'
);
assertIncludes(
  networkSystem,
  'pending_file_transfer_for_actor',
  'NetworkSystem must suppress duplicate ACTOR_CREATE packets while a file transfer for that actor is pending'
);
assertIncludes(
  networkSystem,
  '!impl_->incoming_transfers.empty()',
  'NetworkSystem has_pending_transfers must include in-progress incoming file transfers'
);
assertIncludes(
  networkSystem,
  '!impl_->pending_file_transfer_groups.empty()',
  'NetworkSystem has_pending_transfers must include actor file transfer groups'
);

console.log('Network AI framework sync constraints OK');
