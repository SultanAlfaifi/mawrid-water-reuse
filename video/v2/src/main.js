import * as THREE from 'three';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {createCinemaPlant} from './cinema.js';
import {setupTypography} from './type.js';
import './type.css';

const W=1920,H=1080;
Object.assign(document.documentElement.style,{width:W+'px',height:H+'px',overflow:'hidden',background:'#0a211d'});
Object.assign(document.body.style,{margin:'0',width:W+'px',height:H+'px',overflow:'hidden'});
const renderer=new THREE.WebGLRenderer({canvas:document.querySelector('#picture'),antialias:true,alpha:false,preserveDrawingBuffer:true,powerPreference:'high-performance'});
renderer.setPixelRatio(1);renderer.setSize(W,H);renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.78;
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
const scene=new THREE.Scene();scene.background=new THREE.Color('#061c16');scene.fog=new THREE.FogExp2('#061c16',.005);
const pmrem=new THREE.PMREMGenerator(renderer), room=new RoomEnvironment();
const env=pmrem.fromScene(room,.04);scene.environment=env.texture;scene.environmentIntensity=.22;room.dispose();pmrem.dispose();
scene.add(new THREE.HemisphereLight('#e7f4e4','#09231e',.45));
function light(color,intensity,p,shadow=false){const l=new THREE.DirectionalLight(color,intensity);l.position.set(...p);if(shadow){l.castShadow=true;l.shadow.mapSize.set(2048,2048);Object.assign(l.shadow.camera,{left:-13,right:13,top:10,bottom:-10,near:1,far:50});l.shadow.bias=-.00015;l.shadow.normalBias=.025;}scene.add(l);return l;}
light('#fff4d8',2.5,[-7,14,10],true);light('#86d9c4',1.9,[7,7,-8]);light('#cde1ff',.55,[-10,4,-6]);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(220,220),new THREE.MeshStandardMaterial({color:'#071d16',roughness:.95,metalness:0}));floor.rotation.x=-Math.PI/2;floor.position.y=-1.88;floor.receiveShadow=true;scene.add(floor);
const plant=createCinemaPlant();scene.add(plant.root);
const camera=new THREE.PerspectiveCamera(37,W/H,.08,200);
const target=new THREE.Vector3();
const composer=new EffectComposer(renderer,new THREE.WebGLRenderTarget(W,H,{type:THREE.HalfFloatType,samples:2}));
composer.addPass(new RenderPass(scene,camera));const bloom=new UnrealBloomPass(new THREE.Vector2(W,H),.055,.3,1.6);composer.addPass(bloom);composer.addPass(new OutputPass());
Object.assign(document.querySelector('#atmosphere').style,{position:'absolute',inset:'0',pointerEvents:'none',background:'linear-gradient(to left,rgba(2,17,12,.9),rgba(2,17,12,.62) 32%,transparent 62%),linear-gradient(to bottom,rgba(2,17,12,.75),transparent 22%,transparent 85%,rgba(2,17,12,.6))'});
const type=setupTypography(document.querySelector('#typography'));
const smoother=x=>{x=THREE.MathUtils.clamp(x,0,1);return x*x*x*(x*(x*6-15)+10)};
const lerp=(a,b,p)=>a.map((v,i)=>v+(b[i]-v)*p);
const shots=[
 {a:0,b:6,key:'hero',from:[15,11.5,22],to:[12.8,9.8,20],offset:4},
 {a:6,b:14,key:'raw',from:[3.6,4.7,7.5],to:[2.1,3.2,6.8],offset:1.35},
 {a:14,b:24,key:'filter',from:[4.8,4.5,8.2],to:[2.3,3.2,7.3],offset:1.7},
 {a:24,b:31,key:'sensors',from:[-3.8,2.4,5],to:[-2.6,1.9,4.2],offset:1.2},
 {a:31,b:36,key:'sensors',from:[-2.6,1.9,4.2],to:[-2.2,1.7,4],offset:1.2},
 {a:36,b:44,key:'valve',from:[3.5,2.2,5.4],to:[2.5,1.5,4.4],offset:1.1},
 {a:44,b:51,key:'hero',from:[14,10,21],to:[12.5,9.2,20],offset:2.7},
 {a:51,b:60,key:'hero',from:[12.5,9.2,20],to:[16,11,23],offset:0,ending:true},
];
function anchor(name){const value=plant.anchors[name];return value?.clone?value.clone():new THREE.Vector3(...(value||[.5,.7,0]));}
window.renderFilmFrame=async(frame)=>{
 const t=THREE.MathUtils.clamp(frame/30,0,59.999);plant.update(t);
 const shot=shots.find(s=>t>=s.a&&t<s.b)||shots.at(-1),p=smoother((t-shot.a)/(shot.b-shot.a));
 target.copy(anchor(shot.key));const delta=new THREE.Vector3(...lerp(shot.from,shot.to,p));
 const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),delta).normalize();target.addScaledVector(right,shot.offset);
 if(shot.ending)target.y+=2.8*smoother((t-51)/3);
 camera.position.copy(target).add(delta);camera.lookAt(target);camera.updateMatrixWorld();type.update(t);
 composer.render(0);
 return {frame,t,shot:shot.key,camera:camera.position.toArray(),target:target.toArray(),...plant.diagnostics(),type:type.diagnostics()};
};
await document.fonts.ready;await Promise.all([...document.images].map(im=>im.decode().catch(()=>{})));await window.renderFilmFrame(0);
window.FILM_READY=true;window.FILM_META={width:W,height:H,fps:30,frames:1800,deterministic:true,shots};
