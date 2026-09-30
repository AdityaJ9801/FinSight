import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is proxied to Flask so the app works on one origin. In production the
// built bundle (dist/) is served by frontend_server.py, which proxies /api the same way.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.FINSIGHT_API ?? "http://127.0.0.1:5000", changeOrigin: true } },
  },
});
