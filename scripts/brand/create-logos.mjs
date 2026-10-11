import { C, LOGOS, logoBody, svgWrap, write } from './shared.mjs';
for(const [variant,geometry]of Object.entries(LOGOS)) {
  const name=variant==='ar'?'primary':variant;
  for(const [tone,color]of Object.entries({green:C.forest,white:C.white,ink:C.ink})) {
    write(`assets/brand/logos/mawrid-${name}-${tone}.svg`,svgWrap(geometry.width,geometry.height,logoBody(color,variant),`مورد · ${variant} · ${tone}`));
  }
  write(`assets/brand/logos/mawrid-${name}.svg`,svgWrap(geometry.width,geometry.height,logoBody(C.forest,variant)));
}
write('assets/brand/mawrid-logo.svg',svgWrap(48,48,`<rect width="48" height="48" rx="8" fill="${C.mint}"/>`+logoBody(C.forest,'mark')));
const colorSpecs=Object.fromEntries(Object.entries(C).map(([name,hex])=>{
  const rgb=hex.slice(1).match(/../g).map(n=>parseInt(n,16));
  const k=1-Math.max(...rgb)/255;
  const cmyk=rgb.map(v=>Math.round(((1-v/255-k)/(1-k||1))*100)).concat(Math.round(k*100));
  return [name,{hex,rgb,cmykApprox:cmyk}];
}));
write('assets/brand/colors.json',JSON.stringify({name:'MAWRID / مورد',version:'1.0',colors:C,specifications:colorSpecs,print:'CMYK values are mathematical approximations; production conversion uses the printer profile.',type:{arabic:'IBM Plex Sans Arabic',english:'Manrope'},tagline:{ar:'مياه الوضوء، موردٌ للري.',en:'Ablution water, a resource for irrigation.'}},null,2)+'\n');
write('assets/brand/palette.csv','name,HEX,R,G,B,C_approx,M_approx,Y_approx,K_approx\n'+Object.entries(colorSpecs).map(([name,v])=>[name,v.hex,...v.rgb,...v.cmykApprox].join(',')).join('\n')+'\n');
write('assets/brand/mawrid-tokens.css',`:root {\n${Object.entries(C).map(([name,value])=>`  --mawrid-${name}: ${value};`).join('\n')}\n  --mawrid-font-ar: 'Plex Arabic', sans-serif;\n  --mawrid-font-en: 'Manrope', sans-serif;\n  --mawrid-radius: 8px;\n  --mawrid-grid: 8px;\n  --mawrid-motion-short: 180ms;\n  --mawrid-motion-scene: 720ms;\n}\n`);
console.log('MAWRID logo family and tokens exported with outlined type.');
