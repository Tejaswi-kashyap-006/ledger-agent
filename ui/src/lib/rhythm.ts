// Vertical rhythm keeper. The sheet is ruled every 28px, and text must sit on those rules.
// Text lines are 28px tall by CSS, but some blocks have heights no stylesheet can predict (cards,
// receipts, charts, tables that grow as data arrives). After layout, every direct child of a flow
// container gets a bottom margin that rounds the space it occupies up to a whole number of lines,
// so the next block starts on the grid again. ResizeObserver keeps it right as content changes.
import { useLayoutEffect, type RefObject } from "react";

export const LINE = 28;

// KEEP IN SYNC with the flow-container rule in styles/layout.css.
export const FLOW_CONTAINERS = [
  ".sheet__main", ".marginalia", ".marginalia > section", ".section", ".chart", ".letters", ".letter",
  ".letter__a", ".write-cta", ".all-clear", ".next-step", ".editorial", ".post-form", ".struck",
];
const CHILDREN = FLOW_CONTAINERS.map((c) => `${c} > *`).join(", ");

/** Extra bottom margin that rounds `occupied` px up to a whole number of lines (0 if already whole). */
export function snapExtra(occupied: number, line = LINE): number {
  if (occupied <= 0) return 0;
  const lines = Math.ceil(occupied / line - 0.02);   // tolerate sub-pixel noise (e.g. 56.3px -> 2 lines)
  return Math.max(0, Math.round((lines * line - occupied) * 100) / 100);
}

function snap(el: HTMLElement): void {
  const cs = getComputedStyle(el);
  if (cs.display === "none" || cs.position === "absolute" || cs.position === "fixed") return;
  const occupied = el.getBoundingClientRect().height + (parseFloat(cs.marginTop) || 0);
  const extra = snapExtra(occupied);
  const next = extra > 0.01 ? `${extra}px` : "";
  if (el.style.marginBottom !== next) el.style.marginBottom = next;
}

export function snapWithin(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>(CHILDREN).forEach(snap);
}

/** Keep every flow child under `root` on the 28px grid for as long as the component is mounted. */
export function useRhythm(root: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const el = root.current;
    if (!el || typeof ResizeObserver === "undefined") return;   // jsdom / very old browsers: no-op
    let frame = 0;
    const run = () => { frame = 0; snapWithin(el); };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(run); };
    const ro = new ResizeObserver(schedule);
    const observeAll = () => el.querySelectorAll<HTMLElement>(CHILDREN).forEach((c) => ro.observe(c));
    const mo = new MutationObserver(() => { observeAll(); schedule(); });
    observeAll();
    run();
    mo.observe(el, { childList: true, subtree: true });
    void document.fonts?.ready.then(schedule);                  // web fonts change line metrics once they load
    return () => { ro.disconnect(); mo.disconnect(); cancelAnimationFrame(frame); };
  }, [root]);
}
