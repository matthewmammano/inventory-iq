import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const FLASK_DEV_ORIGIN = "http://127.0.0.1:5055";

export default defineConfig({
  base: "/v2/",
  plugins: [react()],
  build: {
    outDir: "../app/static/v2",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": FLASK_DEV_ORIGIN,
    },
  },
});
