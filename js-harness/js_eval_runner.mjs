// Lightweight JS/TS/JSX static checks without extra deps.
// - Syntax check for .js using `node --check`
// - Heuristic presence checks for JSX/TS files (we don't parse them here)

import { promises as fs } from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';

const root = process.argv[2] || '/workspace/target';
const exts = ['.js', '.jsx', '.ts', '.tsx'];

function isCode(file) { return exts.includes(path.extname(file).toLowerCase()); }

async function rglob(dir, out=[]) {
  let ents;
  try { ents = await fs.readdir(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of ents) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (!/node_modules|\.git|dist|build|\.next|out/i.test(p)) await rglob(p, out);
    } else if (isCode(p)) {
      out.push(p);
    }
  }
  return out;
}

function nodeCheck(file) {
  const res = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
  return res.status === 0;
}

const isJSXish = (txt) => /<\w|className=|React/.test(txt);

(async () => {
  const files = await rglob(root);
  if (!files.length) {
    console.log('[ui] No JS/TS/JSX files; treating as pass.');
    process.exit(0);
  }

  let failures = 0;
  for (const f of files) {
    const ext = path.extname(f).toLowerCase();
    if (ext === '.js') {
      if (!nodeCheck(f)) {
        console.error('[ui] Syntax error in', f);
        failures++;
      }
    } else {
      // Heuristic sanity for JSX/TS/TSX
      const txt = await fs.readFile(f, 'utf8').catch(() => '');
      if (ext === '.jsx' && !isJSXish(txt)) {
        console.warn('[ui] .jsx without JSX-like content:', f);
      }
      // Do not fail TS/TSX/JSX; keep harness lenient
    }
  }

  if (failures > 0) process.exit(1);
  console.log('[ui] JS harness OK');
  process.exit(0);
})();
