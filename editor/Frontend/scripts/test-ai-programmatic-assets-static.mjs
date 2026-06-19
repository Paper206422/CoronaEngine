import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const sceneComposer = readFileSync(
  join(repoRoot, 'editor/plugins/AITool/cai_extensions/agent/scene_composer.py'),
  'utf8'
);

const fail = (message) => {
  throw new Error(message);
};
const assertIncludes = (source, needle, message) => {
  if (!source.includes(needle)) fail(message);
};
const assertNotIncludes = (source, needle, message) => {
  if (source.includes(needle)) fail(message);
};

assertIncludes(
  sceneComposer,
  'def _generated_asset_dir(self)',
  'SceneComposer must create a per-generation project Resource directory for procedural assets'
);
assertIncludes(
  sceneComposer,
  'Resource" / "generated" / "scene_composer"',
  'Procedural assets must live under project Resource/generated/scene_composer'
);
assertNotIncludes(
  sceneComposer,
  '_tf.gettempdir(), "corona_room_box"',
  'Procedural scene assets must not use the fixed temp corona_room_box directory'
);

for (const routeName of [
  'box_route',
  'terrain_route',
  'grass_route',
  'boundary_route',
  'carpet_route',
  'foundation_route',
]) {
  assertIncludes(
    sceneComposer,
    `route=${routeName}`,
    `Procedural actor must use stable project-relative ${routeName}`
  );
}

console.log('AI procedural asset path constraints OK');
