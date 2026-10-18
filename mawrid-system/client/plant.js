/* Digital-twin presentation. Values are supplied by the server, never generated here. */
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const finite = value => typeof value === 'number' && Number.isFinite(value);
const number = (value, digits = 1) => finite(value) ? new Intl.NumberFormat('en-US', {maximumFractionDigits:digits}).format(value) : '—';
const unit = (value, label, digits = 1) => `<bdi>${number(value, digits)}</bdi> <small>${esc(label)}</small>`;
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const clock = value => typeof value === 'string' ? value.replace('T',' ').replace(/\.\d+(?=Z|[+-]\d\d:|$)/,'').replace(/Z$/,' UTC') : '—';
export const PLANT_MODES = {auto:'تشغيل تلقائي',standby:'استعداد',backwash:'غسيل عكسي'};
export const PLANT_FAULTS = {none:'تشغيل اعتيادي',turbidity:'ارتفاع العكارة',sensor_dropout:'انقطاع قراءة حساس',clogging:'انسداد المرشح',power_loss:'انقطاع الكهرباء',valve_stuck:'تعطل صمام الري'};
export const EQUIPMENT = {
  collection: {name:'خزان التجميع',tag:'TK-101',description:'يستقبل مياه الاستخدام ويوازن التدفق الداخل إلى خط المعالجة.'},
  pump: {name:'مضخة التغذية',tag:'P-101',description:'تنقل المياه من خزان التجميع إلى وحدات الترشيح حسب وضع العملية.'},
  media: {name:'مرشح الوسائط',tag:'F-101',description:'مرحلة إزالة العوالق. فرق الضغط يساعد على متابعة مقاومة المرشح والحاجة للغسيل.'},
  carbon: {name:'مرشح الكربون',tag:'F-102',description:'مرحلة الكربون ضمن سلسلة المعالجة الافتراضية.'},
  disinfection: {name:'وحدة التعقيم',tag:'D-101',description:'مرحلة الجرعات الافتراضية قبل خزان المياه المعالجة؛ الحالة المعروضة لمضخات الجرعات.'},
  treated: {name:'خزان المياه المعالجة',tag:'TK-102',description:'يخزن الماء الخارج من المعالجة قبل قرار توجيهه إلى الري أو الصرف.'},
  irrigation: {name:'صمام الري الافتراضي',tag:'XV-201',description:'يُتاح المسار وفق قواعد التوأم الرقمي. الحجم المعروض ناتج المحاكاة، وليس وفرًا مائيًا ميدانيًا.'},
  drain: {name:'مسار الصرف',tag:'XV-202',description:'مسار التحويل أو التصريف داخل المحاكاة عند الحاجة التشغيلية.'},
};
const statusNames = {running:'يعمل',on:'يعمل',off:'متوقف',stopped:'متوقف',open:'مفتوح',closed:'مغلق',ready:'جاهز',normal:'اعتيادي',fault:'عطل',blocked:'محجوز',warning:'تنبيه',backwash:'غسيل',standby:'استعداد',unavailable:'غير متاح'};
const statusText = value => statusNames[value] || value || 'غير متاح';
const statusTone = value => ['fault','blocked','failed','stuck'].includes(value) ? 'danger' : ['running','on','open','ready','normal'].includes(value) ? 'good' : value === 'warning' ? 'warning' : 'neutral';
const badge = (label,tone='neutral') => `<span class="plant-chip ${tone}"><i></i>${esc(label)}</span>`;
const field = (name,value) => `<div><dt>${esc(name)}</dt><dd>${value}</dd></div>`;

