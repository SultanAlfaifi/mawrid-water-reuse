import * as THREE from 'three';

// Created for MAWRID from mathematical surfaces. No photographs or texture assets.
// All texture strengths below are dimensionless; engineering dimensions live in unitSpec.
function seededRandom(seed) {
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

function normalTexture(kind, size = 256) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const random = seededRandom(81173);
  const field = new Float32Array(size * size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const u = x / size, v = y / size;
      let value;
      if (kind === 'frp') {
        // Opposing fine helical passes simulate filament-wound glass fibres.
        value = Math.sin((u * 24 + v * 18) * Math.PI * 2) * .28
          + Math.sin((u * 24 - v * 18) * Math.PI * 2) * .24
          + Math.sin(v * Math.PI * 128) * .12 + (random() - .5) * .12;
      } else if (kind === 'brush') {
        value = Math.sin(v * Math.PI * 176) * .25
          + Math.sin(v * Math.PI * 72) * .17 + (random() - .5) * .12;
      } else if (kind === 'stone') {
        value = Math.sin(u * Math.PI * 24) * Math.cos(v * Math.PI * 20) * .15
          + (random() - .5) * .65;
      } else {
        value = (random() - .5) * .6
          + Math.sin(u * Math.PI * 94) * Math.sin(v * Math.PI * 86) * .2;
      }
      field[y * size + x] = value;
    }
  }
  const output = ctx.createImageData(size, size);
  const sample = (x, y) => field[((y + size) % size) * size + ((x + size) % size)];
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const dx = sample(x + 1, y) - sample(x - 1, y);
    const dy = sample(x, y + 1) - sample(x, y - 1);
    const inv = 1 / Math.sqrt(dx * dx + dy * dy + 1);
    const i = (y * size + x) * 4;
    output.data[i] = Math.round((-dx * inv * .5 + .5) * 255);
    output.data[i + 1] = Math.round((-dy * inv * .5 + .5) * 255);
    output.data[i + 2] = Math.round((inv * .5 + .5) * 255);
    output.data[i + 3] = 255;
  }
  ctx.putImageData(output, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.anisotropy = 8;
  texture.colorSpace = THREE.NoColorSpace;
  texture.name = `MAWRID procedural ${kind} normal`;
  return texture;
}

