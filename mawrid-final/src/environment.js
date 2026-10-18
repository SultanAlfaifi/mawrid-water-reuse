import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

// Architectural context is deliberately fictional. Every physical length is read
// from the resolved unitSpec; numeric constants below are ratios or mesh quality.
const Y = new THREE.Vector3(0, 1, 0);

function staticBatch(parent) {
  const entries = new Map();
  const matrix = new THREE.Matrix4();
  const quaternion = new THREE.Quaternion();
  function add(geometry, material, position = new THREE.Vector3(), rotation) {
    quaternion.identity();
    if (rotation instanceof THREE.Quaternion) quaternion.copy(rotation);
    else if (rotation) quaternion.setFromEuler(rotation);
    matrix.compose(position, quaternion, new THREE.Vector3(1, 1, 1));
    geometry.applyMatrix4(matrix);
    const list = entries.get(material) || [];
    list.push(geometry.index ? geometry.toNonIndexed() : geometry);
    if (geometry.index) geometry.dispose();
    entries.set(material, list);
  }
  const box = (w, h, d, x, y, z, material) => add(new THREE.BoxGeometry(w, h, d), material, new THREE.Vector3(x, y, z));
  const tube = (from, to, radius, material, segments = 10) => {
    const a = new THREE.Vector3(...from), b = new THREE.Vector3(...to);
    const delta = b.clone().sub(a);
    if (!delta.lengthSq()) return;
    const q = new THREE.Quaternion().setFromUnitVectors(Y, delta.clone().normalize());
    add(new THREE.CylinderGeometry(radius, radius, delta.length(), segments), material, a.add(b).multiplyScalar(.5), q);
  };
  return {
    add, box, tube,
    finish() {
      for (const [material, geometries] of entries) {
        const combined = mergeGeometries(geometries, false);
        const mesh = new THREE.Mesh(combined, material);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.name = `Site static batch · ${material.name}`;
        parent.add(mesh);
        geometries.forEach(geometry => geometry.dispose());
      }
    },
  };
}

function groundGeometry(width, depth, cut, elevation) {
  const shape = new THREE.Shape();
  shape.moveTo(-width / 2, -depth / 2);
  shape.lineTo(width / 2, -depth / 2);
  shape.lineTo(width / 2, depth / 2);
  shape.lineTo(-width / 2, depth / 2);
  shape.closePath();
  const hole = new THREE.Path();
  const left = cut.x - cut.width / 2, right = cut.x + cut.width / 2;
  const top = -cut.z + cut.depth / 2, bottom = -cut.z - cut.depth / 2;
  hole.moveTo(left, bottom);
  hole.lineTo(left, top);
  hole.lineTo(right, top);
  hole.lineTo(right, bottom);
  hole.closePath();
  shape.holes.push(hole);
  const geometry = new THREE.ShapeGeometry(shape);
  geometry.rotateX(-Math.PI / 2);
  geometry.translate(0, elevation, 0);
  return geometry;
}

