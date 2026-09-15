import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Doit refléter `paths` de tsconfig.json : TypeScript résout l'alias au
    // typecheck, Vite doit le résoudre au bundling.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Évite tout CORS en développement, y compris pour le flux SSE.
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
