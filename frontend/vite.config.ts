import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Relative base so the build loads correctly from file:// in Electron
  base: "./",
  server: {
    port: 4173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/components/UpdateChecker.tsx", "src/components/UpdateFallback.tsx", "src/lib/api.ts"],
    },
  },
});
