import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const langGraphApi = process.env.LANGGRAPH_API_URL ?? "http://127.0.0.1:8123";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5175,
    strictPort: true,
    proxy: {
      "/langgraph": {
        target: langGraphApi,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/langgraph/, ""),
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4175,
    strictPort: true,
  },
});
