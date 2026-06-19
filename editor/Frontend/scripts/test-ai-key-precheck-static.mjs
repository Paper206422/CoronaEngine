import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const read = (path) => readFileSync(join(repoRoot, path), 'utf8');
const fail = (message) => {
  throw new Error(message);
};
const assertIncludes = (source, needle, message) => {
  if (!source.includes(needle)) fail(message);
};

const modelTools = read('editor/plugins/AITool/Quasar/ai_modules/three_d_generate/tools/model_tools.py');

assertIncludes(
  modelTools,
  'def _is_placeholder_api_key',
  '3D generation tools must detect placeholder API keys before making provider requests'
);
assertIncludes(
  modelTools,
  '_is_placeholder_api_key(api_key)',
  'Rodin3D tool loading must reject placeholder API keys'
);
assertIncludes(
  modelTools,
  'all_keys = [k for k in all_keys if not _is_placeholder_api_key(k)]',
  'Hunyuan3D tool loading must remove placeholder API keys before creating clients'
);

console.log('AI API key precheck static constraints OK');
