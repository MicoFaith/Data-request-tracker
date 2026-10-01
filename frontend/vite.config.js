import { defineConfig } from "vite";
export default defineConfig({
  base: "/static/react/",
  build: {
    outDir: "../static/react",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: "src/main.jsx",
      onwarn(warning, warn) {
        // React client directives are expected in this entirely client-side bundle.
        if (warning.code === "MODULE_LEVEL_DIRECTIVE") return;
        warn(warning);
      },
    },
  },
  test: { environment: "jsdom", setupFiles: "./src/test-setup.js" },
});