function cycloramaGeometry(site) {
  const positions = [], uv = [], indices = [];
  const segments = 48;
  const profile = [];
  for (let i = 0; i <= segments; i++) {
    const angle = i / segments * Math.PI / 2;
    profile.push([
      site.cycloramaRadius * (1 - Math.cos(angle)),
      site.studioBackZ + site.cycloramaRadius * (1 - Math.sin(angle)),
    ]);
  }
  profile.push([site.cycloramaHeight, site.studioBackZ]);
  for (let i = 0; i < profile.length; i++) {
    const [height, z] = profile[i];
    positions.push(-site.studioLength / 2, height, z, site.studioLength / 2, height, z);
    uv.push(0, i / segments, 1, i / segments);
    if (i < profile.length - 1) {
      const a = i * 2;
      indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function paverTexture(site) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 512;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#c8c5ba';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const gap = site.paverJoint / site.paverSize * canvas.width;
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, '#dad7cb');
  gradient.addColorStop(1, '#d1cec2');
  ctx.fillStyle = gradient;
  ctx.fillRect(gap / 2, gap / 2, canvas.width - gap, canvas.height - gap);
  let seed = 917;
  for (let i = 0; i < 18000; i++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const x = seed % canvas.width;
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const y = seed % canvas.height;
    ctx.fillStyle = i % 2 ? 'rgba(70,64,50,.025)' : 'rgba(255,255,255,.045)';
    ctx.fillRect(x, y, 1, 1);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1 / site.paverSize, 1 / site.paverSize);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

function bladeGeometry(start, midpoint, end, width) {
  const direction = end.clone().sub(start).normalize();
  let side = direction.clone().cross(Y);
  if (side.lengthSq() < Number.EPSILON) side.set(1, 0, 0);
  side.normalize().multiplyScalar(width / 2);
  const left = midpoint.clone().add(side), right = midpoint.clone().sub(side);
  const positions = [...start, ...left, ...end, ...right];
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 0, .5, 1, 1, 1, .5], 2));
  geometry.setIndex([0, 1, 2, 0, 2, 3]);
  geometry.computeVertexNormals();
  return geometry;
}

function palm(batch, x, z, site, soilY, materials, trunkMaterial, phase) {
  const trunkBottom = new THREE.Vector3(x, soilY, z);
  const trunkTop = new THREE.Vector3(x + site.palmTrunkDiameter * phase, soilY + site.palmHeight, z);
  const quaternion = new THREE.Quaternion().setFromUnitVectors(Y, trunkTop.clone().sub(trunkBottom).normalize());
  batch.add(new THREE.CylinderGeometry(site.palmTrunkDiameter * .34, site.palmTrunkDiameter / 2, site.palmHeight, 16), trunkMaterial, trunkTop.clone().add(trunkBottom).multiplyScalar(.5), quaternion);
  const rings = Math.floor(site.palmHeight / site.palmTrunkRing);
  for (let i = 1; i < rings; i++) {
    const t = i / rings;
    const center = trunkBottom.clone().lerp(trunkTop, t);
    const radius = site.palmTrunkDiameter * (.5 - t * .16);
    const geometry = new THREE.TorusGeometry(radius, site.palmTrunkRing * .15, 4, 16);
    geometry.rotateX(Math.PI / 2);
    batch.add(geometry, trunkMaterial, center);
  }
  for (let f = 0; f < 13; f++) {
    const angle = f / 13 * Math.PI * 2 + phase;
    const heading = new THREE.Vector3(Math.cos(angle), 0, Math.sin(angle));
    const cross = new THREE.Vector3(-heading.z, 0, heading.x);
    const length = site.palmLeafLength * (.84 + .16 * Math.sin(f * 2.3 + phase));
    const points = [];
    for (let i = 0; i <= 12; i++) {
      const t = i / 12;
      const p = trunkTop.clone().addScaledVector(heading, length * t);
      p.y += site.palmCrownRadius * (Math.sin(t * Math.PI) * .35 - t * .18);
      points.push(p);
      if (i) batch.tube(points[i - 1].toArray(), p.toArray(), site.palmLeafWidth * .022, materials.leaf, 5);
      if (!i || i === 12) continue;
      const spread = length * .26 * Math.sin(t * Math.PI) * (1 - t * .35);
      for (const sign of [-1, 1]) {
        const tip = p.clone().addScaledVector(cross, spread * sign).addScaledVector(heading, length * .17);
        tip.y -= spread * .28;
        const mid = p.clone().lerp(tip, .47);
        mid.y += site.palmLeafWidth * .16;
        batch.add(bladeGeometry(p, mid, tip, site.palmLeafWidth * (.50 - t * .27)), materials.leaf);
      }
    }
  }
}

