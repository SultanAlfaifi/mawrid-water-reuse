import * as THREE from 'three';

const normalURL=new URL('../assets/phone-normal.png',import.meta.url).href;
const dropoutURL=new URL('../assets/phone-dropout.png',import.meta.url).href;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
const ease=x=>{x=clamp(x);return x*x*(3-2*x)};

function roundRect(w,h,r){
 const s=new THREE.Shape(),x=-w/2,y=-h/2;
 s.moveTo(x+r,y);s.lineTo(x+w-r,y);s.quadraticCurveTo(x+w,y,x+w,y+r);
 s.lineTo(x+w,y+h-r);s.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
 s.lineTo(x+r,y+h);s.quadraticCurveTo(x,y+h,x,y+h-r);
 s.lineTo(x,y+r);s.quadraticCurveTo(x,y,x+r,y);return s;
}
function face(w,h,r,z,material){
 const geometry=new THREE.ShapeGeometry(roundRect(w,h,r),28);
 const positions=geometry.attributes.position,uv=geometry.attributes.uv;
 for(let i=0;i<positions.count;i++)uv.setXY(i,(positions.getX(i)+w/2)/w,(positions.getY(i)+h/2)/h);
 uv.needsUpdate=true;
 const mesh=new THREE.Mesh(geometry,material);mesh.position.z=z;return mesh;
}
function body(w,h,d,r,material){
 const geo=new THREE.ExtrudeGeometry(roundRect(w,h,r),{depth:d,bevelEnabled:true,bevelSegments:5,steps:1,bevelSize:.038,bevelThickness:.035,curveSegments:20});
 geo.translate(0,0,-d/2);const mesh=new THREE.Mesh(geo,material);mesh.castShadow=true;return mesh;
}

/**
 * Original procedural phone geometry. Screen textures are unaltered screenshots
 * of MAWRID's actual deployed browser simulation, not a remote station or AI UI.
 * Coordinates: centered, 2.9 x 6.2 x .2 world units, screen faces +Z.
 * Caller should await ready once before frame capture and light the metal body.
 */
export function createPhoneShot(){
 const root=new THREE.Group();root.name='actual-mobile-simulation-phone';
 const frame=new THREE.MeshStandardMaterial({color:'#344b45',roughness:.25,metalness:.94});
 const black=new THREE.MeshStandardMaterial({color:'#07100f',roughness:.19,metalness:.35});
 const edge=new THREE.MeshStandardMaterial({color:'#718b82',roughness:.22,metalness:.93});
 const keys=new THREE.MeshStandardMaterial({color:'#405c52',roughness:.25,metalness:.9});
 root.add(body(2.90,6.20,.14,.29,frame));
 root.add(face(2.885,6.185,.285,.111,black));
 // Thin machined inner rim bounds the screen without hiding the actual UI.
 root.add(face(2.731,5.845,.175,.127,edge));
 root.add(face(2.713,5.827,.166,.130,black));

 const screenMaterial=new THREE.MeshBasicMaterial({color:'#ffffff',toneMapped:false});
 const screen=face(2.67,2.67*844/390,.145,.135,screenMaterial);
 screen.name='unaltered-390x844-live-ui-capture';root.add(screen);
 const loader=new THREE.TextureLoader();
 let normalTexture,dropoutTexture,loaded=0,loadError=null;
 const ready=Promise.all([normalURL,dropoutURL].map(url=>new Promise((resolve,reject)=>{
  loader.load(url,t=>{t.colorSpace=THREE.SRGBColorSpace;t.minFilter=THREE.LinearMipmapLinearFilter;t.magFilter=THREE.LinearFilter;t.anisotropy=8;loaded++;resolve(t)},undefined,e=>{loadError=String(e);reject(e)});
 }))).then(([n,d])=>{normalTexture=n;dropoutTexture=d;screenMaterial.map=normalTexture;screenMaterial.needsUpdate=true;return true});

 const speaker=face(.42,.034,.016,.142,new THREE.MeshStandardMaterial({color:'#020706',roughness:.9,metalness:.1}));speaker.position.y=3.006;root.add(speaker);
 const lensRim=new THREE.Mesh(new THREE.CylinderGeometry(.042,.042,.009,24),edge);lensRim.rotation.x=Math.PI/2;lensRim.position.set(.405,3.006,.145);root.add(lensRim);
 const lens=new THREE.Mesh(new THREE.CircleGeometry(.027,24),new THREE.MeshPhysicalMaterial({color:'#142b38',metalness:.25,roughness:.15,clearcoat:1}));lens.position.set(.405,3.006,.151);root.add(lens);
 const glint=new THREE.Mesh(new THREE.CircleGeometry(.009,16),new THREE.MeshBasicMaterial({color:'#8ab9b2',transparent:true,opacity:.75}));glint.position.set(.397,3.016,.153);root.add(glint);
 function key(x,y,h){const mesh=new THREE.Mesh(new THREE.BoxGeometry(.055,h,.085),keys);mesh.position.set(x,y,-.008);root.add(mesh)}
 key(1.502,.89,.64);key(-1.502,1.14,.42);key(-1.502,.55,.42);
 // The low center speaker slot identifies orientation without any invented UI.
 const bottomSlot=face(.28,.019,.009,.145,new THREE.MeshBasicMaterial({color:'#485d55'}));bottomSlot.position.y=-3.008;root.add(bottomSlot);
 let current='normal',lastTime=0;
 function update(timeSeconds){
  lastTime=timeSeconds;const p=ease((timeSeconds-40)/11);
  root.rotation.set(-.018+.025*p,-.30+.42*p,-.045+.03*p);
  root.position.y=.025*Math.sin(clamp((timeSeconds-40)/11)*Math.PI);
  const selected=timeSeconds>=44&&timeSeconds<48?'dropout':'normal';
  if(selected!==current||!screenMaterial.map){current=selected;screenMaterial.map=current==='dropout'?dropoutTexture:normalTexture;screenMaterial.needsUpdate=true}
 }
 update(40);
 return {root,ready,update,diagnostics:()=>({phoneShot:true,source:'actual_public_browser_simulation',hardwareConnected:false,mlUsed:false,screenState:current,sourceURL:'https://sultalfaifi.com/mawrid-water-reuse/experience/',screenshotViewport:[390,844],screenshotPixelSize:[1170,2532],texturesLoaded:loaded,loadError,timeSeconds:lastTime,texture:screenMaterial.map?.image?.src||null})};
}
