import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  root: 'web',
  base: './',
  publicDir: false,
  build: {
    outDir: '../.site-build',
    emptyOutDir: true,
    assetsDir: 'assets/app',
    target: 'es2022',
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./web/index.html', import.meta.url)),
        simulator: fileURLToPath(new URL('./web/simulator/index.html', import.meta.url))
      },
      output: { manualChunks(id) { if (id.replaceAll('\\', '/').includes('node_modules/three/')) return 'three'; } }
    }
  },
  server: { port: 4173, strictPort: true }
});
