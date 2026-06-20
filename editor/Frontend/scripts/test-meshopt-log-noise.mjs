import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const source = readFileSync(
  join(repoRoot, 'modules/corona_resource/src/resource/types/parse_common.h'),
  'utf8'
);

const fail = (message) => {
  throw new Error(message);
};

const phase1LoopLog = 'CFW_LOG_TRACE("[MeshOpt] Mesh \'{}\' phase1: error {:.4f}, unique vertices {}"';
if (!source.includes(phase1LoopLog)) {
  fail('MeshOpt phase1 per-error logs must be TRACE to avoid terrain_detail log floods');
}

const alreadyWithinLog =
  'CFW_LOG_TRACE("[MeshOpt] Mesh \'{}\': already within uint16 vertex limit ({} <= {}), skipping simplification"';
if (!source.includes(alreadyWithinLog)) {
  fail('MeshOpt already-within-limit logs must be TRACE because large terrain OBJ files contain many submeshes');
}

console.log('MeshOpt log-noise constraints OK');
