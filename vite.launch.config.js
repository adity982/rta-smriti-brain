import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "launch-site",
  base: "./",
  plugins: [react()],
  build: {
    outDir: "../launch-dist",
    emptyOutDir: true,
  },
});
