import assert from 'node:assert/strict';
import * as THREE from 'three';
import { unitSpec, resolveSpec } from '../src/unitSpec.js';
import { getComponents, csvFromComponents } from '../src/components.js';
import { createMaterials } from '../src/materials.js';
import { createPlant } from '../src/model.js';

// Geometry-only verification. Canvas drawing is stubbed deliberately: visual,
// WebGL, typography, export and accessibility checks still need a real browser.
globalThis.document = {
  createElement(name) {
    assert.equal(name, 'canvas');
    const context = new Proxy({
      createImageData(w, h) { return { data: new Uint8ClampedArray(w * h * 4) }; },
      measureText(value) { return { width: String(value).length * 10 }; },
    }, { get(target, key) { return key in target ? target[key] : () => {}; } });
    return { width: 0, height: 0, getContext() { return context; } };
  },
};

const finite = (value, message) => assert(Number.isFinite(value), message);
const reports = [];
for (const key of Object.keys(unitSpec.presets)) {
  const spec = resolveSpec(key), components = getComponents(spec);
  assert.deepEqual(components.map(row => row.id), Array.from({ length: 15 }, (_, i) => i + 1));
  assert.equal(new Set(components.map(row => row.code)).size, 15);
  assert.equal(csvFromComponents(spec).split('\r\n').length, 16);
  assert(csvFromComponents(spec).startsWith('\uFEFF'));
  assert.equal(spec.common.panel.centerHeight, 1.5);
  assert.equal(spec.human.height, 1.75);
  assert.equal(spec.common.drain.outerDiameter, .063);
  assert.equal(spec.pipe.outerDiameter, key === 'M30' ? .05 : .04);
  const headHeight = spec.layout.equipmentBaseY + Math.max(spec.sand.height, spec.carbon.height) + spec.valveHead.height;
  assert(headHeight < spec.layout.maximumHeadY);
  assert(spec.layout.service.headClearance >= .5);

  const materials = createMaterials(spec), plant = createPlant(spec, materials);
  plant.root.updateMatrixWorld(true);
  assert.equal(plant.groups.size, 15);
  let meshes = 0, vertices = 0;
  plant.root.traverse(object => {
    object.matrixWorld.elements.forEach(number => finite(number, `${key}: non-finite transform in ${object.name || object.type}`));
    if (!object.isMesh) return;
    meshes++;
    const positions = object.geometry?.getAttribute('position');
    if (positions) {
      vertices += positions.count;
      for (const number of positions.array) finite(number, `${key}: non-finite vertex in component ${object.userData.id || object.name}`);
    }
    if (object.isInstancedMesh) for (const number of object.instanceMatrix.array) finite(number, `${key}: non-finite instance transform`);
  });

  for (const run of plant.pipeRuns) {
    assert(plant.ports.has(run.from), `${key}: missing start port ${run.from}`);
    assert(plant.ports.has(run.to), `${key}: missing finish port ${run.to}`);
    assert(run.curve.getLength() > 0, `${key}: empty pipe ${run.name}`);
    for (const [portName, t] of [[run.from, 0], [run.to, 1]]) {
      const port = plant.ports.get(portName);
      const world = port.local.clone().add(plant.groups.get(port.id).userData.home);
      assert(world.distanceTo(run.curve.getPointAt(t)) < 1e-6, `${key}: disconnected endpoint ${portName}`);
    }
  }
  // A drain may penetrate grade only vertically at a deliberate drop point.
  // Raised collector barrels must remain completely above the ground plane.
  for (const run of plant.pipeRuns.filter(run => run.kind === 'drain')) {
    for (let i = 1; i < run.points.length; i++) {
      const a = run.points[i - 1], b = run.points[i];
      if ((a.y > 0 && b.y < 0) || (a.y < 0 && b.y > 0)) {
        assert(Math.hypot(a.x - b.x, a.z - b.z) < 1e-6, `${key}: diagonal drain crosses grade: ${run.name}`);
      }
    }
    if (run.name.startsWith('gravity-main-')) for (let i = 0; i <= 40; i++) {
      assert(run.curve.getPointAt(i / 40).y >= spec.common.drain.outerDiameter / 2 + spec.detail.labels.surfaceGap, `${key}: collector intersects grade`);
    }
  }
  for (const id of [4, 11]) {
    const outlet = plant.ports.get(`${id}.out`).local;
    assert(outlet.x < 0, `${key}: pump discharge must be on the wet-stage side`);
    assert(outlet.y > spec.layout.equipmentBaseY + spec.detail.pump.footHeight + spec.detail.pump.isolatorHeight + spec.common.pump.motorDiameter, `${key}: discharge must rise above the wet-stage body`);
  }
  const gapOut = plant.ports.get('airgap.spout'), gapIn = plant.ports.get('airgap.receptor');
  assert(Math.abs(gapOut.local.y - gapIn.local.y - spec.detail.fittings.drainAirGap) < 1e-8);
  assert(!plant.pipeRuns.some(run => run.from === 'airgap.spout' && run.to === 'airgap.receptor'), 'Air gap must remain open');

  const operatingFlows = {};
  for (const mode of ['normal', 'backwash', 'fault', 'poweroff']) {
    plant.updateState({ mode, flow: true, cutaway: false, exploded: false, human: false });
    plant.update(1, 1, true);
    operatingFlows[mode] = plant.pipeRuns.filter(run => run.particles.visible).map(run => run.name);
    const irrigation = plant.pipeRuns.find(run => run.name === 'irrigation-isolation');
    assert.equal(irrigation.particles.visible, mode === 'normal', `${key}: irrigation must be isolated in ${mode}`);
    if (mode === 'poweroff') assert.equal(operatingFlows[mode].length, 0);
  }
  plant.updateState({ exploded: true });
  plant.update(2, 1, true);
  for (const run of plant.pipeRuns) assert(run.dashed.visible);
  plant.updateState({ exploded: false });
  plant.update(3, 1, true);

  // Detect pipe centerlines penetrating the straight cylindrical FRP barrel.
  // This deliberately excludes shoulders and registered head connections.
  const barrelIntersections = [];
  for (const [id, dimension] of [[5, spec.sand], [6, spec.carbon]]) {
    const p = plant.groups.get(id).userData.home;
    for (const run of plant.pipeRuns) {
      const radius = (run.kind === 'drain' ? spec.common.drain.outerDiameter : spec.pipe.outerDiameter) / 2;
      let hit = false;
      for (let i = 1; i < 200; i++) {
        const q = run.curve.getPointAt(i / 200);
        if (q.y <= p.y + spec.detail.frp.shoulderHeight || q.y >= p.y + dimension.height - spec.detail.frp.shoulderHeight) continue;
        if (Math.hypot(q.x - p.x, q.z - p.z) < dimension.diameter / 2 + radius) { hit = true; break; }
      }
      if (hit) barrelIntersections.push({ component: id, pipe: run.name });
    }
  }

  const chamberOverflow = plant.pipeRuns.find(run => run.name === 'chamber-overflow');
  let gravityRise = false;
  for (let i = 1; i < chamberOverflow.points.length; i++) if (chamberOverflow.points[i].y > chamberOverflow.points[i - 1].y + 1e-6) gravityRise = true;
  reports.push({ preset: key, headHeight: Number(headHeight.toFixed(3)), components: components.length, pipeRuns: plant.pipeRuns.length, meshes, vertices, barrelIntersections, chamberOverflowHasRise: gravityRise, operatingFlows });
  plant.dispose(); materials.dispose();
}

console.log(JSON.stringify({ geometryChecks: 'passed', reports }, null, 2));
if (reports.some(report => report.barrelIntersections.length || report.chamberOverflowHasRise)) {
  console.error('Engineering routing audit requires review: barrel intersections or upward gravity-drain segments found.');
  process.exitCode = 1;
}
