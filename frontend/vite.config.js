import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes to ../web/dist, which FastAPI serves automatically when present.
// During `npm run dev`, /api calls are proxied to the running FastAPI server on :8000.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../web/dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
