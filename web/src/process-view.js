import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

// One visual concept, aligned with assets/images/campus-concept.png. The image
// and this geometry are proposed illustrations, not an approved engineering
// design. Model units, ports and camera fits do not establish real dimensions,
// hydraulics, treatment performance or water safety.
export async function createProcessView({ container, onSelect = () => {}, reducedMotion = false }) {
  if (!container) throw new TypeError('A container is required for the process view.');

  const palette = { mint: '#e9f3ef', forest: '#123e35', teal: '#39786a', copper: '#bd724d', sand: '#927253', water: '#65b8c2', reject: '#d18a52' };
  const compact = window.matchMedia('(max-width: 700px)').matches;
  const detail = compact ? 24 : 32;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  } catch (error) {
    throw new Error('The 3D process view could not initialize WebGL.', { cause: error });
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, compact ? 1.5 : 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.86;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  // Camera or route-indicator motion does not move any shadow caster. Refresh
  // the static shadow only when the unit's parts, selection or valves change.
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.domElement.className = 'process-canvas';
  renderer.domElement.setAttribute('aria-label', 'مجسم توضيحي لوحدة مورد: اسحب أفقيًا للدوران واختر مكوّنًا لاستكشافه.');
  renderer.domElement.setAttribute('role', 'img');
  renderer.domElement.style.width = '100%';
  renderer.domElement.style.height = '100%';
  renderer.domElement.style.display = 'block';
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 80);
  const defaultDirection = new THREE.Vector3(0.20, 0.20, 1).normalize();
  const targetHome = new THREE.Vector3(0, 1.6, 0);
  camera.position.copy(targetHome).addScaledVector(defaultDirection, 18);
  const controls = new OrbitControls(camera, renderer.domElement);
  // OrbitControls.connect() sets touchAction to none; restore vertical page
  // scrolling after construction. Horizontal touch drags still orbit the skid.
  renderer.domElement.style.touchAction = 'pan-y';
  controls.target.copy(targetHome);
  controls.enableDamping = !reducedMotion;
  controls.dampingFactor = 0.09;
  controls.enablePan = false;
  controls.minDistance = 9;
  controls.maxDistance = 26;
  controls.minPolarAngle = 0.3;
  controls.maxPolarAngle = Math.PI / 2 - 0.04;
  controls.rotateSpeed = 0.65;
  controls.zoomSpeed = 0.7;
  controls.update();

  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environment = pmrem.fromScene(room, 0.04);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.72;
  room.dispose();
  pmrem.dispose();

  scene.add(new THREE.HemisphereLight('#ffffff', '#8ba69a', 1.35));
  const key = new THREE.DirectionalLight('#fff9ec', 2.35);
  key.position.set(-4, 10, 7);
  key.castShadow = true;
  key.shadow.mapSize.set(compact ? 1024 : 2048, compact ? 1024 : 2048);
  Object.assign(key.shadow.camera, { left: -8, right: 8, top: 7, bottom: -7, near: 1, far: 25 });
  key.shadow.camera.updateProjectionMatrix();
  key.shadow.bias = -0.0003;
  key.shadow.normalBias = 0.025;
  key.shadow.radius = 2;
  scene.add(key);
  const fill = new THREE.DirectionalLight('#d9f2ec', 0.8);
  fill.position.set(7, 5, -6);
  scene.add(fill);

  const materials = {
    frame: new THREE.MeshStandardMaterial({ color: palette.forest, metalness: 0.55, roughness: 0.36 }),
    steel: new THREE.MeshStandardMaterial({ color: '#bbc6bf', metalness: 0.94, roughness: 0.23 }),
    brushed: new THREE.MeshStandardMaterial({ color: '#b6c3bc', metalness: 0.86, roughness: 0.44 }),
    pvc: new THREE.MeshStandardMaterial({ color: '#46544d', metalness: 0.08, roughness: 0.43 }),
    dark: new THREE.MeshStandardMaterial({ color: '#263d37', roughness: 0.76 }),
    rubber: new THREE.MeshStandardMaterial({ color: '#1d2825', roughness: 0.95 }),
    copper: new THREE.MeshStandardMaterial({ color: palette.copper, metalness: 0.74, roughness: 0.31 }),
    sand: new THREE.MeshStandardMaterial({ color: '#9f825c', roughness: 1 }),
    gravel: new THREE.MeshStandardMaterial({ color: '#626c60', roughness: 0.95 }),
    carbon: new THREE.MeshStandardMaterial({ color: '#272c29', roughness: 0.98 }),
    tank: new THREE.MeshPhysicalMaterial({ color: '#e4e3d6', roughness: 0.42, metalness: 0, clearcoat: 0.08, clearcoatRoughness: 0.65 }),
    filterCase: new THREE.MeshPhysicalMaterial({ color: '#bfc8bb', roughness: 0.33, metalness: 0.03, clearcoat: 0.15 }),
    carbonCase: new THREE.MeshStandardMaterial({ color: '#222a25', roughness: 0.73, metalness: 0.08 }),
    water: new THREE.MeshPhysicalMaterial({ color: palette.water, metalness: 0, roughness: 0.12, transparent: true, opacity: 0.52, transmission: 0.22, thickness: 0.35, depthWrite: false }),
    glass: new THREE.MeshPhysicalMaterial({ color: '#e4eee9', roughness: 0.12, metalness: 0, transparent: true, opacity: 0.36, transmission: 0.58, thickness: 0.065, ior: 1.48, side: THREE.DoubleSide, depthWrite: false }),
    panel: new THREE.MeshStandardMaterial({ color: '#e2e1d3', metalness: 0.18, roughness: 0.46 }),
    screen: new THREE.MeshStandardMaterial({ color: '#173e34', emissive: '#173e34', emissiveIntensity: 0.5, roughness: 0.55 }),
    orange: new THREE.MeshStandardMaterial({ color: palette.reject, roughness: 0.42 }),
    red: new THREE.MeshStandardMaterial({ color: '#9f3b2d', roughness: 0.46 }),
    yellow: new THREE.MeshStandardMaterial({ color: '#cda851', roughness: 0.52 }),
  };
  const geometryCache = new Map();
  const ownedTextures = [];
  const surfaceTexture = (seed, streaked = false) => {
    const size = 128;
    const data = new Uint8Array(size * size * 4);
    let row = 0;
    for (let y = 0; y < size; y += 1) {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      row = 145 + ((seed >>> 16) % 75);
      for (let x = 0; x < size; x += 1) {
        seed = (seed * 1664525 + 1013904223) >>> 0;
        const value = streaked ? row + ((seed >>> 16) % 9) : 90 + ((seed >>> 16) % 165);
        const index = (y * size + x) * 4;
        data[index] = data[index + 1] = data[index + 2] = value;
        data[index + 3] = 255;
      }
    }
    const texture = new THREE.DataTexture(data, size, size);
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(streaked ? 2 : 7, streaked ? 16 : 7);
    texture.needsUpdate = true;
    ownedTextures.push(texture);
    return texture;
  };
  const grainTexture = surfaceTexture(23);
  materials.sand.bumpMap = grainTexture; materials.sand.bumpScale = 0.027;
  materials.gravel.bumpMap = grainTexture; materials.gravel.bumpScale = 0.034;
  materials.carbon.bumpMap = grainTexture; materials.carbon.bumpScale = 0.046;
  materials.carbonCase.bumpMap = grainTexture; materials.carbonCase.bumpScale = 0.009;
  materials.steel.roughnessMap = surfaceTexture(71, true);
  const geo = (keyName, factory) => {
    if (!geometryCache.has(keyName)) geometryCache.set(keyName, factory());
    return geometryCache.get(keyName);
  };
  const mesh = (parent, geometry, material, position, rotation) => {
    const item = new THREE.Mesh(geometry, material);
    if (position) item.position.set(...position);
    if (rotation) item.rotation.set(...rotation);
    item.castShadow = !material.transparent;
    item.receiveShadow = !material.transparent;
    parent.add(item);
    return item;
  };
  const box = (parent, size, material, position, radius = 0.015) => mesh(parent, geo(`box:${size}:${radius}`, () => new RoundedBoxGeometry(...size, 2, radius)), material, position);
  const cylinder = (parent, radius, height, material, position, rotation) => mesh(parent, geo(`cylinder:${radius}:${height}`, () => new THREE.CylinderGeometry(radius, radius, height, detail)), material, position, rotation);
  const ring = (parent, radius, tube, material, position) => mesh(parent, geo(`ring:${radius}:${tube}`, () => new THREE.TorusGeometry(radius, tube, 8, detail)), material, position, [Math.PI / 2, 0, 0]);
  const sphere = geo('bolt', () => new THREE.SphereGeometry(0.037, 8, 6));
  const boltRing = (parent, radius, y, count = 8) => {
    for (let i = 0; i < count; i += 1) {
      const angle = (i / count) * Math.PI * 2;
      mesh(parent, sphere, materials.steel, [Math.sin(angle) * radius, y, Math.cos(angle) * radius]);
    }
  };

  const ground = mesh(scene, new THREE.PlaneGeometry(200, 200), new THREE.ShadowMaterial({ opacity: 0.28 }), [0, -0.06, 0], [-Math.PI / 2, 0, 0]);
  ground.receiveShadow = true;
  const skid = new THREE.Group();
  scene.add(skid);
  // Compact powder-coated skid and one rear rack, matching the visual concept.
  for (const z of [-1.05, 1.05]) {
    box(skid, [8.2, 0.18, 0.16], materials.frame, [0, 0.30, z]);
    for (const x of [-3.95, -1.8, 0.1, 1.9, 3.95]) {
      box(skid, [0.13, 0.22, 0.13], materials.frame, [x, 0.15, z]);
      cylinder(skid, 0.105, 0.07, materials.rubber, [x, 0.025, z]);
      box(skid, [0.21, 0.03, 0.21], materials.brushed, [x, 0.075, z]);
    }
  }
  for (const x of [-3.95, -1.8, 0.1, 1.9, 3.95]) box(skid, [0.13, 0.12, 2.10], materials.frame, [x, 0.31, 0]);
  box(skid, [8.06, 0.035, 2.04], materials.dark, [0, 0.42, 0]);
  for (const x of [-2.28, 3.95]) box(skid, [0.12, 2.86, 0.12], materials.frame, [x, 1.88, -0.86]);
  box(skid, [6.35, 0.13, 0.12], materials.frame, [0.84, 3.30, -0.86]);
  box(skid, [6.35, 0.08, 0.10], materials.frame, [0.84, 0.79, -0.86]);
  box(skid, [0.11, 2.30, 0.11], materials.frame, [2.14, 1.62, -0.86]);

  const positions = [[-3.10, 0, 0], [-1.45, 0, -0.04], [-0.10, 0, -0.04], [1.12, 0, -0.08], [2.99, 0, 0], [2.99, 0, 0.02]];
  const explodeOffsets = [[-0.28, 0, 0.05], [-0.15, 0.03, 0], [0, 0.06, 0.10], [0.16, 0.06, -0.03], [0.28, 0.15, -0.10], [0.30, 0, 0.10]];
  const focusSizes = [[1.95, 2.8, 2.05], [1.3, 3.35, 1.6], [1.2, 3.1, 1.5], [1.12, 2.9, 1.65], [2.0, 2.70, 1.65], [2.05, 2.12, 1.9]];
  const stages = positions.map((position, index) => {
    const group = new THREE.Group();
    group.position.set(...position);
    group.userData.stageIndex = index;
    scene.add(group);
    const accent = new THREE.MeshStandardMaterial({ color: palette.teal, emissive: palette.teal, emissiveIntensity: 0, metalness: 0.42, roughness: 0.3 });
    const selectionRing = ring(group, index === 0 || index === 5 ? 0.88 : 0.54, 0.019, accent, [0, 0.45, 0]);
    const focusCenter = new THREE.Vector3(index === 4 ? -0.37 : 0, index === 4 ? 1.98 : index === 5 ? 1.34 : 1.85, index === 4 ? -0.18 : 0);
    return { group, accent, selectionRing, base: new THREE.Vector3(...position), offset: new THREE.Vector3(...explodeOffsets[index]), anchor: focusCenter.clone(), focusBounds: new THREE.Box3().setFromCenterAndSize(focusCenter, new THREE.Vector3(...focusSizes[index])) };
  });
  const explodedParts = [];
  const cutawayContents = [];
  const cutawayFaces = [];
  const registerExplodedPart = (object, offset) => explodedParts.push({ object, base: object.position.clone(), offset: new THREE.Vector3(...offset) });

  const plaque = (parent, text, width, position) => {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 160;
    const context = canvas.getContext('2d');
    context.fillStyle = '#ecf2ee';
    context.fillRect(0, 0, 512, 160);
    context.fillStyle = palette.forest;
    context.font = '600 58px Arial, sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(text, 256, 85);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    ownedTextures.push(texture);
    const material = new THREE.MeshStandardMaterial({ map: texture, roughness: 0.7, metalness: 0.08 });
    return mesh(parent, new THREE.PlaneGeometry(width, width * 160 / 512), material, position);
  };
  const gauge = (parent, position, valueAngle = -0.55) => {
    const group = new THREE.Group();
    group.position.set(...position);
    parent.add(group);
    cylinder(group, 0.145, 0.055, materials.steel, [0, 0, 0], [Math.PI / 2, 0, 0]);
    mesh(group, geo('gauge-face', () => new THREE.CircleGeometry(0.125, 24)), new THREE.MeshStandardMaterial({ color: '#fafaf3', roughness: 0.7 }), [0, 0, 0.032]);
    const needle = box(group, [0.013, 0.1, 0.005], materials.dark, [0, 0.037, 0.037], 0.001);
    needle.rotation.z = valueAngle;
    for (let i = 0; i < 7; i += 1) {
      const angle = (i / 6) * Math.PI * 1.5 - Math.PI * 0.75;
      const mark = box(group, [0.009, 0.015, 0.003], materials.dark, [Math.sin(angle) * 0.105, Math.cos(angle) * 0.105, 0.036], 0.001);
      mark.rotation.z = -angle;
    }
    cylinder(group, 0.026, 0.17, materials.copper, [0, -0.18, 0]);
    return group;
  };
  const shell = (parent, radius, height, centerY, caseMaterial) => {
    const rear = mesh(parent, new THREE.CylinderGeometry(radius, radius, height, detail, 1, true, Math.PI / 3, Math.PI * 4 / 3), caseMaterial, [0, centerY, 0]);
    rear.material = caseMaterial.clone();
    rear.material.side = THREE.DoubleSide;
    const frontMaterial = caseMaterial.clone();
    frontMaterial.side = THREE.DoubleSide;
    const front = mesh(parent, new THREE.CylinderGeometry(radius, radius, height, Math.max(12, detail / 2), 1, true, -Math.PI / 3, Math.PI * 2 / 3), frontMaterial, [0, centerY, 0]);
    cutawayFaces.push(front);
    registerExplodedPart(front, [0, 0.04, 0.82]);
    const interior = new THREE.Group();
    interior.visible = false;
    parent.add(interior);
    cutawayContents.push(interior);
    return { rear, front, interior };
  };
  const granularLayer = (parent, radius, height, centerY, material, seed, count = 30) => {
    const layer = cylinder(parent, radius, height, material, [0, centerY, 0]);
    const grainGeometry = geo('grain', () => new THREE.IcosahedronGeometry(1, 0));
    const grains = new THREE.InstancedMesh(grainGeometry, material, compact ? Math.min(24, count) : count);
    const dummy = new THREE.Object3D();
    // Deterministic placements keep the explanatory object stable on every visit.
    const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    for (let i = 0; i < grains.count; i += 1) {
      const angle = random() * Math.PI * 2;
      const r = Math.sqrt(random()) * radius * 0.93;
      const size = material === materials.gravel ? 0.048 + random() * 0.04 : 0.018 + random() * 0.024;
      dummy.position.set(Math.sin(angle) * r, centerY + height / 2 + size * 0.2, Math.cos(angle) * r);
      dummy.rotation.set(random() * 2, random() * 2, random() * 2);
      dummy.scale.set(size, size * (0.6 + random() * 0.6), size);
      dummy.updateMatrix();
      grains.setMatrixAt(i, dummy.matrix);
    }
    grains.castShadow = true;
    grains.receiveShadow = true;
    parent.add(grains);
    return layer;
  };
  const filterColumn = (stage, carbon = false) => {
    const parent = stage.group;
    const radius = carbon ? 0.415 : 0.47;
    const height = carbon ? 2.20 : 2.46;
    const centerY = carbon ? 1.77 : 1.89;
    const bottomY = centerY - height / 2;
    const topY = centerY + height / 2;
    const { interior } = shell(parent, radius, height, centerY, carbon ? materials.carbonCase : materials.filterCase);
    const top = cylinder(parent, radius + 0.07, 0.15, materials.frame, [0, topY, 0]);
    cylinder(parent, radius + 0.07, 0.13, materials.frame, [0, bottomY, 0]);
    ring(parent, radius + 0.02, 0.025, materials.rubber, [0, topY - 0.055, 0]);
    ring(parent, radius + 0.02, 0.022, stage.accent, [0, bottomY + 0.05, 0]);
    boltRing(parent, radius + 0.015, topY + 0.08, 10);
    boltRing(parent, radius + 0.015, bottomY - 0.07, 8);
    registerExplodedPart(top, [0, 0.44, 0]);
    for (const x of [-0.32, 0.32]) box(parent, [0.07, 0.20, 0.08], materials.frame, [x, 0.53, 0]);
    box(parent, [1.0, 0.06, 0.76], materials.frame, [0, 0.44, 0]);
    for (const y of [1.18, 2.43]) {
      ring(parent, radius + 0.019, 0.018, materials.brushed, [0, y, 0]);
      box(parent, [0.17, 0.11, 0.45], materials.brushed, [0, y, -0.62]);
    }
    for (const x of [-0.39, 0.39]) {
      cylinder(parent, 0.022, height + 0.19, materials.brushed, [x, centerY, -0.20]);
      cylinder(parent, 0.04, 0.06, materials.steel, [x, topY + 0.105, -0.20]);
    }
    granularLayer(interior, radius - 0.035, carbon ? 0.15 : 0.44, bottomY + (carbon ? 0.12 : 0.25), materials.gravel, carbon ? 49 : 41, carbon ? 24 : 65);
    granularLayer(interior, radius - 0.035, carbon ? 1.73 : 1.35, carbon ? bottomY + 1.01 : bottomY + 1.16, carbon ? materials.carbon : materials.sand, carbon ? 74 : 63, carbon ? 70 : 65);
    cylinder(interior, radius - 0.05, 0.27, materials.water, [0, topY - 0.22, 0]);
    cylinder(interior, radius - 0.03, 0.022, materials.brushed, [0, bottomY + 0.04, 0]);
    cylinder(parent, 0.09, 0.19, materials.pvc, [0, topY + 0.16, 0]);
    cylinder(parent, 0.09, 0.11, materials.pvc, [0, bottomY - 0.11, 0.13]);
    gauge(parent, [radius - 0.045, topY - 0.08, 0.20], carbon ? -0.25 : -0.45);
    stage.ports = { inlet: [0, topY + 0.255, 0], outlet: [0, bottomY - 0.165, 0.13] };
  };

  // 01: A short moulded source tank. The feed pump is mounted on the lower
  // central rail, as in the campus visual, while still belonging to this stage.
  const source = stages[0].group;
  const sourceShell = shell(source, 0.82, 1.65, 1.32, materials.tank);
  cylinder(source, 0.825, 0.07, materials.tank, [0, 0.50, 0]);
  mesh(source, new THREE.CylinderGeometry(0.64, 0.82, 0.22, detail), materials.tank, [0, 2.255, 0]);
  for (const y of [0.84, 1.24, 1.72, 2.07]) ring(source, 0.818, 0.026, materials.tank, [0, y, 0]);
  const sourceLid = cylinder(source, 0.65, 0.10, materials.frame, [0, 2.405, 0]);
  registerExplodedPart(sourceLid, [0, 0.30, 0]);
  cylinder(source, 0.14, 0.16, materials.pvc, [0, 2.53, 0]);
  ring(source, 0.65, 0.026, stages[0].accent, [0, 2.445, 0]);
  cylinder(sourceShell.interior, 0.755, 1.0, materials.water, [0, 1.04, 0]);
  cylinder(source, 0.085, 0.22, materials.pvc, [0.76, 0.67, 0.18], [0, 0, Math.PI / 2]);
  const feedPump = new THREE.Group();
  feedPump.position.set(3.8, 0, 0.22);
  source.add(feedPump);
  box(feedPump, [1.10, 0.07, 0.67], materials.frame, [0, 0.46, 0.55]);
  cylinder(feedPump, 0.245, 0.66, materials.steel, [0, 0.72, 0.55], [0, 0, Math.PI / 2]);
  cylinder(feedPump, 0.275, 0.14, stages[0].accent, [-0.40, 0.72, 0.55], [0, 0, Math.PI / 2]);
  cylinder(feedPump, 0.26, 0.13, materials.frame, [0.40, 0.72, 0.55], [0, 0, Math.PI / 2]);
  for (let i = 0; i < 5; i += 1) cylinder(feedPump, 0.253, 0.018, materials.brushed, [-0.26 + i * 0.11, 0.72, 0.55], [0, 0, Math.PI / 2]);
  for (const x of [-0.36, 0.34]) box(feedPump, [0.13, 0.12, 0.41], materials.frame, [x, 0.55, 0.55]);
  box(feedPump, [0.25, 0.10, 0.24], materials.dark, [-0.18, 1.0, 0.55]);
  cylinder(feedPump, 0.087, 0.17, materials.pvc, [-0.55, 0.72, 0.55], [0, 0, Math.PI / 2]);
  cylinder(feedPump, 0.087, 0.17, materials.pvc, [0.55, 0.72, 0.55], [0, 0, Math.PI / 2]);
  const pumpInlet = [3.165, 0.72, 0.77];
  const pumpOutlet = [4.435, 0.72, 0.77];
  filterColumn(stages[1]);
  filterColumn(stages[2], true);

  // 04: An independent stainless contact chamber. Its inner baffles and water
  // are explanatory cutaways; the vessel silhouette does not specify a method.
  const disinfection = stages[3].group;
  const contactShell = shell(disinfection, 0.355, 1.87, 1.82, materials.steel);
  cylinder(disinfection, 0.395, 0.11, materials.brushed, [0, 0.885, 0]);
  const contactLid = cylinder(disinfection, 0.395, 0.11, materials.brushed, [0, 2.755, 0]);
  registerExplodedPart(contactLid, [0, 0.40, 0]);
  boltRing(disinfection, 0.35, 2.82, 8);
  for (const y of [0.99, 2.65]) ring(disinfection, 0.368, 0.023, materials.brushed, [0, y, 0]);
  ring(disinfection, 0.371, 0.015, stages[3].accent, [0, 2.68, 0]);
  cylinder(contactShell.interior, 0.30, 1.64, materials.water, [0, 1.80, 0]);
  for (const y of [1.12, 1.50, 1.88, 2.26]) cylinder(contactShell.interior, 0.26, 0.03, materials.pvc, [0, y, 0]);
  for (const x of [-0.24, 0.24]) box(disinfection, [0.06, 0.38, 0.08], materials.brushed, [x, 0.65, 0]);
  gauge(disinfection, [0.12, 2.97, 0.17], -0.35);
  cylinder(disinfection, 0.077, 0.16, materials.pvc, [-0.385, 1.02, 0], [0, 0, Math.PI / 2]);
  cylinder(disinfection, 0.077, 0.16, materials.pvc, [0.385, 2.59, 0], [0, 0, Math.PI / 2]);

  // 05: The off-white electrical enclosure sits over the rectangular storage
  // tank. Gauges and probes remain on the separate downstream manifold.
  const instrumentation = stages[4].group;
  box(instrumentation, [1.09, 1.12, 0.34], materials.panel, [0, 2.67, -0.64], 0.035);
  box(instrumentation, [1.02, 1.05, 0.04], materials.panel, [0, 2.67, -0.448], 0.019);
  box(instrumentation, [0.45, 0.35, 0.028], materials.dark, [0, 2.85, -0.415], 0.008);
  box(instrumentation, [0.37, 0.25, 0.012], materials.screen, [0, 2.85, -0.394], 0.006);
  const screenBars = [];
  for (let i = 0; i < 3; i += 1) screenBars.push(box(instrumentation, [0.22 + i * 0.025, 0.013, 0.006], new THREE.MeshStandardMaterial({ color: '#a1c7b4', emissive: '#568f75', emissiveIntensity: 0.18 }), [-0.025, 2.915 - i * 0.055, -0.384], 0.002));
  for (const x of [-0.22, 0.22]) cylinder(instrumentation, 0.043, 0.04, materials.dark, [x, 2.51, -0.407], [Math.PI / 2, 0, 0]);
  cylinder(instrumentation, 0.089, 0.035, materials.yellow, [0, 2.29, -0.406], [Math.PI / 2, 0, 0]);
  cylinder(instrumentation, 0.061, 0.068, materials.red, [0, 2.29, -0.376], [Math.PI / 2, 0, 0]);
  for (const x of [-0.455, 0.455]) for (const y of [2.21, 3.125]) mesh(instrumentation, sphere, materials.steel, [x, y, -0.416]);
  plaque(instrumentation, 'MAWRID', 0.43, [0, 3.11, -0.414]);
  box(instrumentation, [0.09, 2.24, 0.09], materials.frame, [0.47, 1.54, -0.81]);
  cylinder(instrumentation, 0.108, 0.40, materials.glass, [-1.04, 1.04, 0.52]);
  for (const y of [0.815, 1.265]) cylinder(instrumentation, 0.134, 0.055, materials.brushed, [-1.04, y, 0.52]);
  cylinder(instrumentation, 0.043, 0.08, materials.copper, [-1.04, 1.08, 0.52]);
  gauge(instrumentation, [-0.78, 1.55, 0.50], -0.6);
  cylinder(instrumentation, 0.065, 0.17, materials.pvc, [-0.65, 0.88, 0.52]);
  cylinder(instrumentation, 0.04, 0.21, materials.steel, [-0.65, 1.03, 0.52]);
  box(instrumentation, [0.12, 0.11, 0.11], stages[4].accent, [-0.65, 1.16, 0.52]);
  const signalCurve = new THREE.CatmullRomCurve3([new THREE.Vector3(-0.65, 1.22, 0.52), new THREE.Vector3(-0.64, 1.55, 0.52), new THREE.Vector3(-0.52, 1.83, -0.62), new THREE.Vector3(-0.26, 2.11, -0.64)], false, 'centripetal');
  mesh(instrumentation, new THREE.TubeGeometry(signalCurve, 24, 0.017, 6, false), materials.rubber);
  for (const x of [-0.25, -0.05, 0.15]) cylinder(instrumentation, 0.032, 0.10, materials.dark, [x, 2.065, -0.65]);

  // 06: A moulded rectangular outlet tank retained by the forest frame.
  // HOLD is an explanatory outlet branch, not a miniature unverified vessel.
  const outlet = stages[5].group;
  const tankCenterY = 1.25;
  const wall = 0.055;
  box(outlet, [1.49, 1.43, wall], materials.tank, [0, tankCenterY, -0.595], 0.025);
  for (const x of [-0.727, 0.727]) box(outlet, [wall, 1.43, 1.20], materials.tank, [x, tankCenterY, 0], 0.025);
  for (const y of [0.535, 1.965]) box(outlet, [1.49, wall, 1.20], materials.tank, [0, y, 0], 0.025);
  const tankFront = box(outlet, [1.44, 1.37, 0.072], materials.tank.clone(), [0, tankCenterY, 0.607], 0.034);
  cutawayFaces.push(tankFront);
  registerExplodedPart(tankFront, [0, 0, 0.76]);
  const tankInterior = new THREE.Group();
  tankInterior.visible = false;
  outlet.add(tankInterior);
  cutawayContents.push(tankInterior);
  box(tankInterior, [1.31, 0.76, 1.03], materials.water, [0, 0.97, 0], 0.025);
  for (const y of [0.96, 1.55]) box(outlet, [1.44, 0.035, 0.025], materials.tank, [0, y, 0.655], 0.01);
  for (const x of [-0.80, 0.80]) box(outlet, [0.09, 1.68, 0.10], materials.frame, [x, 1.27, 0.69]);
  box(outlet, [1.68, 0.085, 0.10], materials.frame, [0, 1.38, 0.69]);
  box(outlet, [1.66, 0.07, 1.42], materials.frame, [0, 0.45, 0]);
  cylinder(outlet, 0.26, 0.11, materials.dark, [0.15, 2.045, 0]);
  const outletLid = cylinder(outlet, 0.265, 0.055, materials.pvc, [0.15, 2.13, 0]);
  registerExplodedPart(outletLid, [0, 0.30, 0]);
  cylinder(outlet, 0.083, 0.18, materials.pvc, [-0.80, 1.78, 0.10], [0, 0, Math.PI / 2]);
  const valve = (parent, position, material) => {
    const group = new THREE.Group();
    group.position.set(...position);
    parent.add(group);
    cylinder(group, 0.10, 0.24, materials.pvc, [0, 0, 0], [0, 0, Math.PI / 2]);
    cylinder(group, 0.034, 0.13, materials.steel, [0, 0.12, 0]);
    const handle = box(group, [0.28, 0.035, 0.063], material, [0.08, 0.20, 0], 0.009);
    return { group, handle };
  };
  const reuseValve = valve(outlet, [-0.98, 1.78, 0.10], stages[5].accent);
  const rejectValve = valve(outlet, [-1.10, 0.78, 0.92], materials.orange);
  plaque(outlet, 'HOLD', 0.38, [-0.98, 0.66, 1.155]);
  // Stored water still has an independent release boundary in this diagram.
  const deliveryValve = valve(outlet, [0.57, 0.67, 0.80], stages[5].accent);
  const deliveryTube = new THREE.CatmullRomCurve3([new THREE.Vector3(0.46, 0.67, 0.61), new THREE.Vector3(0.57, 0.67, 0.80), new THREE.Vector3(1.18, 0.67, 0.80)], false, 'centripetal');
  mesh(outlet, new THREE.TubeGeometry(deliveryTube, 18, 0.057, 8, false), materials.pvc);

  const at = (stage, x, y, z) => new THREE.Vector3(x, y, z).add(stages[stage].group.position);
  const port = (stage, name) => at(stage, ...stages[stage].ports[name]);
  const roundedRoute = (points, cornerRadius = 0.13) => {
    const curve = new THREE.CurvePath();
    let start = points[0].clone();
    for (let i = 1; i < points.length - 1; i += 1) {
      const corner = points[i];
      const incoming = corner.clone().sub(points[i - 1]);
      const outgoing = points[i + 1].clone().sub(corner);
      const distance = Math.min(cornerRadius, incoming.length() * 0.25, outgoing.length() * 0.25);
      const before = corner.clone().addScaledVector(incoming.normalize(), -distance);
      const after = corner.clone().addScaledVector(outgoing.normalize(), distance);
      if (start.distanceToSquared(before) > 0.000001) curve.add(new THREE.LineCurve3(start, before));
      curve.add(new THREE.QuadraticBezierCurve3(before, corner.clone(), after));
      start = after;
    }
    if (start.distanceToSquared(points.at(-1)) > 0.000001) curve.add(new THREE.LineCurve3(start, points.at(-1).clone()));
    return curve;
  };
  const pipes = [];
  const pipeSegments = compact ? 28 : 40;
  const pipeRadialSegments = 8;
  const tubePoint = new THREE.Vector3();
  const tubeNormal = new THREE.Vector3();
  const fittingDirection = new THREE.Vector3();
  const fittingUp = new THREE.Vector3(0, 1, 0);
  const tubeCircle = Array.from({ length: pipeRadialSegments + 1 }, (_, index) => {
    const angle = index / pipeRadialSegments * Math.PI * 2;
    return { sin: Math.sin(angle), cos: -Math.cos(angle) };
  });
  // Same Frenet-frame construction as Three's TubeGeometry, with stable index,
  // UV and GPU buffers. Opening the unit changes vertices, not its topology.
  const updatePipeGeometry = (geometry, curve, radius) => {
    const frames = curve.computeFrenetFrames(pipeSegments, false);
    const positions = geometry.attributes.position;
    const normals = geometry.attributes.normal;
    let vertex = 0;
    for (let segment = 0; segment <= pipeSegments; segment += 1) {
      curve.getPointAt(segment / pipeSegments, tubePoint);
      const normal = frames.normals[segment];
      const binormal = frames.binormals[segment];
      for (const circle of tubeCircle) {
        tubeNormal.copy(normal).multiplyScalar(circle.cos).addScaledVector(binormal, circle.sin).normalize();
        normals.setXYZ(vertex, tubeNormal.x, tubeNormal.y, tubeNormal.z);
        positions.setXYZ(vertex, tubePoint.x + radius * tubeNormal.x, tubePoint.y + radius * tubeNormal.y, tubePoint.z + radius * tubeNormal.z);
        vertex += 1;
      }
    }
    geometry.parameters.path = curve;
    geometry.tangents = frames.tangents;
    geometry.normals = frames.normals;
    geometry.binormals = frames.binormals;
    positions.needsUpdate = true;
    normals.needsUpdate = true;
    geometry.boundingBox = null;
    geometry.computeBoundingSphere();
  };
  const pipeGroup = new THREE.Group();
  scene.add(pipeGroup);
  const makePipe = (stageIndex, points, radius = 0.073, material = materials.pvc) => {
    const item = mesh(pipeGroup, new THREE.BufferGeometry(), material);
    item.userData.stageIndex = stageIndex;
    const fittings = [0, 1].map(() => {
      const fitting = cylinder(pipeGroup, radius * 1.33, 0.12, materials.pvc);
      fitting.userData.stageIndex = stageIndex;
      return fitting;
    });
    const definition = { item, points, radius, curve: null, fittings };
    pipes.push(definition);
    return definition;
  };
  // Every interstage line terminates at a real port; positions are recomputed for
  // the exploded view rather than leaving a decorative, disconnected pipeline.
  makePipe(0, () => [at(0, 0.87, 0.67, 0.18), at(0, 0.87, 0.67, 0.77), at(0, ...pumpInlet)]);
  makePipe(1, () => [at(0, ...pumpOutlet), at(0, 4.60, 0.72, 0.77), at(0, 4.60, 0.72, -0.60), at(1, -0.63, 0.72, -0.60), at(1, -0.63, 3.44, -0.60), at(1, 0, 3.44, -0.60), port(1, 'inlet')]);
  makePipe(2, () => [port(1, 'outlet'), at(1, 0.68, 0.51, 0.13), at(1, 0.68, 3.22, -0.55), at(2, 0, 3.22, -0.55), port(2, 'inlet')]);
  makePipe(3, () => [port(2, 'outlet'), at(2, 0.60, 0.54, 0.13), at(3, -0.465, 0.54, 0.13), at(3, -0.465, 1.02, 0)]);
  makePipe(4, () => [at(3, 0.465, 2.59, 0), at(3, 0.59, 2.59, 0.52), at(4, -1.32, 2.59, 0.52), at(4, -1.32, 0.815, 0.52), at(4, -1.04, 0.815, 0.52), at(4, -1.04, 1.30, 0.52), at(4, -0.74, 1.30, 0.52), at(4, -0.74, 0.815, 0.52), at(4, -0.60, 0.815, 0.52)]);
  const reusePipe = makePipe(5, () => [at(4, -0.60, 0.815, 0.52), at(5, -1.10, 0.815, 0.52), at(5, -1.10, 1.78, 0.10), at(5, -0.98, 1.78, 0.10), at(5, -0.89, 1.78, 0.10)]);
  const rejectPipe = makePipe(5, () => [at(4, -0.60, 0.815, 0.52), at(5, -1.10, 0.815, 0.52), at(5, -1.10, 0.78, 0.92), at(5, -0.88, 0.78, 0.92), at(5, -0.88, 0.50, 1.16)], 0.057);
  const updatePipes = () => {
    for (const pipe of pipes) {
      const points = pipe.points();
      pipe.curve = roundedRoute(points);
      if (pipe.item.geometry.type !== 'TubeGeometry') {
        pipe.item.geometry.dispose();
        pipe.item.geometry = new THREE.TubeGeometry(pipe.curve, pipeSegments, pipe.radius, pipeRadialSegments, false);
        pipe.item.geometry.attributes.position.setUsage(THREE.DynamicDrawUsage);
        pipe.item.geometry.attributes.normal.setUsage(THREE.DynamicDrawUsage);
      } else updatePipeGeometry(pipe.item.geometry, pipe.curve, pipe.radius);
      pipe.fittings.forEach((fitting, index) => {
        const endpoint = index === 0 ? points[0] : points.at(-1);
        fittingDirection.copy(index === 0 ? points[1] : endpoint).sub(index === 0 ? endpoint : points.at(-2));
        fitting.position.copy(endpoint);
        fitting.quaternion.setFromUnitVectors(fittingUp, fittingDirection.normalize());
      });
    }
  };

  // The sparse beads are a diagram overlay, visible through opaque PVC and
  // media. They indicate a route rather than simulating water hydraulics.
  const particlesMaterial = new THREE.MeshStandardMaterial({ color: '#a2bfc0', roughness: 0.6, transparent: true, opacity: 0.46, depthTest: false, depthWrite: false });
  const droplets = new THREE.InstancedMesh(new THREE.SphereGeometry(0.033, 7, 5), particlesMaterial, compact ? 8 : 12);
  droplets.frustumCulled = false;
  droplets.renderOrder = 20;
  scene.add(droplets);
  let waterCurve;
  let assembledBounds;
  let activeStage = 0;
  let focusedStage = null;
  let cameraFlight = null;
  let mode = 'normal';
  let flow = true;
  let explodedTarget = 0;
  let explodedAmount = 0;
  let disposed = false;
  let contextLost = false;
  let inView = true;
  let raf = 0;
  let inFrame = false;
  let lastTime = 0;
  let elapsed = 0;
  let renderUntil = 0;
  let suspendedAt = null;
  let renderWidth = 0;
  let renderHeight = 0;
  let renderPixelRatio = renderer.getPixelRatio();
  const dropletTransform = new THREE.Object3D();
  const updateWaterCurve = () => {
    const downstream = mode === 'normal' ? reusePipe : rejectPipe;
    const points = [at(0, 0, 1.58, 0), at(0, 0, 0.67, 0), ...pipes[0].points(), ...pipes[1].points(), at(1, 0, 2.8, 0), at(1, 0, 0.77, 0), ...pipes[2].points(), at(2, 0, 2.6, 0), at(2, 0, 0.79, 0), ...pipes[3].points(), at(3, -0.16, 1.1, 0), at(3, 0.16, 1.50, 0), at(3, -0.16, 1.88, 0), at(3, 0.16, 2.30, 0), ...pipes[4].points(), ...downstream.points()];
    if (mode === 'normal') points.push(at(5, 0, 1.78, 0.10), at(5, 0, 1.12, 0.10));
    const clean = points.filter((point, index) => index === 0 || point.distanceToSquared(points[index - 1]) > 0.00001);
    waterCurve = roundedRoute(clean, 0.09);
  };
  const updateParticles = () => {
    droplets.visible = flow && mode !== 'power';
    if (!droplets.visible) return;
    for (let i = 0; i < droplets.count; i += 1) {
      const progress = ((i / droplets.count) + (reducedMotion ? 0 : elapsed * 0.042)) % 1;
      waterCurve.getPointAt(progress, dropletTransform.position);
      dropletTransform.scale.setScalar(i % 3 === 0 ? 1.3 : 1);
      dropletTransform.updateMatrix();
      droplets.setMatrixAt(i, dropletTransform.matrix);
    }
    droplets.instanceMatrix.needsUpdate = true;
  };
  const updateExplosion = () => {
    for (const stage of stages) stage.group.position.copy(stage.base).addScaledVector(stage.offset, explodedAmount);
    for (const part of explodedParts) part.object.position.copy(part.base).addScaledVector(part.offset, explodedAmount);
    for (const contents of cutawayContents) contents.visible = explodedAmount > 0.045;
    for (const face of cutawayFaces) {
      const opacity = 1 - THREE.MathUtils.smoothstep(explodedAmount, 0.05, 0.68);
      face.visible = opacity > 0.015;
      const transparent = opacity < 0.999;
      if (face.material.transparent !== transparent) {
        face.material.transparent = transparent;
        face.material.needsUpdate = true;
      }
      face.material.opacity = opacity;
      face.material.depthWrite = opacity > 0.8;
    }
    updatePipes();
    updateWaterCurve();
    renderer.shadowMap.needsUpdate = true;
  };
  const applyMode = () => {
    const fault = mode !== 'normal';
    particlesMaterial.color.set(fault ? palette.reject : '#a2bfc0');
    reuseValve.handle.rotation.y = fault ? Math.PI / 2 : 0;
    deliveryValve.handle.rotation.y = fault ? Math.PI / 2 : 0;
    rejectValve.handle.rotation.y = fault ? 0 : Math.PI / 2;
    rejectPipe.item.material = fault ? materials.orange : materials.pvc;
    for (const bar of screenBars) {
      bar.material.color.set(mode === 'power' ? '#39574d' : fault ? '#e8b07c' : '#a1dbcb');
      bar.material.emissiveIntensity = mode === 'power' ? 0 : 0.18;
    }
    materials.screen.emissiveIntensity = mode === 'power' ? 0 : 0.18;
    updateWaterCurve();
    renderer.shadowMap.needsUpdate = true;
  };

  const requestFrame = (milliseconds = reducedMotion ? 50 : 950) => {
    if (disposed || contextLost) return;
    renderUntil = Math.max(renderUntil, performance.now() + milliseconds);
    if (!raf && !inFrame && inView && !document.hidden) raf = requestAnimationFrame(frame);
  };
  function frame(time) {
    raf = 0;
    if (disposed || contextLost || !inView || document.hidden) { lastTime = 0; return; }
    inFrame = true;
    const dt = lastTime ? Math.min((time - lastTime) / 1000, 0.04) : 0;
    lastTime = time;
    if (flow && !reducedMotion && mode !== 'power') elapsed += dt;
    if (Math.abs(explodedAmount - explodedTarget) > 0.001) {
      explodedAmount = reducedMotion ? explodedTarget : THREE.MathUtils.damp(explodedAmount, explodedTarget, 7, dt || 0.016);
      if (Math.abs(explodedAmount - explodedTarget) < 0.002) explodedAmount = explodedTarget;
      updateExplosion();
      if (explodedAmount === explodedTarget) fitCamera(false);
    }
    if (cameraFlight) {
      const progress = Math.min(1, (time - cameraFlight.started) / cameraFlight.duration);
      const eased = progress * progress * (3 - 2 * progress);
      controls.target.lerpVectors(cameraFlight.fromTarget, cameraFlight.target, eased);
      camera.position.lerpVectors(cameraFlight.fromPosition, cameraFlight.position, eased);
      if (progress === 1) cameraFlight = null;
    }
    controls.update();
    updateParticles();
    renderer.render(scene, camera);
    inFrame = false;
    if (cameraFlight || (flow && !reducedMotion && mode !== 'power') || Math.abs(explodedAmount - explodedTarget) > 0.001 || time < renderUntil) raf = requestAnimationFrame(frame);
    else lastTime = 0;
  }

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const activePointers = new Set();
  let pointerDown = null;
  const onPointerDown = (event) => {
    activePointers.add(event.pointerId);
    pointerDown = activePointers.size === 1 && event.button === 0 ? { x: event.clientX, y: event.clientY, id: event.pointerId, moved: false, intent: null } : null;
  };
  const onPointerMove = (event) => {
    if (!pointerDown || event.pointerId !== pointerDown.id) return;
    const x = Math.abs(event.clientX - pointerDown.x);
    const y = Math.abs(event.clientY - pointerDown.y);
    if (Math.hypot(x, y) > 6) pointerDown.moved = true;
    if (event.pointerType !== 'touch') return;
    if (!pointerDown.intent && Math.max(x, y) > 6) {
      if (x > y * 1.1) pointerDown.intent = 'orbit';
      else if (y > x * 1.1) pointerDown.intent = 'scroll';
    }
    // Let native pan-y scrolling claim a vertical gesture without first nudging
    // the camera. A deliberate horizontal drag still reaches OrbitControls.
    if (pointerDown.intent !== 'orbit') event.stopPropagation();
  };
  const onPointerUp = (event) => {
    activePointers.delete(event.pointerId);
    if (!pointerDown || event.pointerId !== pointerDown.id) return;
    const distance = Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y);
    const moved = pointerDown.moved;
    pointerDown = null;
    if (moved || distance > 6 || disposed || contextLost) return;
    const rect = renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const intersections = raycaster.intersectObjects([...stages.map((stage) => stage.group), pipeGroup], true);
    for (const intersection of intersections) {
      let ancestor = intersection.object;
      let visible = true;
      while (ancestor) { if (!ancestor.visible) { visible = false; break; } ancestor = ancestor.parent; }
      if (!visible) continue;
      let object = intersection.object;
      while (object && object.userData.stageIndex === undefined) object = object.parent;
      if (object && Number.isInteger(object.userData.stageIndex)) {
        api.setStage(object.userData.stageIndex);
        onSelect(object.userData.stageIndex);
        break;
      }
    }
  };
  const cancelPointer = (event) => { activePointers.delete(event.pointerId); pointerDown = null; };
  renderer.domElement.addEventListener('pointerdown', onPointerDown);
  renderer.domElement.addEventListener('pointermove', onPointerMove, { capture: true, passive: true });
  renderer.domElement.addEventListener('pointerup', onPointerUp);
  renderer.domElement.addEventListener('pointercancel', cancelPointer);
  const onControlsChange = () => requestFrame();
  // The first user gesture owns the camera immediately, even during a focus
  // flight. OrbitControls emits start before applying pointer/wheel movement.
  const onControlsStart = () => { cameraFlight = null; };
  controls.addEventListener('change', onControlsChange);
  controls.addEventListener('start', onControlsStart);
  const syncVisibility = () => {
    const now = performance.now();
    if (!inView || document.hidden) {
      if (suspendedAt === null) suspendedAt = now;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      lastTime = 0;
    } else {
      if (suspendedAt !== null && cameraFlight) cameraFlight.started += now - Math.max(suspendedAt, cameraFlight.started);
      suspendedAt = null;
      requestFrame();
    }
  };
  document.addEventListener('visibilitychange', syncVisibility);
  const onContextLost = (event) => {
    event.preventDefault();
    contextLost = true;
    api.is3D = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    container.dispatchEvent(new CustomEvent('processviewerror', { detail: { reason: 'webgl-context-lost' } }));
  };
  renderer.domElement.addEventListener('webglcontextlost', onContextLost);

  const resize = () => {
    if (disposed || contextLost) return;
    const rect = container.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    const pixelRatio = Math.min(window.devicePixelRatio || 1, window.matchMedia('(max-width: 700px)').matches ? 1.5 : 2);
    const sizeChanged = width !== renderWidth || height !== renderHeight;
    const ratioChanged = pixelRatio !== renderPixelRatio;
    if (!sizeChanged && !ratioChanged) return;
    renderWidth = width;
    renderHeight = height;
    renderPixelRatio = pixelRatio;
    if (ratioChanged) renderer.setPixelRatio(pixelRatio);
    renderer.setSize(width, height, false);
    if (!sizeChanged) { requestFrame(); return; }
    camera.aspect = width / height;
    camera.fov = width < 600 ? 42 : 35;
    camera.updateProjectionMatrix();
    cameraFlight = null;
    fitCamera(false);
    requestFrame();
  };

  function cameraGoal(resetDirection = false) {
    const detailStage = focusedStage === null ? null : stages[focusedStage];
    const bounds = detailStage ? detailStage.focusBounds.clone().translate(detailStage.group.position) : assembledBounds.clone();
    // Use the actual closed envelope and the compact opening clearance, rather
    // than the invisible removed front faces. Stage focus fits only its housing
    // so the pump attached to the source does not shrink a source close-up.
    if (explodedTarget || explodedAmount > 0.002) {
      bounds.min.add(new THREE.Vector3(detailStage ? -0.12 : -0.3, 0, -0.14));
      bounds.max.add(new THREE.Vector3(detailStage ? 0.12 : 0.32, 0.46, detailStage ? 0.25 : 0.16));
    }
    const center = bounds.getCenter(new THREE.Vector3());
    const direction = resetDirection ? defaultDirection.clone() : camera.position.clone().sub(controls.target).normalize();
    const right = new THREE.Vector3().crossVectors(direction, camera.up).normalize();
    const up = new THREE.Vector3().crossVectors(right, direction).normalize();
    const tangentVertical = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
    const tangentHorizontal = tangentVertical * camera.aspect;
    let distance = detailStage ? 2.3 : 1;
    // For each bounding corner, perspective depth plus its projected half-size
    // must fit inside tan(FOV / 2). Separate horizontal/vertical limits keep
    // the device near 85% canvas width without cropping on narrow viewports.
    for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
      const relative = new THREE.Vector3(x, y, z).sub(center);
      const depth = relative.dot(direction);
      distance = Math.max(distance,
        depth + Math.abs(relative.dot(right)) / (tangentHorizontal * 0.85),
        depth + Math.abs(relative.dot(up)) / (tangentVertical * 0.83));
    }
    return { target: center, position: center.clone().addScaledVector(direction, distance), distance };
  }
  function fitCamera(resetDirection = false) {
    if (!assembledBounds || disposed || contextLost) return;
    const goal = cameraGoal(resetDirection);
    controls.minDistance = Math.max(1.7, Math.min(9, goal.distance * 0.48));
    controls.maxDistance = Math.max(26, goal.distance * 2);
    controls.target.copy(goal.target);
    camera.position.copy(goal.position);
    controls.update();
  }
  const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
  resizeObserver?.observe(container);
  // Also refresh DPR when the window is zoomed or moved between displays. The
  // size guard keeps mobile browser-bar and duplicate observer events harmless.
  window.addEventListener('resize', resize, { passive: true });
  const intersectionObserver = typeof IntersectionObserver !== 'undefined' ? new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting;
    syncVisibility();
  }, { rootMargin: '100px' }) : null;
  intersectionObserver?.observe(container);

  const api = {
    is3D: true,
    setStage(index) {
      if (disposed || !Number.isInteger(index) || index < 0 || index > 5) return;
      activeStage = index;
      stages.forEach((stage, i) => {
        stage.accent.emissiveIntensity = i === activeStage ? 0.30 : 0;
        stage.selectionRing.visible = i === activeStage;
      });
      renderer.shadowMap.needsUpdate = true;
      requestFrame();
    },
    setExploded(value) {
      if (disposed) return;
      cameraFlight = null;
      explodedTarget = value ? 1 : 0;
      if (reducedMotion) { explodedAmount = explodedTarget; updateExplosion(); }
      fitCamera(false);
      requestFrame(1200);
    },
    setFlow(value) {
      if (disposed) return;
      flow = Boolean(value);
      requestFrame();
    },
    // The preference can change while this view remains mounted. The parent
    // forwards that change; no remount or stale initialization flag is needed.
    setReducedMotion(value) {
      if (disposed) return;
      const next = Boolean(value);
      if (next === reducedMotion) return;
      reducedMotion = next;
      controls.enableDamping = false;
      controls.update();
      controls.enableDamping = !reducedMotion;
      if (reducedMotion) {
        if (Math.abs(explodedAmount - explodedTarget) > 0.001) {
          explodedAmount = explodedTarget;
          updateExplosion();
          fitCamera(false);
        }
        if (cameraFlight) {
          const goal = cameraGoal(false);
          controls.target.copy(goal.target);
          camera.position.copy(goal.position);
          cameraFlight = null;
          controls.update();
        }
        renderUntil = performance.now();
      }
      requestFrame(reducedMotion ? 50 : 950);
    },
    setMode(value) {
      if (disposed) return;
      if (!['normal', 'sensor', 'disinfection', 'power', 'storage'].includes(value)) throw new RangeError('Unknown illustrative process mode.');
      mode = value;
      applyMode();
      requestFrame();
    },
    resetCamera() {
      if (disposed) return;
      focusedStage = null;
      cameraFlight = null;
      fitCamera(true);
      requestFrame();
    },
    // Selection and camera are independent: setStage keeps the hero overview;
    // focusStage is an explicit detail action. It preserves the current orbit
    // direction, takes 650 ms, and is instantaneous with reduced motion.
    focusStage(index) {
      if (disposed || contextLost || !Number.isInteger(index) || index < 0 || index > 5) return;
      cameraFlight = null;
      controls.enableDamping = false;
      controls.update();
      controls.enableDamping = !reducedMotion;
      focusedStage = index;
      const goal = cameraGoal(false);
      controls.minDistance = Math.max(1.7, Math.min(9, goal.distance * 0.48));
      controls.maxDistance = Math.max(26, goal.distance * 2);
      if (reducedMotion) {
        controls.target.copy(goal.target);
        camera.position.copy(goal.position);
        controls.update();
      } else {
        cameraFlight = { fromTarget: controls.target.clone(), fromPosition: camera.position.clone(), target: goal.target, position: goal.position, started: performance.now(), duration: 650 };
      }
      requestFrame(750);
    },
    getProjection(index) {
      if (disposed || !Number.isInteger(index) || index < 0 || index > 5) return null;
      const rect = container.getBoundingClientRect();
      const point = stages[index].anchor.clone().add(stages[index].group.position).project(camera);
      return { x: (point.x * 0.5 + 0.5) * rect.width, y: (-point.y * 0.5 + 0.5) * rect.height, visible: point.z > -1 && point.z < 1 && Math.abs(point.x) < 1 && Math.abs(point.y) < 1 };
    },
    resize,
    dispose() {
      if (disposed) return;
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', syncVisibility);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointermove', onPointerMove, true);
      renderer.domElement.removeEventListener('pointerup', onPointerUp);
      renderer.domElement.removeEventListener('pointercancel', cancelPointer);
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost);
      controls.removeEventListener('change', onControlsChange);
      controls.removeEventListener('start', onControlsStart);
      controls.dispose();
      const geometries = new Set();
      const disposableMaterials = new Set();
      scene.traverse((object) => {
        if (object.geometry) geometries.add(object.geometry);
        if (object.material) for (const material of Array.isArray(object.material) ? object.material : [object.material]) disposableMaterials.add(material);
      });
      for (const geometry of geometries) geometry.dispose();
      for (const material of disposableMaterials) material.dispose();
      for (const texture of ownedTextures) texture.dispose();
      key.shadow.dispose();
      environment.dispose();
      scene.environment = null;
      renderer.renderLists.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      api.is3D = false;
    },
  };

  updatePipes();
  updateWaterCurve();
  scene.updateMatrixWorld(true);
  assembledBounds = new THREE.Box3().setFromObject(skid);
  for (const stage of stages) assembledBounds.union(new THREE.Box3().setFromObject(stage.group));
  assembledBounds.union(new THREE.Box3().setFromObject(pipeGroup));
  api.setStage(0);
  applyMode();
  resize();
  requestFrame();
  return api;
}
