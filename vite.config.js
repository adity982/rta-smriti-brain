import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "dashboard-src",
  plugins: [react()],
  build: {
    outDir: "../rta_brain/static",
    emptyOutDir: true,
  },
});
