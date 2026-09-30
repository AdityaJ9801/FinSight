import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api is forwarded to the Flask backend so the app runs on one origin:
// `npm run dev` (5173, hot reload) and `npm run preview` (8080, the production build).
// In Docker, nginx does the same forwarding (nginx.conf.template).
const api = { "/api": { target: process.env.FINSIGHT_API ?? "http://127.0.0.1:5000", changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: api },
  preview: { port: 8080, proxy: api },
});
