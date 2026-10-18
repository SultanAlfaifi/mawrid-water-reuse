import * as THREE from 'three';
import {createVirtualScene} from '../../../mawrid-system/plant3d/scene.js';
import {BrowserPlant, sceneSnapshot} from '../../../experience/src/model.js';

// The film uses the application's real virtual geometry and rule snapshot.
// Lighting, finish and directional markers are presentation; no treatment,
// measured water quality or physical operation is introduced here.
export function createCinemaPlant() {
  const model = createVirtualScene();
  const root = model.root;
  root.name = 'MAWRID cinematic presentation of the software simulation';
  const plant = new BrowserPlant();
  const normal = plant.snapshot();
  plant.control({fault: 'sensor_dropout'});
  const fault = plant.snapshot();
  const normalScene = sceneSnapshot(normal);
  const faultScene = sceneSnapshot(fault);
  const materialCache = new Map();
  const lamps = [];

  const finish = {
    '#dfdfd3': {color:'#d6d8c6', roughness:.7, metalness:.06},
    '#f1f0e5': {color:'#f1eee0', roughness:.28, metalness:.08, clearcoat:.65, clearcoatRoughness:.24},
    '#83938a': {color:'#93aaa1', roughness:.27, metalness:.88, clearcoat:.3},
    '#285e49': {color:'#194e3d', roughness:.3, metalness:.35, clearcoat:.65, clearcoatRoughness:.22},
    '#243f36': {color:'#0b2720', roughness:.38, metalness:.42},
    '#79938b': {color:'#72978c', roughness:.24, metalness:.8},
    '#845ba0': {color:'#739e90', roughness:.23, metalness:.76},
    '#ae8152': {color:'#80633f', roughness:.42, metalness:.6},
    '#7485a1': {color:'#506f70', roughness:.36, metalness:.72},
    '#435950': {color:'#173b32', roughness:.36, metalness:.2, clearcoat:.5},
    '#d4ddc6': {color:'#d7dfca', roughness:.26, metalness:.09, clearcoat:.8, clearcoatRoughness:.23},
    '#cbd1c5': {color:'#aaa991', roughness:.72, metalness:.08},
    '#589c92': {color:'#32b5a5', roughness:.14, metalness:.18, opacity:.85, transmission:.12, clearcoat:1},
    '#9dba98': {color:'#559b7c', roughness:.22, metalness:.1, opacity:.82, transmission:.08, clearcoat:.7},
    '#d7e3d9': {color:'#c1e0d3', roughness:.13, metalness:.02, opacity:.14, transmission:.3, clearcoat:1, clearcoatRoughness:.11},
  };

  // A tiny seeded, linear roughness texture gives stainless steel a restrained
  // brushed finish; it is generated locally rather than sourced photography.
  const texSize = 128;
  const texData = new Uint8Array(texSize * texSize * 4);
  let seed = 75419;
  for (let y = 0; y < texSize; y++) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const stripe = 165 + Math.round((seed / 4294967296 - .5) * 26);
    for (let x = 0; x < texSize; x++) {
      const i = (y * texSize + x) * 4;
      const value = stripe + Math.round(Math.sin(x * .19) * 3);
      texData[i] = texData[i+1] = texData[i+2] = value;
      texData[i+3] = 255;
    }
  }
  const brushed = new THREE.DataTexture(texData, texSize, texSize, THREE.RGBAFormat);
  brushed.wrapS = brushed.wrapT = THREE.RepeatWrapping;
  brushed.repeat.set(2, 10);
  brushed.needsUpdate = true;

  function cinemaMaterial(source) {
    if (materialCache.has(source)) return materialCache.get(source);
    const key = '#' + source.color.getHexString();
    const preset = finish[key] || {};
    const material = new THREE.MeshPhysicalMaterial({
      color:source.color, roughness:source.roughness ?? .4,
      metalness:source.metalness ?? .1, transparent:source.transparent,
      opacity:source.opacity, depthWrite:source.depthWrite,
      side:source.side, emissive:source.emissive ?? '#000000',
      emissiveIntensity:source.emissiveIntensity ?? 0,
      envMapIntensity:1.1, ...preset,
    });
    material.name = 'Cinema finish / ' + key;
    if (material.metalness > .6) material.roughnessMap = brushed;
    if (source.emissiveIntensity === .25) lamps.push(material);
    materialCache.set(source, material);
    return material;
  }
  root.traverse(object => {
    if (!object.isMesh) return;
    object.material = Array.isArray(object.material)
      ? object.material.map(cinemaMaterial) : cinemaMaterial(object.material);
    object.castShadow = !object.material.transparent;
    object.receiveShadow = true;
  });

  const stage = new THREE.Group();
  stage.name = 'Exhibition plinth / presentation geometry only';
  root.add(stage);
  const plinthMaterial = new THREE.MeshPhysicalMaterial({
    color:'#0b201a', roughness:.32, metalness:.55, clearcoat:.45,
  });
  const plinth = new THREE.Mesh(new THREE.BoxGeometry(18.8,.18,7.4), plinthMaterial);
  plinth.position.set(.5,-2.02,0);
  plinth.castShadow = plinth.receiveShadow = true;
  stage.add(plinth);
  const trimMaterial = new THREE.MeshStandardMaterial({
    color:'#9bb49a', metalness:.7, roughness:.3, emissive:'#244a36', emissiveIntensity:.3,
  });
  for (const z of [-3.68,3.68]) {
    const trim = new THREE.Mesh(new THREE.BoxGeometry(18.65,.012,.015), trimMaterial);
    trim.position.set(.5,-1.924,z); stage.add(trim);
  }

  const routes = [];
  const markerGroup = new THREE.Group();
  markerGroup.name = 'Directional markers on original flow curves';
  root.add(markerGroup);
  const beadGeometry = new THREE.SphereGeometry(.074,12,10);
  const matrixDummy = new THREE.Object3D();
  for (const pipe of model.pipes) {
    if (!pipe.key || ['backwash','overflow'].includes(pipe.key)) continue;
    const material = new THREE.MeshBasicMaterial({
      color:'#8fe5d3', transparent:true, opacity:.3, depthWrite:false,
      blending:THREE.AdditiveBlending, toneMapped:false,
    });
    const ribbon = new THREE.Mesh(new THREE.TubeGeometry(
      pipe.curve, Math.max(16,pipe.curve.curves.length*18), .055, 10, false,
    ), material);
    ribbon.name = 'Original route / ' + pipe.name;
    ribbon.renderOrder = 2; markerGroup.add(ribbon);
    const beadMaterial = new THREE.MeshBasicMaterial({
      color:'#ccfff2', transparent:true, opacity:.9, depthWrite:false,
      toneMapped:false,
    });
    const count = Math.max(2, Math.ceil(pipe.curve.getLength()/.55));
    const beads = new THREE.InstancedMesh(beadGeometry, beadMaterial, count);
    beads.frustumCulled = false; beads.renderOrder = 3;
    beads.name = 'Flow direction / ' + pipe.name;
    markerGroup.add(beads);
    routes.push({pipe,ribbon,material,beads,beadMaterial,count});
  }

  // Camera anchors stay in original model coordinates. The master timeline is
  // the only camera owner; this module owns no asynchronous animation loop.
  const anchors = {};
  for (const [id, object] of model.equipment) anchors[id] = object.position.clone();
  Object.assign(anchors, {
    hero:new THREE.Vector3(.3,.5,0),
    raw:new THREE.Vector3(-6,-.1,0),
    filter:new THREE.Vector3(-2.3,1.1,0),
    filters:new THREE.Vector3(-2.3,1.1,0),
    sensors:new THREE.Vector3(2.1,.9,-.15),
    valve:new THREE.Vector3(8,.8,0),
    storage:new THREE.Vector3(5,1.05,0),
  });

  let current = normal;
  let currentTime = 0;
  function update(timeSeconds) {
    const t = Math.max(0,Number.isFinite(timeSeconds) ? timeSeconds : 0);
    currentTime = t;
    const holding = t >= 31 && t < 44;
    current = holding ? fault : normal;
    model.apply(holding ? faultScene : normalScene);
    model.update(t, true, 0);
    // The original app rotors are cumulative. Override with absolute time so
    // a frame rendered out of order is identical to a sequential render.
    const flowTime = holding ? 31 : t >= 44 ? t - 13 : t;
    for (const pump of model.pumps) {
      pump.rotor.rotation.x = normalScene.pumps[pump.id] === 'running' ? flowTime * 7 : 0;
    }
    for (const pipe of model.pipes) pipe.dots.visible = false;
    for (const material of lamps) material.emissiveIntensity = .65;
    const frozenTime = flowTime;
    for (const route of routes) {
      const flowing = (current.flow[route.pipe.key + '_lpm'] ?? 0) > 0;
      route.material.color.set(holding ? '#9c6d30' : '#77ccba');
      route.material.opacity = holding ? .14 : .3;
      route.beadMaterial.color.set(holding ? '#bc9354' : '#d9fff1');
      route.beadMaterial.opacity = flowing ? .94 : .32;
      for (let i = 0; i < route.count; i++) {
        const position = (i/route.count + frozenTime*.36/route.pipe.curve.getLength()) % 1;
        matrixDummy.position.copy(route.pipe.curve.getPointAt(position));
        matrixDummy.rotation.set(0,0,0);
        matrixDummy.scale.setScalar(flowing ? 1 : .74);
        matrixDummy.updateMatrix();
        route.beads.setMatrixAt(i,matrixDummy.matrix);
      }
      route.beads.instanceMatrix.needsUpdate = true;
    }
    root.updateMatrixWorld(true);
    return current;
  }
  update(0);

  return {root,model,anchors,update,diagnostics() {
    return {
      time:currentTime, source:current.source, virtual:current.virtual,
      state:current.safety.state, fault:current.fault,
      chlorine:current.chans.chlorine,
      irrigationFeedback:current.equipment.irrigation_feedback,
      reasonCodes:current.safety.reason_codes,
      flow:current.flow, routes:routes.map(route => route.pipe.name),
      originalEquipmentCount:model.equipment.size,
      originalPipeCount:model.pipes.length,
      cumulativeAnimation:false,
    };
  }};
}
