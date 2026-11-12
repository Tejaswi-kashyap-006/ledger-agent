// tiny CDP helper: import { open } from "./cdp.mjs"; const p = await open(); await p.goto(url); await p.eval(js)
export async function open({ width = 1440, height = 1200, scheme = "light" } = {}) {
  const page = (await (await fetch("http://127.0.0.1:9333/json/list")).json()).find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d.result ?? d.error); pending.delete(d.id); } };
  await new Promise((r) => (ws.onopen = r));
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }, { name: "prefers-reduced-motion", value: "reduce" }] });
  return {
    send,
    goto: async (url, wait = 2200) => { await send("Page.navigate", { url }); await new Promise((r) => setTimeout(r, wait)); },
    eval: async (expression) => { const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description); return r.result.value; },
    close: () => ws.close(),
  };
}