export function createMaterials(spec) {
  const optical = spec.common.opticalThickness;
  const normals = {
    frp: normalTexture('frp'),
    paint: normalTexture('peel'),
    steel: normalTexture('brush'),
    stone: normalTexture('stone'),
  };
  const physical = (name, values) => new THREE.MeshPhysicalMaterial({
    name, color: 0xffffff, roughness: .45, metalness: 0,
    envMapIntensity: 1, ...values,
  });
  const glow = (name, color, intensity) => physical(name, {
    color, emissive: color, emissiveIntensity: intensity,
    roughness: .22, clearcoat: .7,
  });
  const materials = {
    frame: physical('Powder coated galvanized steel · dark green', {
      color: '#123e35', metalness: .32, roughness: .34, clearcoat: .5,
      clearcoatRoughness: .36, normalMap: normals.paint, normalScale: new THREE.Vector2(.075, .075),
    }),
    steel: physical('Brushed stainless steel', {
      color: '#cad1d3', metalness: .95, roughness: .26, anisotropy: .72,
      anisotropyRotation: Math.PI / 2, normalMap: normals.steel,
      normalScale: new THREE.Vector2(.045, .12),
    }),
    frpSand: physical('Light grey filament-wound FRP', {
      color: '#d3d6ce', roughness: .28, metalness: .035, clearcoat: .55,
      clearcoatRoughness: .24, normalMap: normals.frp, normalScale: new THREE.Vector2(.095, .095),
    }),
    frpCarbon: physical('Navy filament-wound FRP', {
      color: '#183e60', roughness: .29, metalness: .035, clearcoat: .5,
      clearcoatRoughness: .25, normalMap: normals.frp, normalScale: new THREE.Vector2(.09, .09),
    }),
    peWhite: physical('Rotomoulded polyethylene · ivory', {
      color: '#f0eee1', roughness: .48, transmission: .12, thickness: optical.peWhite,
      transparent: true, opacity: .89, ior: 1.5,
      normalMap: normals.paint, normalScale: new THREE.Vector2(.045, .045),
    }),
    peTreated: physical('Rotomoulded polyethylene · muted lilac', {
      color: '#beb5ca', roughness: .46, transmission: .06, thickness: optical.peTreated,
      transparent: true, opacity: .91, ior: 1.5,
      normalMap: normals.paint, normalScale: new THREE.Vector2(.045, .045),
    }),
    pp: physical('Translucent blue cartridge housing', {
      color: '#3181a8', roughness: .16, metalness: 0, transmission: .35,
      thickness: optical.pp, transparent: true, opacity: .5, ior: 1.49,
      clearcoat: .75, depthWrite: false,
    }),
    acrylic: physical('Transparent sample-cell acrylic', {
      color: '#e0f6fa', roughness: .1, transmission: .6,
      thickness: optical.acrylic, transparent: true, opacity: .32, ior: 1.49,
      clearcoat: 1, depthWrite: false,
    }),
    quartz: physical('UV lamp quartz sleeve', {
      color: '#e6edff', roughness: .04, transmission: .55,
      thickness: optical.quartz, transparent: true, opacity: .28, ior: 1.46, depthWrite: false,
    }),
    water: physical('Treated water', {
      color: '#4ba2b7', roughness: .08, transmission: .2,
      transparent: true, opacity: .62, ior: 1.333, depthWrite: false,
    }),
    rawWater: physical('Greywater balance level', {
      color: '#687d70', roughness: .18, transparent: true, opacity: .76,
      transmission: .05, ior: 1.333,
    }),
    pipe: physical('Light grey UPVC process pipe', { color: '#bbc0be', roughness: .32, clearcoat: .2 }),
    purple: physical('Reclaimed water purple UPVC', { color: '#79539c', roughness: .32, clearcoat: .2 }),
    drain: physical('Black drainage polyethylene', { color: '#252b2a', roughness: .44, clearcoat: .12 }),
    rubber: physical('Black EPDM rubber', { color: '#1e2424', roughness: .87 }),
    brass: physical('Unbranded brass fitting', { color: '#b29a61', metalness: .84, roughness: .31 }),
    red: physical('Red actuator and handwheel enamel', { color: '#b83d35', roughness: .34, clearcoat: .4 }),
    blue: physical('Blue valve handle enamel', { color: '#26698e', roughness: .34, clearcoat: .4 }),
    black: physical('Anthracite polymer', { color: '#252c2d', roughness: .5 }),
    white: physical('Warm white instrument enclosure', {
      color: '#e4e6df', roughness: .38, clearcoat: .25,
      normalMap: normals.paint, normalScale: new THREE.Vector2(.05, .05),
    }),
    concrete: physical('Pale warm limestone', {
      color: '#d6d2c5', roughness: .83, normalMap: normals.stone,
      normalScale: new THREE.Vector2(.09, .09),
    }),
    soil: physical('Exposed soil', {
      color: '#786752', roughness: .97, normalMap: normals.stone,
      normalScale: new THREE.Vector2(.23, .23),
    }),
    leaf: physical('Date palm and ornamental foliage', {
      color: '#52684a', roughness: .65, side: THREE.DoubleSide,
      sheen: .12, sheenColor: '#b1bb8b',
    }),
    uvGlow: glow('UV source only · selective bloom', '#8c89ff', 3.2),
    greenGlow: glow('Green status lamp only · selective bloom', '#46bd7d', 1.6),
    yellowGlow: glow('Amber status lamp only · selective bloom', '#ffc757', 1.25),
    redGlow: glow('Red status lamp only · selective bloom', '#ee6352', 1.5),
    offGlow: physical('De-energized lamp diffuser', { color: '#5b6465', roughness: .24, clearcoat: .7 }),
  };
  Object.defineProperty(materials, 'dispose', {
    enumerable: false,
    value: () => {
      Object.values(materials).forEach(material => material.dispose());
      Object.values(normals).forEach(texture => texture.dispose());
    },
  });
  return materials;
}
