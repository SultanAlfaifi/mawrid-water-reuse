import { unitSpec } from './unitSpec.js';

const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const circled = ['①','②','③','④','⑤','⑥','⑦','⑧','⑨','⑩','⑪','⑫','⑬','⑭','⑮'];
const modeLabels = {normal:'تشغيل عادي',backwash:'غسيل عكسي',fault:'تحويل عند خلل',poweroff:'انقطاع الكهرباء'};

function textValue(value) {
  if (value == null) return '—';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(textValue).join(' × ');
  return Object.entries(value).map(([key, item]) => `${key}: ${textValue(item)}`).join(' · ');
}

export function mountUI({state, getComponents, onChange, onCamera, onExport, onCSV, onSelect}) {
  let current = {...state};
  let tableSignature = '';
  let selectedCamera = 'overview';
  let exportBusy = false;
  const root = document.getElementById('app');
  const shell = document.querySelector('.viewer-shell');
  const card = document.getElementById('component-card');
  const tablePanel = document.getElementById('component-table-panel');
  const tableBody = document.getElementById('component-table-body');
  const status = document.getElementById('status-text');
  const exportToggle = document.getElementById('export-toggle');
  const exportMenu = document.getElementById('export-menu');
  const listComponents = () => {const result = getComponents?.() || []; return Array.isArray(result) ? result : Object.values(result);};
  const componentId = (component, index) => component.id ?? component.number ?? index + 1;
  const componentNumber = (component, index) => component.number ?? component.id ?? index + 1;
  const componentSize = component => textValue(component.dimensions ?? component.size ?? component.dimensionLabel ?? component.measurements);
  const findComponent = id => listComponents().find((c,i) => String(componentId(c,i)) === String(id));
  const patch = update => { current = {...current,...update}; sync(current); onChange?.(update); };
  const select = id => { current.selected = id; showComponent(id == null ? null : findComponent(id)); onSelect?.(id); };

  root.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => patch({preset:button.dataset.preset})));
  root.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => patch({mode:button.dataset.mode})));
  root.querySelectorAll('[data-environment]').forEach(button => button.addEventListener('click', () => patch({environment:button.dataset.environment})));
  root.querySelectorAll('[data-toggle]').forEach(button => button.addEventListener('click', () => patch({[button.dataset.toggle]:!current[button.dataset.toggle]})));
  root.querySelectorAll('[data-camera]').forEach(button => button.addEventListener('click', () => { selectedCamera = button.dataset.camera; syncCamera(); onCamera?.(selectedCamera); }));
  document.getElementById('quality-select').addEventListener('change', event => patch({quality:event.target.value}));
  document.getElementById('table-close').addEventListener('click', () => patch({labels:false}));
  document.getElementById('csv-button').addEventListener('click', () => onCSV?.());
  exportToggle.addEventListener('click', () => {const open = exportMenu.hidden; exportMenu.hidden = !open; exportToggle.setAttribute('aria-expanded',String(open));});
  document.addEventListener('click', event => {if(!event.target.closest('.export-control')) {exportMenu.hidden = true;exportToggle.setAttribute('aria-expanded','false');}});
  document.addEventListener('keydown', event => {if(event.key === 'Escape'){exportMenu.hidden=true;exportToggle.setAttribute('aria-expanded','false');if(!card.hidden)select(null);}});
  root.querySelectorAll('[data-export]').forEach(button => button.addEventListener('click', async () => {
    if(exportBusy) return;
    exportBusy = true; exportMenu.hidden = true; exportToggle.disabled = true;
    exportToggle.setAttribute('aria-expanded','false'); setStatus('تجهيز صورة 4K…');
    try {await onExport?.(button.dataset.export); setStatus('تم تجهيز الصورة');}
    catch(error) {setStatus('تعذّر التصدير؛ جرّب جودة اقتصادية'); console.error(error);}
    finally {exportBusy=false; exportToggle.disabled=false;}
  }));
  tableBody.addEventListener('click', event => {const row=event.target.closest('[data-component]'); if(row){const item=findComponent(row.dataset.component);select(item ? componentId(item,listComponents().indexOf(item)) : row.dataset.component);}});
  tableBody.addEventListener('keydown', event => {if(event.key==='Enter'||event.key===' '){const row=event.target.closest('[data-component]');if(row){event.preventDefault();row.click();}}});
  card.addEventListener('click', event => {if(event.target.closest('[data-close-card]'))select(null);});

  function syncCamera() { root.querySelectorAll('[data-camera]').forEach(button => {const active=button.dataset.camera===selectedCamera;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));}); }
  function renderTable() {
    const components=listComponents();
    const signature=JSON.stringify(components.map((item,i)=>[componentId(item,i),item.name,item.code,item.function??item.description??item.purpose,componentSize(item)]));
    if(signature!==tableSignature){
      tableSignature=signature;
      tableBody.innerHTML=components.map((item,index)=>`<tr data-component="${escapeHTML(componentId(item,index))}" tabindex="0" role="button" aria-label="${escapeHTML(item.name)}"><td>${escapeHTML(componentNumber(item,index))}</td><td><strong>${escapeHTML(item.name)}</strong><code dir="ltr">${escapeHTML(item.code||'')}</code><small class="table-function">${escapeHTML(textValue(item.function??item.description??item.purpose??''))}</small></td><td>${escapeHTML(componentSize(item))}</td></tr>`).join('');
    }
    tableBody.querySelectorAll('[data-component]').forEach(row=>row.classList.toggle('is-selected',String(row.dataset.component)===String(current.selected)));
  }
  function showComponent(component) {
    if(!component) {card.hidden=true;return;}
    const index=listComponents().indexOf(component);
    const number=componentNumber(component,index<0?0:index);
    const description=component.function??component.description??component.purpose??'';
    const sensor=component.sensor??component.sensors??component.relatedSensor??'لا يوجد حساس مباشر';
    const safety=String(component.code||'').includes('V-601')||Number(number)===10;
    card.innerHTML=`<div class="card-top"><span class="component-number">${escapeHTML(circled[Number(number)-1]||number)}</span><div class="card-title-wrap"><h3>${escapeHTML(component.name)}</h3><code dir="ltr">${escapeHTML(component.code||'')}</code></div><button type="button" class="card-close" data-close-card aria-label="إغلاق بطاقة المكوّن">×</button></div><div class="card-body"><p>${escapeHTML(textValue(description))}</p><div class="card-field"><span>المقاس</span><strong>${escapeHTML(componentSize(component))}</strong></div><div class="card-field"><span>الحساس</span><strong>${escapeHTML(textValue(sensor))}</strong></div>${safety?'<div class="card-safety">V-601 يعود مغلقًا بالنابض عند أي خلل أو انقطاع كهرباء.</div>':''}</div>`;
    card.hidden=false;
    renderTable();
  }
  function sync(nextState) {
    current={...current,...nextState};
    root.querySelectorAll('[data-preset]').forEach(button=>{const active=button.dataset.preset===current.preset;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
    root.querySelectorAll('[data-mode]').forEach(button=>{const active=button.dataset.mode===current.mode;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
    root.querySelectorAll('[data-environment]').forEach(button=>{const active=button.dataset.environment===current.environment;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
    root.querySelectorAll('[data-toggle]').forEach(button=>button.setAttribute('aria-pressed',String(Boolean(current[button.dataset.toggle]))));
    for(const mode of Object.keys(modeLabels))shell.classList.toggle(`is-${mode}`,current.mode===mode);
    shell.classList.toggle('is-labels',Boolean(current.labels));shell.classList.toggle('is-site',current.environment==='site');
    document.getElementById('viewer-preset').textContent=current.preset;
    document.getElementById('capacity-display').textContent=`${String(current.preset).replace(/[^\d]/g,'')} م³/يوم`;
    document.getElementById('quality-select').value=current.quality||'auto';
    document.getElementById('process-destination').innerHTML=`<span>08</span>${current.mode==='backwash'?'صرف الغسيل':current.mode==='fault'?'إعادة معالجة':current.mode==='poweroff'?'توقف آمن':'ري'}`;
    const modeText=modeLabels[current.mode]||'تصور هندسي تفاعلي';
    status.textContent=modeText;status.title=current.mode==='fault'?'احتجاز: عكارة نهائية خارج الحد — محاكاة توضيحية':modeText;
    tablePanel.hidden=!current.labels;
    renderTable();syncCamera();
    if(current.selected != null)showComponent(findComponent(current.selected));else card.hidden=true;
  }
  function setStatus(text) {status.textContent=text;status.title=text;}
  function setLoading(visible) {document.getElementById('viewer-loading').hidden=!visible;}
  function setPerformance(fps,quality) {const indicator=document.getElementById('performance-indicator');indicator.textContent=fps===0?'عرض عند الطلب · موفّر للطاقة':`${Math.round(fps)} FPS${quality ? ` · ${quality==='high'?'عالية':quality==='mobile'?'اقتصادية':quality}`:''}`;indicator.dir='ltr';}
  document.getElementById('constraints-list').innerHTML=unitSpec.constraints.map(item=>`<li>${escapeHTML(item)}</li>`).join('');
  document.getElementById('human-scale-label').textContent=`${unitSpec.human.height} م`;
  sync(current);
  return {sync,showComponent,setStatus,setLoading,setPerformance};
}
