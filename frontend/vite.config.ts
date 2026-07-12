import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      // 本地 npm run dev 走宿主机 Backend；Docker 全栈可用 VITE_API_PROXY 覆盖
      "/api": process.env.VITE_API_PROXY || "http://127.0.0.1:8000",
      "/ws": {
        target: process.env.VITE_API_PROXY || "http://127.0.0.1:8000",
        ws: true,
      },
    },
  },
});