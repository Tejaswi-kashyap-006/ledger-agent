// Rhythm checker: every line of text on the sheet must sit on its ruled line, and no rule may cross a glyph.
//
//   1. ledger serve --port 8765                (a seeded demo db is best: python scripts/seed_demo_db.py data/demo.db)
//   2. chrome --headless=new --remote-debugging-port=9333 --user-data-dir=<tmp dir> about:blank
//   3. node scripts/check-rhythm.mjs [width]  (try 1440, 1024 and 390)
//
// For each text node it takes the line box (Range.getClientRects), adds the font's measured ascent to get the real
// baseline, and requires baseline mod 28 == 18 (2px above the rule drawn at --rule-y = 20). Exit code 1 on failure.
import { open } from "./cdp.mjs";
const width = Number(process.argv[2] ?? 1440);
const routes = ["/", "/import", "/review", "/audit", "/ledger", "/ask", "/reports", "/recurring", "/settings"];
const p = await open({ width, height: 1000 });
const CHECK = `(() => {
  const LINE = 28, RULE_Y = 20, WANT = 18, TOL = 1.6;
  const rules = document.querySelector(".sheet__rules");
  if (!rules) return JSON.stringify({ error: "no sheet" });
  const top0 = rules.getBoundingClientRect().top;
  // text on opaque "laid-on" objects doesn't sit on the page's rules, by design
  const SKIP = ".entry-card, .receipt, .letterbox, .memory-slip, .slip, .chart-tip, .picker__list, kbd, .stamp, .btn--ink, .btn--stamp, .quick-pick, svg, .sr-only, .skip-link, select, option, textarea, .tabs, .spine";
  const ctx = document.createElement("canvas").getContext("2d");
  const walker = document.createTreeWalker(document.querySelector(".sheet__body"), NodeFilter.SHOW_TEXT);
  const bad = [], seen = new Set(); let lines = 0;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.data.trim()) continue;
    const el = n.parentElement;
    if (!el || el.closest(SKIP)) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || +cs.opacity === 0 || el.closest("[hidden]")) continue;
    ctx.font = cs.fontStyle + " " + cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily;
    const ascent = ctx.measureText("Hg").fontBoundingBoxAscent, size = parseFloat(cs.fontSize);
    const r = document.createRange(); r.selectNodeContents(n);
    for (const rect of r.getClientRects()) {
      if (!rect.width) continue;
      lines++;
      const baseline = rect.top + ascent - top0;
      const off = ((baseline % LINE) + LINE) % LINE;
      // a rule strikes the glyphs if one falls between x-height top and just above the baseline
      const hit = [0, 1, 2, 3, 4].map((k) => Math.floor((baseline - size) / LINE) * LINE + RULE_Y + k * LINE)
        .find((y) => y > baseline - 0.55 * size && y < baseline - 1);
      const knockout = !!el.closest(".hero__value, .stat-line__big, .folio-head h1");   // set on clean paper by design
      if (Math.abs(off - WANT) > TOL || (hit !== undefined && !knockout)) {
        const key = el.className + "|" + Math.round(off);
        if (seen.has(key)) continue; seen.add(key);
        bad.push({ el: el.tagName.toLowerCase() + (typeof el.className === "string" && el.className ? "." + el.className.trim().replace(/ +/g, ".") : ""),
                   text: n.data.trim().slice(0, 28), baselineInBand: +off.toFixed(1), strike: hit !== undefined && !knockout });
      }
    }
  }
  // horizontal: a hanging title unit shares one left edge
  const h = [];
  for (const head of document.querySelectorAll(".folio-head")) {
    const k = head.querySelector(".kicker")?.getBoundingClientRect().left, t = head.querySelector("h1")?.getBoundingClientRect().left;
    if (k != null && t != null && Math.abs(k - t) > 1) h.push("kicker " + Math.round(k) + " vs title " + Math.round(t));
  }
  const hl = document.querySelector(".hero__label")?.getBoundingClientRect().left, hv = document.querySelector(".hero__value")?.getBoundingClientRect().left;
  if (hl != null && hv != null && Math.abs(hl - hv) > 1) h.push("hero label " + Math.round(hl) + " vs figure " + Math.round(hv));
  // content silently hidden inside a scroll box (e.g. a table column pushed out of view)
  for (const box of document.querySelectorAll(".table-scroll")) {
    if (box.scrollWidth > box.clientWidth + 1) h.push("hidden overflow in .table-scroll: " + box.scrollWidth + "px content in " + box.clientWidth + "px");
  }
  return JSON.stringify({ lines, bad, horizontal: h });
})()`;
let total = 0, horizontal = 0;
for (const route of routes) {
  await p.goto((process.env.LEDGER_URL ?? "http://localhost:8765") + route, 2600);
  const res = JSON.parse(await p.eval(CHECK));
  total += res.bad?.length ?? 0;
  horizontal += res.horizontal.length;
  console.log(`${route.padEnd(11)} ${res.lines} lines, ${res.bad.length} off-grid${res.horizontal.length ? ", HORIZONTAL: " + res.horizontal.join("; ") : ""}`);
  for (const b of res.bad.slice(0, 12)) console.log(`    ${b.strike ? "STRIKE " : "       "}${String(b.baselineInBand).padStart(5)}  ${b.el}  "${b.text}"`);
}
console.log(`off-grid text styles: ${total} · horizontal problems: ${horizontal}`);
p.close();
process.exit(total || horizontal ? 1 : 0);
