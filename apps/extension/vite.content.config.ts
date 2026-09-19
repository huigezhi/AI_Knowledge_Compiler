import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { defineConfig } from "vite";

const here = fileURLToPath(new URL(".", import.meta.url));

/**
 * Content Script 构建：输出 IIFE，供 MV3 的 ``content_scripts`` 注入。
 * 与页面构建分离，因为同一份 rollup 输出无法混用 es / iife 格式。
 */
export default defineConfig({
  root: resolve(here, "src"),
  publicDir: false,
  resolve: {
    alias: { "@": resolve(here, "src") },
  },
  build: {
    outDir: resolve(here, "dist"),
    emptyOutDir: false,
    target: "esnext",
    rollupOptions: {
      input: { content: resolve(here, "src/content/index.ts") },
      output: {
        format: "iife",
        entryFileNames: "content.js",
        inlineDynamicImports: true,
      },
    },
  },
});