// The adapter is deliberately narrow. A different source never inherits a
// virtual-plant snapshot left behind by a previous session.
export function plantView(data) {
  const p = data?.virtual_plant, s = data?.session;
  if (data?.source?.kind !== 'digital_twin' || data?.source?.id !== 'virtual_plant' || !s?.id || !p || p.session_id !== s.id)
    return {active:false,sessionId:null};
  const ch=p.chans||{}, e=p.equipment||{}, f=p.flow||{}, tanks=p.tanks||{};
  const pressure=(a,b)=>finite(ch[a])&&finite(ch[b])?ch[a]-ch[b]:null;
  const tank=t=>t?{liters:t.liters,capacity_liters:t.capacity_liters,level_pct:t.level_percent,status:'مخزون محاكى'}:undefined;
  const through=finite(f.treatment_lpm)&&f.treatment_lpm>0?'running':'stopped';
  const process={REUSE:'معالجة وري',HOLD:'احتجاز',STANDBY:'استعداد',BACKWASH:'غسيل عكسي'};
  return {active:true,sessionId:s.id,running:p.running===true,simulation_timestamp:p.timestamp,
    mode:p.mode,fault:p.fault,speed:p.speed,safety_state:p.safety?.state,
    process_state:process[p.safety?.state]||p.safety?.state,
    tanks:{collection:tank(tanks.raw),treated:tank(tanks.treated)},
    treatment_flow_lpm:f.treatment_lpm,inlet_flow_lpm:f.inlet_lpm,irrigation_flow_lpm:f.reuse_lpm,
    drain_flow_lpm:finite(f.drain_lpm)&&finite(f.backwash_lpm)?f.drain_lpm+f.backwash_lpm:null,
    reject_flow_lpm:f.drain_lpm,backwash_flow_lpm:f.backwash_lpm,
    irrigation_liters:p.volumes?.reuse_liters,filter_delta_pressure_bar:pressure('p1_bar','p2_bar'),carbon_delta_pressure_bar:pressure('p2_bar','p3_bar'),
    equipment:{pump:{status:e.feed_pump},media:{status:p.fault==='clogging'?'warning':through},carbon:{status:through},
      disinfection:{status:e.dosing_pumps},irrigation:{status:e.irrigation_valve},drain:{status:e.drain_valve}},
    readings:{outlet_turbidity:p.validity?.turbidity===false?null:ch.turbidity,chlorine:p.validity?.chlorine===false?null:ch.chlorine,ph:p.validity?.ph===false?null:ch.ph},
    reasons:p.safety?.reasons||[],events:(data.alarms||[]).filter(event=>event.session_id===s.id),
  };
}
function metric(title,value,note,name) {
  return `<article class="plant-metric"><span class="plant-metric-icon">${icon(name)}</span><div><p>${esc(title)}</p><strong>${value}</strong><small>${esc(note)}</small></div></article>`;
}
function metrics(v) {
  return metric('تدفق المعالجة',unit(v.treatment_flow_lpm,'L/min'),'التدفق الحالي في الخط','wave')+
    metric('الري المحاكى',unit(v.irrigation_liters,'L'),'إجمالي هذه الجلسة الافتراضية','droplet')+
    metric('فرق ضغط المرشح',unit(v.filter_delta_pressure_bar,'bar',2),'عبر مرشح الوسائط','settings')+
    metric('وضع العملية',`<span class="plant-mode-value">${esc(v.process_state || PLANT_MODES[v.mode] || 'غير متاح')}</span>`,'من متحكم المحاكاة','shield');
}
function selected(id,ui) { return ui.equipment === id ? ' selected' : ''; }
function equipmentOpen(id,ui) {
  return `<g class="plant-equipment${selected(id,ui)}" data-equipment="${id}" tabindex="0" role="button" aria-label="تفاصيل ${EQUIPMENT[id].name}" aria-pressed="${ui.equipment === id}">`;
}
function svgLabel(x,y,id,status) {
  return `<text class="plant-svg-tag" x="${x}" y="${y}" text-anchor="middle">${EQUIPMENT[id].tag}</text><text class="plant-svg-name" x="${x}" y="${y+23}" text-anchor="middle">${EQUIPMENT[id].name}</text><text class="plant-svg-status ${statusTone(status)}" x="${x}" y="${y+42}" text-anchor="middle">${esc(statusText(status))}</text>`;
}
function tank(id,x,v,ui) {
  const t=v.tanks?.[id] || {}, pct=finite(t.level_pct)?Math.max(0,Math.min(100,t.level_pct)):null;
  const h=pct===null?0:120*pct/100, y=295-h;
  const previous=ui.previousLevels?.[id], from=finite(previous)?120*Math.max(0,Math.min(100,previous))/100:h;
  return `${equipmentOpen(id,ui)}<rect class="equipment-hit" x="${x-18}" y="92" width="148" height="270" rx="14"/><rect class="tank-shell" x="${x}" y="157" width="112" height="150" rx="11"/><rect class="tank-inner" x="${x+8}" y="165" width="96" height="134" rx="7"/><rect class="tank-water" x="${x+9}" y="${y}" width="94" height="${h}" rx="4">${from!==h&&!ui.reducedMotion?`<animate attributeName="height" from="${from}" to="${h}" dur="0.45s" fill="freeze"/><animate attributeName="y" from="${295-from}" to="${y}" dur="0.45s" fill="freeze"/>`:''}</rect><path class="tank-scale" d="M${x+90} 180h13m-13 23h13m-13 23h13m-13 23h13m-13 23h13"/><ellipse class="tank-cap" cx="${x+56}" cy="157" rx="56" ry="13"/><path class="equipment-foot" d="M${x+20} 308v13h-9m81-13v13h9"/><text class="tank-percent" x="${x+50}" y="237" text-anchor="middle">${pct===null?'—':number(pct,0)+'%'}</text><text class="tank-liters" x="${x+56}" y="283" text-anchor="middle">${number(t.liters,0)} L</text>${svgLabel(x+56,88,id,t.status)}</g>`;
}
function filter(id,x,v,ui) {
  const s=v.equipment?.[id]?.status;
  return `${equipmentOpen(id,ui)}<rect class="equipment-hit" x="${x-17}" y="103" width="116" height="220" rx="13"/><rect class="filter-shell" x="${x}" y="189" width="82" height="97" rx="15"/><ellipse class="filter-top" cx="${x+41}" cy="189" rx="41" ry="11"/><path class="filter-band" d="M${x+2} 215h78m-78 45h78"/><rect class="filter-media ${id==='carbon'?'carbon':''}" x="${x+10}" y="222" width="62" height="31" rx="3"/><path class="equipment-foot" d="M${x+15} 285v25h-9m61-25v25h9"/>${svgLabel(x+41,125,id,s)}</g>`;
}
function pipe(d,flow,extra='') {
  return `<path class="plant-pipe-base ${extra}" d="${d}"/><path class="plant-pipe ${finite(flow)&&flow>0?'flowing':''} ${extra}" d="${d}"/>`;
}
function diagram(v,ui) {
  const eq=v.equipment||{}, flow=v.running?v.treatment_flow_lpm:null;
  return `<svg class="plant-process-svg" viewBox="0 0 1260 430" role="group" aria-label="خط المعالجة؛ اختر جهازًا لعرض تفاصيله"><defs><linearGradient id="tank-steel" x1="0" x2="1"><stop offset="0" stop-color="#eef1e9"/><stop offset=".45" stop-color="#fffefa"/><stop offset="1" stop-color="#e2e9dd"/></linearGradient><linearGradient id="tank-water" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#94b9a1"/><stop offset="1" stop-color="#548b71"/></linearGradient></defs>
    <path class="plant-floor" d="M24 335H1236"/><text class="plant-line-label" x="1170" y="67" text-anchor="middle">مياه الاستخدام</text>${pipe('M1170 78V150',v.running?v.inlet_flow_lpm:null)}
    ${pipe('M1090 252H990',flow)}${pipe('M932 252H845',flow)}${pipe('M763 252H684',flow)}${pipe('M602 252H537',flow)}${pipe('M421 252H337',flow)}
    ${pipe('M225 237H121V178H72',v.running?v.irrigation_flow_lpm:null)}${pipe('M742 252V329H72',v.running?v.drain_flow_lpm:null,'drain-pipe')}
    ${pipe('M281 307V414H804V286',v.running?v.backwash_flow_lpm:null,'backwash-pipe')}
    <text class="plant-line-label" x="545" y="427" text-anchor="middle">خط الغسيل العكسي</text>
    <path class="pipe-direction" d="m1023 247-8 5 8 5m-125-10-8 5 8 5m-185-10-8 5 8 5m-159-10-8 5 8 5m-175-10-8 5 8 5"/>
    ${tank('collection',1090,v,ui)}${tank('treated',225,v,ui)}
    ${equipmentOpen('pump',ui)}<rect class="equipment-hit" x="915" y="104" width="94" height="219" rx="13"/><path class="pump-base" d="M931 288h61v17h-61Z"/><circle class="pump-body" cx="962" cy="252" r="32"/><g class="pump-rotor ${v.running&&['running','on'].includes(eq.pump?.status)?'running':''}" style="transform-origin:962px 252px"><path d="M962 252c-24-13-22-26-7-26l7 26c15-22 28-19 25-4l-25 4c9 26-1 34-12 24Z"/></g>${svgLabel(962,125,'pump',eq.pump?.status)}</g>
    ${filter('media',763,v,ui)}${filter('carbon',602,v,ui)}
    ${equipmentOpen('disinfection',ui)}<rect class="equipment-hit" x="402" y="104" width="151" height="219" rx="13"/><rect class="uv-shell" x="421" y="230" width="116" height="45" rx="20"/><rect class="uv-lamp ${['running','on'].includes(eq.disinfection?.status)?'on':''}" x="436" y="248" width="86" height="8" rx="4"/><path class="equipment-foot" d="M443 275v28m72-28v28"/>${svgLabel(479,125,'disinfection',eq.disinfection?.status)}</g>
    ${equipmentOpen('irrigation',ui)}<rect class="equipment-hit" x="14" y="111" width="135" height="111" rx="13"/><path class="valve-symbol ${eq.irrigation?.status==='open'?'open':''}" d="m67 167 20 11-20 11Zm40 0-20 11 20 11ZM87 177v-22m-10 0h20"/><text class="outlet-name" x="78" y="137" text-anchor="middle">الري</text><text class="plant-svg-status ${statusTone(eq.irrigation?.status)}" x="78" y="211" text-anchor="middle">${esc(statusText(eq.irrigation?.status))}</text></g>
    ${equipmentOpen('drain',ui)}<rect class="equipment-hit" x="14" y="276" width="135" height="115" rx="13"/><path class="valve-symbol ${eq.drain?.status==='open'?'open':''}" d="m67 318 20 11-20 11Zm40 0-20 11 20 11ZM87 328v-22m-10 0h20"/><text class="outlet-name" x="78" y="296" text-anchor="middle">الصرف</text><text class="plant-svg-status ${statusTone(eq.drain?.status)}" x="78" y="370" text-anchor="middle">${esc(statusText(eq.drain?.status))}</text></g>
    <g class="instrument"><rect x="1025" y="349" width="185" height="50" rx="7"/><text x="1197" y="369" text-anchor="end">تدفق التجميع</text><text class="instrument-value" x="1038" y="391">${number(v.inlet_flow_lpm,1)} L/min</text></g>
    <g class="instrument"><rect x="738" y="349" width="153" height="50" rx="7"/><text x="878" y="369" text-anchor="end">فرق الضغط</text><text class="instrument-value" x="751" y="391">${number(v.filter_delta_pressure_bar,2)} bar</text></g>
    <g class="instrument"><rect x="405" y="349" width="180" height="50" rx="7"/><text x="572" y="369" text-anchor="end">عكارة بعد المعالجة</text><text class="instrument-value" x="418" y="391">${number(v.readings?.outlet_turbidity,2)} NTU</text></g>
    <g class="instrument"><rect x="199" y="349" width="172" height="50" rx="7"/><text x="358" y="369" text-anchor="end">الكلور المتبقي</text><text class="instrument-value" x="212" y="391">${number(v.readings?.chlorine,2)} mg/L</text></g>
  </svg>`;
}
function details(v,ui) {
  const id=Object.hasOwn(EQUIPMENT,ui.equipment)?ui.equipment:'collection', e=EQUIPMENT[id], t=v.tanks?.[id], status=t?.status||v.equipment?.[id]?.status;
  let rows=field('حالة الجهاز',badge(statusText(status),statusTone(status)));
  if(t) rows+=field('المستوى',unit(t.level_pct,'%'))+field('الحجم الحالي',unit(t.liters,'L'))+field('سعة الخزان',unit(t.capacity_liters,'L',0));
  if(id==='pump') rows+=field('تدفق المعالجة',unit(v.treatment_flow_lpm,'L/min'));
  if(id==='media') rows+=field('فرق الضغط',unit(v.filter_delta_pressure_bar,'bar',2));
  if(id==='carbon') rows+=field('فرق الضغط',unit(v.carbon_delta_pressure_bar,'bar',2));
  if(id==='disinfection') rows+=field('الكلور المتبقي',unit(v.readings?.chlorine,'mg/L',2));
  if(id==='irrigation') rows+=field('التدفق الحالي',unit(v.irrigation_flow_lpm,'L/min'))+field('حجم الري المحاكى',unit(v.irrigation_liters,'L'));
  if(id==='drain') rows+=field('إجمالي التصريف',unit(v.drain_flow_lpm,'L/min'))+field('رفض المعالجة',unit(v.reject_flow_lpm,'L/min'))+field('الغسيل العكسي',unit(v.backwash_flow_lpm,'L/min'));
  return `<div class="plant-detail-heading"><span class="plant-tag">${e.tag}</span>${badge(statusText(status),statusTone(status))}</div><h3>${e.name}</h3><p>${e.description}</p><dl class="plant-detail-values">${rows}</dl><small class="plant-detail-note">${v.active?'الحالة من محرك التوأم الرقمي.':'تظهر الحالة عند تشغيل المنشأة الافتراضية.'}</small>`;
}
function events(v) {
  const rows=Array.isArray(v.events)?v.events.slice(0,6):[];
  return rows.length?rows.map(event=>`<article class="plant-event"><span class="plant-event-dot ${esc(['critical','warning'].includes(event.severity)?event.severity:'info')}"></span><div><strong>${esc(event.title || event.message || 'حدث تشغيل')}</strong><p>${esc(event.detail || '')}</p></div><div class="plant-event-actions"><time dir="ltr">${esc(clock(event.timestamp))}</time>${Number.isSafeInteger(event.id) && !event.acknowledged_at ? `<button class="text-button" data-action="ack" data-id="${event.id}" data-mutation>تم الاطلاع ${icon('check')}</button>` : event.acknowledged_at ? '<small>تم الاطلاع</small>' : ''}</div></article>`).join(''):'<div class="plant-events-empty">لا أحداث تشغيل مسجلة لهذه الجلسة.</div>';
}
export function plantRegions(data,ui={equipment:'collection'}) {
  const v=plantView(data);
  return {kpis:metrics(v),diagram:diagram(v,ui),detail:details(v,ui),events:events(v),
    process:`${badge(v.process_state || PLANT_MODES[v.mode] || 'بانتظار التشغيل',({REUSE:'good',HOLD:'danger',BACKWASH:'warning',STANDBY:'neutral'})[v.safety_state]||'neutral')}<span class="plant-clock">${v.active&&!v.running?'المحاكاة متوقفة مؤقتًا · ':''}ساعة المحاكاة <bdi>${esc(clock(v.simulation_timestamp))}</bdi></span><a class="button small" href="/plant3d/index.html" target="_blank" rel="noopener">عرض المنشأة 3D</a>`,
    reasons:Array.isArray(v.reasons)&&v.reasons.length?`<div class="plant-reasons">${icon('info')}<span>${v.reasons.map(esc).join(' · ')}</span></div>`:''};
}
export function plantPage(data,ui={equipment:'collection'},disabled=false) {
  const v=plantView(data), r=plantRegions(data,ui);
  const select=(id,title,options,value)=>`<label class="plant-select"><span>${title}</span><select id="${id}" data-plant-control ${disabled||!v.active?'disabled':''}>${Object.entries(options).map(([key,label])=>`<option value="${key}" ${String(value)===key?'selected':''}>${label}</option>`).join('')}</select></label>`;
  return `<div id="plant-screen" data-session="${esc(v.sessionId||'')}" class="${v.active?'plant-active':'plant-idle'}${ui.zoom?' plant-zoomed':''}"><div class="plant-context"><span class="plant-identity"><i></i>توأم رقمي · منشأة افتراضية</span><div data-plant-region="process">${r.process}</div></div>${!v.active?`<section class="plant-start"><div><span>وحدة مورد / خط المعالجة 01</span><h2>المنشأة جاهزة للتشغيل الافتراضي</h2><p>ابدأ الجلسة لتتابع توازن الخزانات ومسار المعالجة، ثم اختبر استجابة الوحدة لسيناريوهات الأعطال.</p></div><button class="button primary" data-action="plant-start" data-mutation ${disabled?'disabled':''}>${icon('play')}تشغيل المنشأة الافتراضية</button></section>`:''}
    <div class="plant-kpis" data-plant-region="kpis">${r.kpis}</div>
    <section class="plant-process-panel"><div class="plant-process-heading"><div><span class="plant-section-code">PROCESS / 01</span><h2>مسار المياه داخل مورد</h2></div><div class="plant-legend"><span><i class="legend-flow"></i>معالجة</span><span><i class="legend-drain"></i>تصريف</span><span>اضغط الجهاز لتفاصيله</span><button class="button small plant-zoom-button" data-action="plant-zoom" aria-pressed="${Boolean(ui.zoom)}">${ui.zoom?'عرض المسار كاملًا':'تكبير المخطط'}</button></div></div><div class="plant-diagram-scroll" data-plant-region="diagram">${r.diagram}</div><div class="plant-equipment-tabs" aria-label="تفاصيل معدات المنشأة">${Object.entries(EQUIPMENT).map(([id,e])=>`<button type="button" data-equipment="${id}" aria-pressed="${ui.equipment===id}">${e.name}</button>`).join('')}</div><div data-plant-region="reasons">${r.reasons}</div>
    <div class="plant-controls">${select('plant-mode','وضع التشغيل',PLANT_MODES,v.mode)}${select('plant-fault','سيناريو الاختبار',PLANT_FAULTS,v.fault)}<div class="plant-speed"><span>سرعة المحاكاة</span><div>${[1,10,30].map(speed=>`<button type="button" data-action="plant-speed" data-plant-control data-speed="${speed}" aria-pressed="${v.speed===speed}" ${disabled||!v.active?'disabled':''}><bdi>×${speed}</bdi></button>`).join('')}</div></div><button class="button small" data-action="plant-running" data-plant-control ${disabled||!v.active?'disabled':''}>${icon(v.running?'pause':'play')}${v.running?'إيقاف المحاكاة مؤقتًا':'متابعة المحاكاة'}</button><a class="plant-lab-link" href="#model">${icon('brain')}مختبر الذكاء ${icon('arrow')}</a></div></section>
    <div class="plant-bottom"><section class="plant-events-panel"><div class="plant-process-heading"><div><span class="plant-section-code">OPERATION LOG</span><h2>أحداث التشغيل</h2></div><a class="text-button" href="#alerts">التنبيهات ${icon('arrow')}</a></div><div data-plant-region="events">${r.events}</div></section><section class="plant-detail-panel" data-plant-region="detail" aria-live="polite">${r.detail}</section></div><p class="plant-footnote">${icon('shield')}حماية التوأم بقواعد تشغيل، والنموذج البحثي في مختبر الذكاء.</p></div>`;
}
// Keep the operator's focus and native select menus while read-only polling
// updates measured values. Only simulation-derived regions are replaced.
export function updatePlant(container,data,ui,disabled=false) {
  const v=plantView(data), screen=container.querySelector('#plant-screen');
  if(!screen || screen.dataset.session!==(v.sessionId||'')) {container.innerHTML=plantPage(data,ui,disabled);return;}
  screen.classList?.toggle('plant-zoomed',Boolean(ui.zoom));
  const zoom=container.querySelector('[data-action="plant-zoom"]');
  if(zoom) {zoom.textContent=ui.zoom?'عرض المسار كاملًا':'تكبير المخطط';zoom.setAttribute('aria-pressed',String(Boolean(ui.zoom)));}
  for(const button of container.querySelectorAll('.plant-equipment-tabs [data-equipment]')) button.setAttribute('aria-pressed',String(button.dataset.equipment===ui.equipment));
  const r=plantRegions(data,ui);
  const focusedEquipment=document.activeElement?.dataset?.equipment;
  for(const [key,html] of Object.entries(r)) {
    const node=container.querySelector(`[data-plant-region="${key}"]`);
    if(node && node.plantMarkup!==html) {node.innerHTML=html;node.plantMarkup=html;}
  }
  if(Object.hasOwn(EQUIPMENT,focusedEquipment)) container.querySelector(`[data-equipment="${focusedEquipment}"]`)?.focus({preventScroll:true});
  for(const [id,key] of [['plant-mode','mode'],['plant-fault','fault']]) {
    const input=container.querySelector(`#${id}`);
    if(input) {if(input!==document.activeElement) input.value=v[key]??'';input.disabled=disabled||!v.active;}
  }
  for(const button of container.querySelectorAll('[data-action="plant-speed"]')) {
    button.disabled=disabled||!v.active;button.setAttribute('aria-pressed',String(v.speed===Number(button.dataset.speed)));
  }
  const running=container.querySelector('[data-action="plant-running"]');
  if(running) {running.disabled=disabled||!v.active;running.innerHTML=`${icon(v.running?'pause':'play')}${v.running?'إيقاف المحاكاة مؤقتًا':'متابعة المحاكاة'}`;}
}
