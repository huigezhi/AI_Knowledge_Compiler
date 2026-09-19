import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { defineConfig } from "vite";

const here = fileURLToPath(new URL(".", import.meta.url));

/**
 * Chrome MV3 构建（扩展页面 + service worker）。
 *
 * Content Script 单独构建（``vite.content.config.ts``）：MV3 的 content script
 * 需要 IIFE，而 service worker / 页面用 ESM，两者无法在同一次 rollup 输出里混用格式。
 */
export default defineConfig({
  root: resolve(here, "src"),
  publicDir: resolve(here, "public"),
  resolve: {
    alias: { "@": resolve(here, "src") },
  },
  build: {
    outDir: resolve(here, "dist"),
    emptyOutDir: true,
    target: "esnext",
    rollupOptions: {
      input: {
        background: resolve(here, "src/background/index.ts"),
        sidepanel: resolve(here, "src/sidepanel/index.html"),
        options: resolve(here, "src/options/index.html"),
      },
      output: {
        entryFileNames: "[name]/index.js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
