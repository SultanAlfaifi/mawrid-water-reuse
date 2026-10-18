import { defineConfig } from 'vite';
export default defineConfig({
  base: './',
  build: { rolldownOptions: { output: { codeSplitting: { groups: [{ name: 'three-engine', test: /node_modules\/three/ }] } } } },
});
