import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend target for the dev proxy. In the production container nginx proxies /api and /health instead.
const BACKEND = process.env.AGENTSHIELD_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true, timeout: 120_000, proxyTimeout: 120_000 },
      "/health": { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
          charts: ["recharts"],
        },
      },
    },
  },
});
