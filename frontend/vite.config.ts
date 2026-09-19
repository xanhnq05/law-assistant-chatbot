import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Vite config — KHÔNG dùng proxy nữa.
 *
 * Từ khi tách thành 3 service riêng biệt (auth: 8001, chat: 8002, rag: 8003),
 * frontend gọi thẳng từng service qua URL trong .env.local. Vite proxy chỉ
 * gây cản trở khi restart và debug.
 *
 * Nếu muốn đi qua nginx gateway (Docker mode), chỉ cần đổi URL trong
 * .env.local → http://localhost:8080 (nginx sẽ route tiếp).
 */

export default defineConfig({
  plugins: [react()],
  base: "/",
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5173,
  },
});