export function createEnvironment({ scene, materials, spec }) {
  const s = spec.site;
  const group = new THREE.Group();
  group.name = 'Architectural context · proposed';
  const studio = new THREE.Group();
  studio.name = 'Horizonless studio';
  const site = new THREE.Group();
  site.name = 'Fictional courtyard site';
  group.add(studio, site);
  scene.add(group);
  const ownedMaterials = [];
  const ownedTextures = [];
  const ownMaterial = material => { ownedMaterials.push(material); return material; };
  const balanceX = -spec.skid.length / 2 - spec.layout.tankSkidGap - spec.balance.diameter / 2;
  const chamberX = balanceX - spec.balance.diameter / 2 - spec.layout.chamberTankGap - spec.common.chamber.length / 2;
  const cut = {
    x: chamberX, z: 0,
    width: spec.common.chamber.length + s.cutawayMargin * 2,
    depth: spec.common.chamber.width + s.cutawayMargin * 2,
  };
  // A narrow forward section exposes the pump from the normal viewing side.
  // Its rear edge remains unchanged; the rest of the courtyard stays intact.
  const sectionBackZ = -cut.depth / 2;
  const sectionFrontZ = spec.common.chamber.depth * 1.4 + spec.common.chamber.width / 2;
  const sectionCut = {
    ...cut,
    z: (sectionFrontZ + sectionBackZ) / 2,
    depth: sectionFrontZ - sectionBackZ,
  };

  const studioMaterial = ownMaterial(new THREE.MeshPhysicalMaterial({ color: '#dde1de', roughness: .83, metalness: 0, side: THREE.DoubleSide }));
  const studioFloor = new THREE.Mesh(groundGeometry(s.studioLength, s.studioWidth, cut, spec.layout.groundY), studioMaterial);
  studioFloor.receiveShadow = true;
  studio.add(studioFloor);
  const studioSectionFloor = new THREE.Mesh(groundGeometry(s.studioLength, s.studioWidth, sectionCut, spec.layout.groundY), studioMaterial);
  studioSectionFloor.receiveShadow = true;
  studio.add(studioSectionFloor);
  const backdrop = new THREE.Mesh(cycloramaGeometry(s), studioMaterial);
  backdrop.receiveShadow = true;
  studio.add(backdrop);

  const tileMap = paverTexture(s);
  ownedTextures.push(tileMap);
  const tileMaterial = ownMaterial(materials.concrete.clone());
  tileMaterial.name = 'Procedural pale stone paving';
  tileMaterial.color.set('#ffffff');
  tileMaterial.map = tileMap;
  const siteFloor = new THREE.Mesh(groundGeometry(s.groundLength, s.groundWidth, cut, spec.layout.groundY), tileMaterial);
  siteFloor.receiveShadow = true;
  site.add(siteFloor);
  const siteSectionFloor = new THREE.Mesh(groundGeometry(s.groundLength, s.groundWidth, sectionCut, spec.layout.groundY), tileMaterial);
  siteSectionFloor.receiveShadow = true;
  site.add(siteSectionFloor);

  const siteBatch = staticBatch(site);
  const pitBottom = -spec.common.chamber.depth - s.slabThickness;
  function soilSection(opening) {
    const soil = new THREE.Group();
    group.add(soil);
    const batch = staticBatch(soil);
    // The front face is intentionally omitted from the section convention.
    batch.box(opening.width, s.slabThickness, opening.depth, opening.x, pitBottom - s.slabThickness / 2, opening.z, materials.soil);
    for (const sign of [-1, 1]) batch.box(s.slabThickness, -pitBottom, opening.depth, opening.x + sign * (opening.width + s.slabThickness) / 2, pitBottom / 2, opening.z, materials.soil);
    batch.box(opening.width, -pitBottom, s.slabThickness, opening.x, pitBottom / 2, opening.z - opening.depth / 2 - s.slabThickness / 2, materials.soil);
    batch.finish();
    return soil;
  }
  const normalSoil = soilSection(cut);
  const sectionSoil = soilSection(sectionCut);

  const wallMaterial = ownMaterial(materials.concrete.clone());
  wallMaterial.name = 'Matte warm courtyard plaster';
  wallMaterial.color.set('#e4ded0');
  siteBatch.box(s.wallLength, s.wallHeight, s.wallThickness, s.wallX, s.wallHeight / 2, s.wallZ, wallMaterial);
  siteBatch.box(s.wallLength, s.slabThickness * .5, s.wallThickness * 1.3, s.wallX, s.wallHeight + s.slabThickness * .25, s.wallZ, materials.concrete);
  const washLength = s.wallLength * .55;
  const washX = s.wallX - s.wallLength * .12;
  const troughZ = s.wallZ + s.wallThickness / 2 + s.washTroughWidth / 2;
  siteBatch.box(washLength, s.slabThickness * .5, s.washTroughWidth, washX, s.washTroughHeight - s.slabThickness * .25, troughZ, materials.concrete);
  siteBatch.box(washLength, s.washTroughHeight, s.planterWall, washX, s.washTroughHeight / 2, troughZ + s.washTroughWidth / 2, materials.concrete);
  for (const sign of [-1, 1]) siteBatch.box(s.planterWall, s.washTroughHeight, s.washTroughWidth, washX + sign * washLength / 2, s.washTroughHeight / 2, troughZ, materials.concrete);
  const tapCount = Math.floor(washLength / s.tapSpacing);
  for (let i = 0; i < tapCount; i++) {
    const x = washX + (i - (tapCount - 1) / 2) * s.tapSpacing;
    const wallFront = s.wallZ + s.wallThickness / 2;
    siteBatch.tube([x, s.tapHeight, wallFront], [x, s.tapHeight, wallFront + s.tapProjection], s.tapDiameter / 2, materials.steel, 12);
    siteBatch.tube([x, s.tapHeight, wallFront + s.tapProjection], [x, s.tapHeight - s.tapProjection * .4, wallFront + s.tapProjection], s.tapDiameter / 2, materials.steel, 12);
    siteBatch.tube([x, s.tapHeight, wallFront + s.tapProjection * .4], [x, s.tapHeight + s.tapDiameter * 1.4, wallFront + s.tapProjection * .4], s.tapDiameter * .38, materials.steel, 10);
    siteBatch.box(s.tapDiameter * 2.2, s.tapDiameter * .3, s.tapDiameter * .65, x, s.tapHeight + s.tapDiameter * 1.4, wallFront + s.tapProjection * .4, materials.steel);
    siteBatch.box(s.tapSpacing * .45, s.washBenchHeight, s.washBenchDepth, x, s.washBenchHeight / 2, troughZ + s.washTroughWidth + s.washBenchDepth, materials.concrete);
  }

  // The wash trough drains to the exact upstream boundary of the plant model.
  // The buried run falls continuously toward CH-101; it has no detached end.
  const sourceX = chamberX - spec.common.chamber.length / 2 - spec.layout.rawInletReach;
  const sourceY = spec.detail.chamber.inletHeight;
  const troughOutletY = s.washTroughHeight;
  const buriedUpstreamY = sourceY + Math.abs(troughZ) * spec.layout.drainSlope;
  const collectionPath = [
    [sourceX, troughOutletY, troughZ],
    [sourceX, buriedUpstreamY, troughZ],
    [sourceX, sourceY, 0],
  ];
  for (let i = 1; i < collectionPath.length; i++) siteBatch.tube(collectionPath[i - 1], collectionPath[i], spec.pipe.outerDiameter / 2, materials.pipe, 12);
  siteBatch.add(new THREE.CylinderGeometry(spec.pipe.outerDiameter, spec.pipe.outerDiameter, spec.detail.labels.plateThickness, 16), materials.steel, new THREE.Vector3(sourceX, troughOutletY + spec.detail.labels.surfaceGap, troughZ));
  for (let i = -2; i <= 2; i++) {
    siteBatch.box(spec.pipe.outerDiameter * 1.5, spec.detail.labels.plateThickness, spec.detail.chamber.basketWire / 2, sourceX, troughOutletY + spec.detail.labels.surfaceGap * 2, troughZ + i * spec.detail.chamber.basketWire, materials.black);
  }

  // A connected eight-point pattern, restrained enough to remain background context.
  const frame = s.screenBar * 2;
  const screenZ = s.wallZ;
  for (const sign of [-1, 1]) {
    siteBatch.box(frame, s.screenHeight, s.screenDepth, s.screenX + sign * s.screenWidth / 2, s.screenHeight / 2, screenZ, materials.frame);
    siteBatch.box(s.screenWidth, frame, s.screenDepth, s.screenX, sign < 0 ? frame / 2 : s.screenHeight - frame / 2, screenZ, materials.frame);
  }
  const columns = Math.max(1, Math.floor(s.screenWidth / s.screenOpening));
  const rows = Math.max(1, Math.floor(s.screenHeight / s.screenOpening));
  const cellWidth = s.screenWidth / columns, cellHeight = s.screenHeight / rows;
  for (let col = 0; col < columns; col++) for (let row = 0; row < rows; row++) {
    const cx = s.screenX - s.screenWidth / 2 + cellWidth * (col + .5);
    const cy = cellHeight * (row + .5);
    const vertices = [];
    for (let v = 0; v < 16; v++) {
      const a = v / 16 * Math.PI * 2;
      const ratio = v % 2 ? .30 : .5;
      vertices.push([cx + Math.cos(a) * cellWidth * ratio, cy + Math.sin(a) * cellHeight * ratio, screenZ]);
    }
    for (let v = 0; v < 16; v++) siteBatch.tube(vertices[v], vertices[(v + 1) % 16], s.screenBar * .27, materials.frame, 5);
  }

  const soilY = s.planterHeight - s.planterWall * .6;
  for (const sign of [-1, 1]) {
    siteBatch.box(s.planterLength, s.planterHeight, s.planterWall, s.planterX, s.planterHeight / 2, s.planterZ + sign * s.planterWidth / 2, materials.concrete);
    siteBatch.box(s.planterWall, s.planterHeight, s.planterWidth, s.planterX + sign * s.planterLength / 2, s.planterHeight / 2, s.planterZ, materials.concrete);
  }
  siteBatch.box(s.planterLength - s.planterWall, soilY, s.planterWidth - s.planterWall, s.planterX, soilY / 2, s.planterZ, materials.soil);
  const trunkMaterial = ownMaterial(materials.soil.clone());
  trunkMaterial.name = 'Date palm trunk';
  trunkMaterial.color.set('#83755c');
  palm(siteBatch, s.planterX - s.planterLength * .30, s.planterZ, s, soilY, materials, trunkMaterial, -.65);
  palm(siteBatch, s.planterX + s.planterLength * .28, s.planterZ, s, soilY, materials, trunkMaterial, .82);
  for (let plant = 0; plant < 15; plant++) {
    const x = s.planterX - s.planterLength * .45 + s.planterLength * .90 * plant / 14;
    const z = s.planterZ + Math.sin(plant * 2.1) * s.planterWidth * .22;
    for (let leaf = 0; leaf < 9; leaf++) {
      const angle = leaf / 9 * Math.PI * 2 + plant;
      const start = new THREE.Vector3(x, soilY, z);
      const end = new THREE.Vector3(x + Math.cos(angle) * s.shrubRadius, soilY + s.shrubHeight * (.5 + .5 * Math.sin(leaf * 1.7) ** 2), z + Math.sin(angle) * s.shrubRadius);
      const mid = start.clone().lerp(end, .52);
      mid.y += s.shrubHeight * .25;
      siteBatch.add(bladeGeometry(start, mid, end, s.palmLeafWidth * .35), materials.leaf);
    }
  }

  // Continue precisely from the plant's purple boundary nozzle into the planter.
  const treatedX = spec.skid.length / 2 + spec.layout.treatedSkidGap + spec.treated.length / 2;
  const endX = treatedX + spec.treated.length / 2 + spec.layout.irrigationEndpointOffset;
  const feedY = spec.layout.dripHeight;
  const plantFront = s.planterZ + s.planterWidth / 2;
  const irrigY = soilY + s.dripDiameter / 2;
  const irrigationPath = [
    [endX, feedY, spec.layout.irrigationEndZ],
    [endX, feedY, plantFront + s.planterWall],
    [endX, irrigY, plantFront + s.planterWall],
    [endX, irrigY, s.planterZ],
  ];
  for (let i = 1; i < irrigationPath.length; i++) siteBatch.tube(irrigationPath[i - 1], irrigationPath[i], spec.pipe.outerDiameter / 2, materials.purple, 12);
  const supportCount = Math.ceil(Math.abs(irrigationPath[1][2] - irrigationPath[0][2]) / spec.layout.pipeSupportInterval);
  const supportHeight = feedY - spec.pipe.outerDiameter / 2;
  for (let i = 0; i <= supportCount; i++) {
    const z = THREE.MathUtils.lerp(irrigationPath[0][2], irrigationPath[1][2], i / supportCount);
    siteBatch.box(spec.detail.fittings.supportBase, supportHeight, spec.detail.fittings.supportBase, endX, supportHeight / 2, z, materials.concrete);
  }
  const lateralStart = s.planterX - s.planterLength / 2 + s.planterWall;
  const lateralEnd = s.planterX + s.planterLength / 2 - s.planterWall;
  siteBatch.tube([lateralStart, irrigY, s.planterZ], [lateralEnd, irrigY, s.planterZ], s.dripDiameter / 2, materials.drain);
  for (const x of [lateralStart, lateralEnd]) siteBatch.add(new THREE.SphereGeometry(s.dripDiameter * .6, 8, 6), materials.drain, new THREE.Vector3(x, irrigY, s.planterZ));
  const emitters = Math.floor((lateralEnd - lateralStart) / s.dripSpacing);
  for (let i = 0; i <= emitters; i++) {
    const x = lateralStart + (lateralEnd - lateralStart) * i / emitters;
    const z = s.planterZ + (i % 2 ? 1 : -1) * s.planterWidth * .28;
    siteBatch.tube([x, irrigY, s.planterZ], [x, irrigY, z], s.dripDiameter * .24, materials.drain, 6);
    siteBatch.add(new THREE.CylinderGeometry(s.dripDiameter * .45, s.dripDiameter * .45, s.dripDiameter * .8, 8), materials.black, new THREE.Vector3(x, irrigY, z));
  }
  siteBatch.finish();

  let mode = 'studio';
  const setMode = next => {
    mode = next === 'site' ? 'site' : 'studio';
    studio.visible = mode === 'studio';
    site.visible = mode === 'site';
  };
  const setCutaway = active => {
    const enabled = !!active;
    studioFloor.visible = siteFloor.visible = normalSoil.visible = !enabled;
    studioSectionFloor.visible = siteSectionFloor.visible = sectionSoil.visible = enabled;
  };
  setMode(mode);
  setCutaway(false);
  return {
    group, studio, site, setMode, setCutaway,
    connections: {
      rawSource: [...collectionPath[collectionPath.length - 1]],
      irrigation: [...irrigationPath[0]],
    },
    dispose() {
      group.traverse(object => { if (object.geometry) object.geometry.dispose(); });
      ownedMaterials.forEach(material => material.dispose());
      ownedTextures.forEach(texture => texture.dispose());
      scene.remove(group);
    },
  };
}
