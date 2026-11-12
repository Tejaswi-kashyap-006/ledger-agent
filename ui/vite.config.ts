import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The production build is written INTO the Python package, so `ledger serve` serves UI + API on one port.
// In development, `npm run dev` proxies API calls to a running `ledger serve` (default :8000).
const API = process.env.LEDGER_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/ledger_agent/static",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: { "/v1": API, "/healthz": API },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    css: false,
  },
});
