import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const isEmbed = process.env.BUILD_TARGET === "embed";
const isWeb = process.env.BUILD_TARGET === "web";

function manualChunks(id: string) {
  const normalizedId = id.replace(/\\/g, "/");

  if (!normalizedId.includes("/node_modules/")) {
    return undefined;
  }

  if (normalizedId.includes("/node_modules/plotly.js") || normalizedId.includes("/node_modules/react-plotly.js/")) {
    return "vendor-plotly";
  }

  if (normalizedId.includes("/node_modules/mermaid/") || normalizedId.includes("/node_modules/@mermaid-js/")) {
    return "vendor-mermaid";
  }

  if (
    normalizedId.includes("/node_modules/@codesandbox/")
    || normalizedId.includes("/node_modules/@stitches/")
  ) {
    return "vendor-sandpack";
  }

  if (normalizedId.includes("/node_modules/monaco-editor/")) {
    return "vendor-monaco";
  }

  const shikiThemeMatch = normalizedId.match(/\/node_modules\/@shikijs\/themes\/dist\/([^/]+)\.mjs$/);
  if (shikiThemeMatch) {
    return `vendor-syntax-theme-${shikiThemeMatch[1]}`;
  }

  const shikiLangMatch = normalizedId.match(/\/node_modules\/@shikijs\/langs\/dist\/([^/]+)\.mjs$/);
  if (shikiLangMatch) {
    return `vendor-syntax-lang-${shikiLangMatch[1]}`;
  }

  if (
    normalizedId.includes("/node_modules/react-shiki/")
    || normalizedId.includes("/node_modules/shiki/")
    || normalizedId.includes("/node_modules/@shikijs/core/")
    || normalizedId.includes("/node_modules/@shikijs/types/")
    || normalizedId.includes("/node_modules/@shikijs/engine-javascript/")
    || normalizedId.includes("/node_modules/@shikijs/vscode-textmate/")
    || normalizedId.includes("/node_modules/refractor/")
  ) {
    return "vendor-syntax-core";
  }

  if (normalizedId.includes("/node_modules/cytoscape/") || normalizedId.includes("/node_modules/cose-bilkent/")) {
    return "vendor-diagrams";
  }

  if (normalizedId.includes("/node_modules/katex/")) {
    return "vendor-katex";
  }

  if (normalizedId.includes("/node_modules/react/") || normalizedId.includes("/node_modules/react-dom/")) {
    return "vendor-react";
  }

  return undefined;
}

// https://tauri.app/start/frontend/vite/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Prevent vite from obscuring rust errors
  clearScreen: false,
  server: {
    port: isEmbed ? 1421 : 1420,
    strictPort: true,
    watch: {
      // Tell vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
  // Env variables starting with TAURI_ are accessible in the client code
  envPrefix: ["VITE_", "TAURI_"],
  // Sprint 220b: Embed assets must use /embed/ base path (served via FastAPI StaticFiles)
  base: isEmbed ? "/embed/" : undefined,
  build: {
    outDir: isEmbed ? "dist-embed" : isWeb ? "dist-web" : "dist",
    // Vite 8/Rolldown no longer supports lowering some modern syntax to Safari 13.
    // Tauri shells and the hosted web/embed targets run on modern engines, so keep
    // the production target at the shared ES2020 baseline unless Windows needs its
    // explicit WebView2 floor.
    target: isEmbed || isWeb
      ? "es2020"
      : process.env.TAURI_PLATFORM === "windows"
        ? "chrome105"
        : "es2020",
    // Embed/Web: always minify; Tauri: only in release
    minify: isEmbed || isWeb ? "esbuild" : !process.env.TAURI_DEBUG ? "esbuild" : false,
    // Embed/Web: no sourcemaps; Tauri: only in debug
    sourcemap: isEmbed || isWeb ? false : !!process.env.TAURI_DEBUG,
    rollupOptions: {
      input: isEmbed
        ? { embed: path.resolve(__dirname, "embed.html") }
        : undefined,
      // Tauri (default target): ONE bundle. Rolldown's automatic splitting
      // emitted circularly-initialized chunks (settings-store imported
      // zustand's `create` from the index chunk before it initialized →
      // "create is not a function" → white screen on every production
      // window; first seen the first time a release was built after the
      // Vite 8 bump). The desktop app loads from disk, so code splitting
      // buys nothing there. Embed/Web stay split for network delivery.
      output:
        isEmbed || isWeb
          ? { manualChunks }
          : { inlineDynamicImports: true },
      // Tauri-only plugins resolved at runtime (dynamic import with try/catch fallback)
      // Web + Embed: bundle everything (Tauri APIs fail gracefully via try/catch)
      external: isEmbed || isWeb ? [] : ["@fabianlars/tauri-plugin-oauth"],
    },
  },
});
