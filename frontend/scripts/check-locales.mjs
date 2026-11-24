// Fails the build if any locale is missing a key present in en.json,
// or has an extra key, or an empty value. Run via `npm run check-locales`.
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'messages');
const files = readdirSync(dir).filter((f) => f.endsWith('.json')).sort();
const base = JSON.parse(readFileSync(join(dir, 'en.json'), 'utf8'));
const baseKeys = Object.keys(base).sort();
let failed = false;

for (const f of files) {
  const data = JSON.parse(readFileSync(join(dir, f), 'utf8'));
  const keys = Object.keys(data).sort();
  const missing = baseKeys.filter((k) => !(k in data));
  const extra = keys.filter((k) => !(k in base));
  const empty = keys.filter((k) => typeof data[k] !== 'string' || data[k].trim() === '');
  if (missing.length || extra.length || empty.length) {
    failed = true;
    console.error(`${f}: missing=[${missing.join(', ')}] extra=[${extra.join(', ')}] empty=[${empty.join(', ')}]`);
  } else {
    console.log(`${f}: OK (${keys.length} keys)`);
  }
}
if (failed) { console.error('Locale check FAILED'); process.exit(1); }
console.log('Locale check passed.');
