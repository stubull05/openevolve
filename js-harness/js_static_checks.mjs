// /opt/js-harness/js_static_checks.mjs
import { promises as fs } from "fs";
import path from "path";

const root = process.argv[2] || "/workspace/target";
const SRC = ["desktop/src", "desktop"]; // candidate roots
const exts = [".js",".jsx",".ts",".tsx"];

const mustTimeframes = ["1d","1w","1m","3m","1y"];
const chartHints = [/rightPriceScale/i, /timeScale/i, /(lightweight-)?charts/i];
const konvaHints = [/react-konva|konva/i, /\b(Stage|Layer|Line)\b/];
const chatHints = [/chat/i, /(aria-label|role|id|class(Name)?)\s*=\s*["'`](.*chat.*)["'`]/i];
const draggableHints = [/draggable\s*=\s*{?true}?/i, /react-grid-layout|drag|resize/i];

function isCode(file){ return exts.includes(path.extname(file).toLowerCase()); }

async function rglob(dir, out=[]) {
  let ents; try { ents = await fs.readdir(dir, { withFileTypes:true }); } catch { return out; }
  for (const e of ents) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (!/node_modules|\.git|dist|build|\.next|out/i.test(p)) await rglob(p, out);
    } else if (isCode(p)) out.push(p);
  }
  return out;
}

function hasAny(hints, text){ return hints.some(rx => rx.test(text)); }
function countMatches(rx, text){ return (text.match(rx) || []).length; }

(async () => {
  // Gather files
  const roots = [];
  for (const s of SRC) {
    const p = path.join(root, s);
    try { if ((await fs.stat(p)).isDirectory()) roots.push(p); } catch {}
  }
  if (roots.length === 0) {
    console.log("[ui] No frontend source directories found; skipping.");
    process.exit(0);
  }
  const files = (await Promise.all(roots.map(r => rglob(r)))).flat();
  if (!files.length) { console.log("[ui] No JS/TS files; skipping."); process.exit(0); }

  let ok = true;
  let tfHits = 0, chartFiles = 0, konvaFiles = 0, chatFiles = 0, dragHits = 0;

  for (const f of files) {
    const t = await fs.readFile(f, "utf8");

    // timeframe controls
    const tfPresent = mustTimeframes.some(tf => t.includes(`"${tf}"`) || t.includes(`'${tf}'`));
    if (tfPresent) tfHits++;

    // chart axes/time config
    if (hasAny(chartHints, t)) chartFiles++;

    // konva drawing overlay
    if (hasAny(konvaHints, t)) konvaFiles++;

    // chat “visible” hint (container present)
    if (hasAny(chatHints, t)) chatFiles++;

    // draggable/relocatable panels
    if (hasAny(draggableHints, t)) dragHits++;
  }

  // Define “correct” thresholds (tunable)
  if (tfHits === 0) { console.error("[ui] Missing timeframe controls (1d/1w/1m/3m/1y)."); ok = false; }
  if (chartFiles === 0) { console.error("[ui] Chart axes/time configuration not found."); ok = false; }
  if (konvaFiles === 0) { console.error("[ui] Konva overlay (react-konva/Stage/Layer/Line) not found."); ok = false; }
  if (chatFiles === 0) { console.error("[ui] Chat container not detected (id/class/aria-label containing 'chat')."); ok = false; }
  if (dragHits === 0) { console.error("[ui] Draggable/resizable panels not detected."); ok = false; }

  if (!ok) process.exit(1);
  console.log(`[ui] OK: tf=${tfHits} chart=${chartFiles} konva=${konvaFiles} chat=${chatFiles} drag=${dragHits}`);
})();
