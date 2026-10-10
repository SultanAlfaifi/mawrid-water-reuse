import { defineConfig } from 'vite';

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
      output: { manualChunks(id) { if (id.replaceAll('\\', '/').includes('node_modules/three/')) return 'three'; } }
    }
  },
  server: { port: 4173, strictPort: true }
});
