import { fileURLToPath } from 'node:url';
const local = path => fileURLToPath(new URL(path, import.meta.url));
export default {
  root: local('./'), base: './',
  resolve: { alias: [{ find: /^three$/, replacement: local('../../mawrid-final/node_modules/three/build/three.module.js') },
    { find: /^three\/addons\/(.*)/, replacement: local('../../mawrid-final/node_modules/three/examples/jsm/')+'$1' }] },
  build: { outDir: local('../client/plant3d/'), emptyOutDir: true,
    rolldownOptions: { output: { codeSplitting: { groups: [{ name:'three', test:/node_modules\/three/ }] } } } },
};
