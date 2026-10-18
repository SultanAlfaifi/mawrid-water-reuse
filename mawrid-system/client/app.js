import { api, safeLink } from './api.js';
import { sensorChart } from './charts.js';
import { plantView, plantPage, updatePlant, EQUIPMENT, PLANT_MODES, PLANT_FAULTS } from './plant.js';
import { GUIDE_PAGES, renderGuide, updateTour, updateComponent } from './guide.js';
import { experienceState } from './experience-state.js';
import { journeyProgress } from './water-journey.js';
import { JourneyPresentation } from './presentation.js';

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const finite = value => typeof value === 'number' && Number.isFinite(value);
const num = (value, digits = 2) => finite(value) ? new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value) : '—';
const ltr = value => `<span class="ltr">${esc(value)}</span>`;
const dateText = value => value ? String(value).replace('T', ' ').replace(/\.\d+(?=Z|[+-]\d\d:|$)/, '').replace(/Z$/, ' UTC') : '—';
const timeText = value => value ? String(value).replace('T', ' ').slice(11, 19) || value : '—';
const pill = (text, tone = '', dot = true) => `<span class="status-pill ${tone}">${dot ? '<span class="dot"></span>' : ''}${esc(text)}</span>`;
const empty = (title, description, name = 'wave', action = '', compact = false) => `<div class="empty-state ${compact ? 'compact' : ''}"><span class="empty-icon">${icon(name)}</span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
const startButton = '<button class="button primary" data-action="new-session">بدء جلسة جديدة '+icon('arrow')+'</button>';
const pages = {
  start: ['تعرّف على مورد', 'الماء يعود نافعًا', 'افهم الفكرة، جرّب المحطة، وتابع ما يحدث.'],
  components: ['رحلة الماء وأجزاء المحطة', 'كل جزء، ولماذا نحتاجه', 'دليل مبسّط للمكونات، مع تفاصيل إضافية لمن يريد.'],
  technology: ['البرمجة والذكاء والأدلة', 'شفافية يمكن فهمها', 'كيف يعمل النظام، ما الذي اختبرناه، وما حدود هذه النسخة.'],
  follow: ['المتابعة والسجل', 'الحالة، ثم السبب، ثم الإجراء', 'اعرف ما يحدث الآن وراجع أثر التجربة.'],
  engineering: ['مخطط التشغيل التفصيلي', 'عرض هندسي إضافي', 'المخطط المبسّط الأصلي؛ المرجع المكاني الأحدث في تجربة المحطة.'],
  plant: ['جرّب المحطة', 'محاكاة تفاعلية / وحدة مورد', 'ابدأ التشغيل، جرّب سيناريو، وافهم سبب القرار.'],
  overview: ['نظرة عامة', 'الماء، بوضوح أكثر', 'تابع القراءات، وافهم التنبيه، وراجع ما حدث.'],
  measurements: ['القياسات', 'من المصدر إلى الشاشة', 'قراءات فعلية من المصدر المحدد، مع الحفاظ على القيم المفقودة.'],
  alerts: ['التنبيهات', 'افهم سبب الإشارة', 'راجع التنبيه وسياقه، ثم سجّل اطلاعك عليه.'],
  history: ['السجل والتصدير', 'أثر يمكن مراجعته', 'كل قراءة مرتبطة بمصدرها وجلستها وقرار البرنامج.'],
  model: ['مختبر الذكاء', 'الدليل قبل الادعاء', 'النموذج البحثي على بياناته العامة، وحدود تأهيله.'],
  settings: ['الإعدادات', 'ضبط مساحة العمل', 'حدود تجريبية للقواعد المحلية؛ لا تعدّل نموذج الذكاء الاصطناعي.'],
};
const state = {
  data: null, sources: [], page: 'start', connected: false, fetching: false, mutation: null,
  guideUi: {tourStep:0,component:'source'},
  plantUi: { equipment: 'collection', zoom: false, previousLevels: {}, reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true },
  stateGeneration: 0, historyRequest: 0, historyKey: null, alarmsRequest: 0,
  autoplay: false, timer: null, batch: 10, channel: null,
  readings: [], historyLoaded: false, historyError: '', historyScope: 'all', historyLimit: 100,
  alarms: [], alarmsLoaded: false, alarmsError: '', alarmFilter: 'all',
  settingsRendered: false, toastTimer: null,
};

function connection(connected, error) {
  state.connected = connected;
  $('#connection-badge').className = `connection-badge ${connected ? 'connected' : 'disconnected'}`;
  $('#connection-badge').innerHTML = `<span class="dot"></span><span>${connected ? 'الخدمة المحلية متصلة' : 'الخدمة غير متصلة'}</span>`;
  $('#connection-error').hidden = connected;
  if (error) $('#connection-error-detail').textContent = error.message;
}
function toast(message, error = false) {
  clearTimeout(state.toastTimer); const node = $('#toast'); node.textContent = message;
  node.className = `toast${error ? ' error' : ''}`; node.hidden = false;
  state.toastTimer = setTimeout(() => { node.hidden = true; }, error ? 8500 : 4500);
}
function applyState(data) {
  if (!data || !data.app || !data.overview || !Array.isArray(data.series)) throw new Error('بنية الحالة غير صالحة. لا توجد بيانات بديلة للعرض.');
  const previousPlant = plantView(state.data), nextPlant = plantView(data);
  state.plantUi.previousLevels = previousPlant.active && previousPlant.sessionId === nextPlant.sessionId
    ? { collection: previousPlant.tanks?.collection?.level_pct, treated: previousPlant.tanks?.treated?.level_pct } : {};
  state.data = data; connection(true);
  // A full state carries newer alarms than any previously loaded list. Show
  // that snapshot immediately; a fresh list request can expand it to 100.
  state.alarmsRequest++; state.alarmsLoaded = false; state.alarmsError = '';
  if (state.historyKey !== null && state.historyKey !== historySelectionKey()) {
    state.historyRequest++; state.readings = []; state.historyLoaded = false; state.historyError = '';
  }
  $('#site-label').textContent = data.settings?.site_name || 'مساحة التشغيل المحلية';
  $('#research-context').textContent = data.source?.kind === 'telemetry'
    ? 'استقبال قراءات عبر API. النموذج غير مؤهل لهذا المخطط، ولا اتصال بصمام فعلي.'
    : data.source?.kind === 'digital_twin' ? 'قراءات المنشأة الافتراضية من محرك التوأم الرقمي. النموذج البحثي متاح في مختبر الذكاء على مصادره العامة.'
    : 'مصادر تاريخية معلنة. لا حساسات ميدانية متصلة، ولا حكم على صلاحية المياه.';
  if (data.source?.kind !== 'public_replay' || data.session?.status === 'completed' || data.session?.status === 'failed') stopAutoplay();
  $('#nav-alert-count').textContent = num(data.overview.unacknowledged_alarms, 0);
  const viewer = safeLink(data.links?.viewer);
  $('#viewer-link').href = '/plant3d/index.html'; $('#viewer-link').removeAttribute('target');
  $('#last-updated').textContent = `آخر اتصال بالخدمة: ${new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
  $('#page-content').setAttribute('aria-busy', 'false'); render();
}
async function refresh({ all = false } = {}) {
  if (state.fetching || state.mutation) return;
  const generation = state.stateGeneration;
  state.fetching = true; $('#refresh-button').disabled = true;
  try {
    const data = await api.state();
    if (generation !== state.stateGeneration) return;
    applyState(data);
    if (!state.sources.length) {
      const result = await api.sources();
      if (generation !== state.stateGeneration) return;
      if (!Array.isArray(result.sources)) throw new Error('تعذّر قراءة قائمة المصادر من الخدمة.');
      state.sources = result.sources;
    }
    if ((all || state.historyKey !== historySelectionKey()) && state.page === 'history') await loadHistory();
    if (state.page === 'alerts') await loadAlarms();
  } catch (error) {
    if (generation !== state.stateGeneration) return;
    stopAutoplay(); connection(false, error); render();
  } finally { state.fetching = false; $('#refresh-button').disabled = false; }
}
function mutationUI() {
  document.querySelectorAll('[data-auto-start]').forEach(node=>{node.disabled||=presentationStarting||Boolean(state.mutation);});
  const busy=$('#experience-busy');if(busy)busy.hidden=!state.mutation;
  document.querySelectorAll('[data-mutation]').forEach(node => { node.disabled = Boolean(state.mutation) || !state.connected; });
  document.querySelectorAll('[data-plant-control]').forEach(node => { node.disabled = Boolean(state.mutation) || !state.connected || !plantView(state.data).active; });
  $('#new-session-button').disabled = Boolean(state.mutation) || !state.connected;
  $('#session-submit').disabled = Boolean(state.mutation) || !state.connected || !$('#research-ack')?.checked;
  if (state.mutation) $('#page-content').setAttribute('aria-busy', 'true');
  else $('#page-content').setAttribute('aria-busy', 'false');
}
async function mutate(task) {
  if (state.mutation) throw new Error('انتظر اكتمال العملية الحالية.');
  const focusedControl=document.activeElement;
  // Invalidate GETs started before this write, even if their response arrives
  // after the write has finished or failed. They cannot establish newer state.
  state.stateGeneration++;
  const operation = (async () => {
    try { const result = await task(); applyState(result); $('#guide-scene')?.contentWindow?.postMessage({type:'mawrid:refresh'},location.origin); return result; }
    catch (error) {
      stopAutoplay();
      if (!error.status || error.code === 'timeout') connection(false, error);
      throw error;
    }
  })();
  state.mutation = operation; mutationUI();
  try { return await operation; }
  finally { state.mutation = null; mutationUI(); render();
    if(focusedControl?.isConnected&&document.activeElement===document.body)focusedControl.focus({preventScroll:true});
  }
}
function stopAutoplay() { state.autoplay = false; clearTimeout(state.timer); state.timer = null; }
async function pause() {
  stopAutoplay(); render();
  try {
    if (state.mutation) await state.mutation;
    if (state.data?.session?.id && state.data.source?.kind === 'public_replay') await mutate(() => api.pause());
  } catch (error) { toast(error.message, true); }
}
async function play() {
  if (state.autoplay || state.mutation || !state.connected) return;
  if (!canReplay()) return;
  state.autoplay = true; render();
  async function tick() {
    if (!state.autoplay || !canReplay()) { stopAutoplay(); render(); return; }
    try { await mutate(() => api.step(state.batch)); }
    catch (error) { toast(error.message, true); return; }
    if (state.autoplay && canReplay()) state.timer = setTimeout(tick, 1000);
    else { stopAutoplay(); render(); }
  }
  await tick();
}
function canReplay() {
  const s = state.data?.session;
  return state.data?.source?.kind === 'public_replay' && s?.id && !['completed', 'failed', 'idle'].includes(s.status) && s.position < s.total;
}
function channels() {
  const source = state.data?.source;
  return source?.channels?.length ? source.channels : state.sources.find(s => s.id === source?.id)?.channels || [];
}
function series() { return [...(state.data?.series || [])].sort((a, b) => a.id - b.id).slice(-60); }
function predictionText(row) {
  if (!row) return { text: 'بانتظار قراءة', tone: 'neutral' };
  if (row.prediction === 1) return { text: 'إشارة شذوذ', tone: 'danger' };
  if (row.prediction === 0) return { text: 'لم يُكتشف شذوذ', tone: 'good' };
  return { text: row.ignored_gap ? 'تهيئة القراءة' : 'الذكاء غير متاح', tone: 'neutral' };
}
function sessionBanner() {
  const data = state.data, s = data?.session;
  if (!s?.id) return '';
  if (data.source?.kind === 'digital_twin') return `<section class="session-banner"><span class="session-icon">${icon('box')}</span><div class="session-details"><strong>توأم رقمي · منشأة افتراضية</strong><small>قراءات محاكاة من غرفة التشغيل، دون تشغيل نموذج على هذا المصدر.</small></div><a class="button small" href="#plant">غرفة التشغيل ${icon('arrow')}</a></section>`;
  if (!['telemetry', 'public_replay'].includes(data.source?.kind)) return '';
  const telemetry = data.source?.kind === 'telemetry';
  const labels = { idle: 'غير مبدوءة', ready: state.autoplay ? 'تشغيل إعادة العرض' : 'جاهزة للقراءة', paused: 'متوقفة مؤقتًا', completed: 'اكتملت البيانات', failed: 'توقفت بخطأ' };
  const progress = finite(s.total) && s.total > 0 ? Math.max(0, Math.min(100, (s.position / s.total) * 100)) : 0;
  return `<section class="session-banner ${s.status === 'completed' ? 'session-ended' : ''}" aria-label="الجلسة الحالية"><span class="session-icon">${icon(telemetry ? 'server' : 'wave')}</span><div class="session-details"><strong>${esc(data.source?.name || 'الجلسة الحالية')} ${pill(telemetry ? 'استقبال API' : labels[s.status] || s.status, s.status === 'failed' ? 'danger' : 'good')}</strong><small>${telemetry ? 'بيانات مرسلة عبر API؛ لا يدعم النموذج البحثي هذا المخطط.' : `أعيد عرض ${num(s.position, 0)} من ${num(s.total, 0)} قراءة · فاصل المصدر ${num(s.sample_seconds, 0)} ثانية`}</small>${!telemetry ? `<div class="session-progress" role="progressbar" aria-label="تقدم إعادة العرض" aria-valuenow="${progress.toFixed(1)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${progress}%"></span></div>` : ''}</div><div class="session-controls">${telemetry ? '<button class="button small" data-action="telemetry-help">طريقة إرسال القراءات</button>' : `<label class="sr-only" for="batch-size">عدد القراءات في كل دفعة</label><select class="field-select" id="batch-size" aria-label="عدد القراءات في كل دفعة" ${state.autoplay ? 'disabled' : ''}>${[1, 5, 10, 25].map(n => `<option value="${n}" ${state.batch === n ? 'selected' : ''}>${n} ${n === 1 ? 'قراءة' : 'قراءات'} / دفعة</option>`).join('')}</select><button class="button small" data-action="step" data-mutation ${!canReplay() || state.autoplay ? 'disabled' : ''}>${icon('step')}قراءة واحدة</button><button class="button small primary" data-action="${state.autoplay ? 'pause' : 'play'}" ${!canReplay() && !state.autoplay ? 'disabled' : ''}>${icon(state.autoplay ? 'pause' : 'play')}${state.autoplay ? 'إيقاف مؤقت' : 'تشغيل'}</button>`}</div></section>`;
}
function statCard(title, value, note, name, small = false) {
  return `<article class="stat-card"><div class="stat-top"><span>${esc(title)}</span><span class="stat-icon">${icon(name)}</span></div><div class="stat-value ${small ? 'small-value' : ''}">${esc(value)}</div><div class="stat-note">${esc(note)}</div></article>`;
}
function stats() {
  const d = state.data, latest = d?.latest, pred = predictionText(latest);
  return `<div class="stats-grid">${statCard('القراءات في الجلسة', num(d?.overview?.readings, 0), 'من المصدر المختار، كما حُفظت', 'wave')}${statCard('تنبيهات تحتاج مراجعة', num(d?.overview?.unacknowledged_alarms, 0), 'المراجعة توثّق الاطلاع ولا تلغي السبب', 'bell')}${statCard('آخر إشارة للنموذج', pred.text, 'ليست حكمًا على سلامة المياه', 'brain', true)}${statCard('صمام البرنامج', d ? 'مغلق' : '—', 'حالة برمجية فقط · لا جهاز متصل', 'shield', true)}</div>`;
}
function chartPanel() {
  const available = channels(), rows = series();
  if (!available.some(c => c.key === state.channel)) state.channel = available[0]?.key || null;
  const channel = available.find(c => c.key === state.channel);
  const chart = channel ? sensorChart(rows, channel) : null;
  return `<section class="panel"><div class="panel-heading"><div><h2>مسار القراءات</h2><p>آخر ${rows.length || '—'} قراءة محفوظة · ساعة المصدر الأصلية</p></div>${available.length ? `<div class="chart-controls"><select class="field-select" id="chart-channel" aria-label="الحساس المعروض في الرسم">${available.map(c => `<option value="${esc(c.key)}" ${c.key === state.channel ? 'selected' : ''}>${esc(c.name)}${c.unit ? ' · '+esc(c.unit) : ''}</option>`).join('')}</select></div>` : ''}</div>${chart?.svg ? `<div class="chart-area">${chart.svg}</div><div class="chart-summary"><span>أقل قراءة<strong>${ltr(num(chart.min, 4))}</strong></span><span>أعلى قراءة<strong>${ltr(num(chart.max, 4))}</strong></span><span>الوحدة<strong>${esc(channel.unit || 'غير محددة')}</strong></span></div><div class="chart-legend"><span><i class="legend-dot"></i>قياس المصدر</span><span><i class="legend-dot alert"></i>إشارة شذوذ من النموذج</span></div>${chart.missingCount ? `<div class="chart-missing">${chart.missingCount} قراءة مفقودة؛ يظهر انقطاع في الخط دون تعويضها.</div>` : ''}` : empty('لم تصل قراءات للرسم بعد', state.data?.session?.id ? 'شغّل إعادة العرض، أو أرسل قراءة إلى جلسة API الحالية.' : 'ابدأ جلسة من مصدر متاح لعرض المسار الفعلي.', 'wave', '', true)}</section>`;
}
function sensorCards() {
  const available = channels(), latest = state.data?.latest;
  if (!available.length) return empty('لا مصدر محدد', 'ستظهر الحساسات ووحداتها بعد بدء الجلسة.', 'droplet', '', true);
  return `<div class="sensor-grid">${available.map(c => {
    const value = latest?.channels?.[c.key], missing = !finite(value);
    return `<article class="sensor-card ${missing ? 'missing' : ''}"><div class="sensor-name"><span>${esc(c.name)}</span><span class="sensor-code">${esc(c.key)}</span></div><div class="sensor-value"><strong>${num(value, 4)}</strong><small>${esc(c.unit || '')}</small></div><div class="sensor-foot">${!latest ? 'بانتظار أول قراءة' : missing ? 'القيمة مفقودة في قراءة المصدر' : 'قيمة المصدر الأصلية · '+esc(timeText(latest.timestamp))}</div></article>`;
  }).join('')}</div>`;
}
function decisionPanel() {
  const d = state.data, row = d?.latest, pred = predictionText(row);
  return `<section class="panel"><div class="panel-heading"><h2>إشارة النموذج والقرار</h2>${pill(d?.model?.version || 'غير محمّل', 'neutral', false)}</div><div class="decision-box ${pred.tone === 'danger' ? 'danger' : ''}"><span class="decision-symbol">${icon(row?.prediction === 1 ? 'bell' : 'shield')}</span><div><h3>${esc(pred.text)}</h3><p>${!row ? 'تظهر الإشارة بعد قراءة البيانات وتهيئة السياق.' : row.prediction === 1 ? 'يستدعي اختلاف القراءة أو نمطها المراجعة؛ لا يحدد نوع العطل.' : row.prediction === 0 ? 'لم يرفع النموذج إشارة لهذه القراءة. لا يعني هذا أن المياه آمنة.' : row.ignored_gap ? 'هذه القراءة ضمن الجزء المستبعد قبل التهيئة.' : 'السياق غير كافٍ أو المخطط غير مؤهل لهذا النموذج.'}</p></div></div><ul class="decision-list"><li><span>درجة ترتيب الشذوذ</span><strong>${ltr(num(row?.score, 5))}</strong></li><li><span>القرار البرمجي</span><strong>${esc(d?.overview?.decision || 'بانتظار بيانات')}</strong></li><li><span>حالة صمام البرنامج</span><strong>${d ? 'مغلق — دون عتاد' : 'غير متاحة'}</strong></li><li><span>لترات ري مقاسة</span><strong>${finite(d?.overview?.measured_irrigation_liters) ? num(d.overview.measured_irrigation_liters)+' لتر' : 'غير مقاسة'}</strong></li></ul>${d?.overview?.reasons?.length ? `<ul class="reason-notes">${d.overview.reasons.map(reason => `<li>${esc(reason)}</li>`).join('')}</ul>` : ''}<div class="panel-footer">الدرجة ليست احتمال سلامة ولا «ثقة حساس». الذكاء لا يفتح صمامًا.</div></section>`;
}
function alertPreview() {
  const alerts = state.data?.alarms?.slice(0, 4) || [];
  return `<section class="panel"><div class="panel-heading"><div><h2>آخر التنبيهات</h2><p>السبب قبل الإجراء</p></div><a class="text-button" href="#alerts">عرض الكل ${icon('arrow')}</a></div>${alerts.length ? `<div style="padding-block:10px">${alerts.map(a => `<div class="recent-event"><span class="event-indicator ${a.severity === 'critical' ? 'danger' : a.severity === 'warning' ? 'warning' : ''}"></span><div class="event-copy"><strong>${esc(a.title)}</strong><p>${esc(a.detail)}</p></div><time title="${esc(dateText(a.timestamp))}">${esc(timeText(a.timestamp))}</time></div>`).join('')}</div>` : empty('لا تنبيهات مسجلة للعرض', state.data?.session?.id ? 'ستظهر إشارات النموذج أو القواعد هنا عند وصولها.' : 'ابدأ جلسة أولًا. عدم وجود تنبيه لا يثبت سلامة المياه.', 'bell', '', true)}</section>`;
}
function overview() {
  const noSession = !state.data?.session?.id;
  return `${sessionBanner()}${stats()}<div class="dashboard-grid">${noSession ? `<section class="panel start-panel"><div><span class="eyebrow">ابدأ من بيانات تعرف مصدرها</span><h2>قراءة أوضح.<br>قرار يمكن مراجعته.</h2><p>أعد عرض بيانات GECCO أو WaterHub التاريخية، وشاهد استدلال النموذج الحقيقي وسجل كل إشارة.</p>${startButton}</div><span class="start-mark">${icon('droplet')}</span></section>` : chartPanel()}${decisionPanel()}<section class="panel"><div class="panel-heading"><div><h2>الحساسات</h2><p>${esc(state.data?.source?.name || 'القيم غير متاحة حتى اختيار المصدر')}</p></div><a class="text-button" href="#measurements">كل القياسات ${icon('arrow')}</a></div>${sensorCards()}</section>${alertPreview()}<section class="panel full-width"><div class="panel-heading"><h2>من القراءة إلى سجل قابل للمراجعة</h2>${pill('مسار البرنامج', 'neutral', false)}</div><div class="process-track">${[['server','مصدر معلن','تاريخي أو API'],['wave','قراءة أصلية','دون ملء القيم'],['brain','تحليل بحثي','عند توفر السياق'],['shield','قرار محجوز','لا فتح فعلي'],['list','سجل وتصدير','مع مصدر القراءة']].map(([i,t,s]) => `<div class="process-node"><span>${icon(i)}</span><div>${t}<small>${s}</small></div></div>`).join('')}</div></section></div>`;
}
function measurements() {
  return `${sessionBanner()}<section class="panel"><div class="panel-heading"><div><h2>آخر قياس لكل قناة</h2><p>${state.data?.latest ? 'وقت المصدر: '+esc(dateText(state.data.latest.timestamp)) : 'بانتظار قراءة من المصدر المختار'}</p></div>${pill(state.data?.source?.kind === 'telemetry' ? 'API · دون تأهيل ML' : state.data?.source?.kind === 'digital_twin' ? 'قراءات المنشأة الافتراضية' : 'إعادة عرض تاريخية', 'neutral')}</div>${sensorCards()}</section><div class="dashboard-grid">${chartPanel()}${decisionPanel()}</div><div class="info-callout section-spacer">${icon('info')}<p>الضغط والموصلية والعكارة قنوات مختلفة بوحداتها الأصلية. لا نستنتج الكلور من ORP أو من قناة أخرى، ولا نحول قيمة مفقودة إلى صفر.</p></div>`;
}
const alarmKinds = { anomaly: 'إشارة النموذج', missing: 'قراءة مفقودة', safety: 'قاعدة تجريبية', system: 'النظام' };
function alertsPage() {
  const all = state.alarmsLoaded ? state.alarms : state.data?.alarms || [];
  const rows = all.filter(a => state.alarmFilter === 'all' || (state.alarmFilter === 'open' ? !a.acknowledged_at : !!a.acknowledged_at));
  return `<section class="panel"><div class="toolbar"><div class="filter-chips" aria-label="تصفية التنبيهات">${[['all','الكل'],['open','لم تُراجع'],['reviewed','تمت مراجعتها']].map(([key,label]) => `<button class="filter-chip ${state.alarmFilter === key ? 'active' : ''}" data-filter="${key}" aria-pressed="${state.alarmFilter === key}">${label}</button>`).join('')}</div><span class="muted" style="font-size:10px">${all.length} تنبيه محمّل · حتى 100</span><div class="toolbar-end"><button class="button small" data-action="refresh-alarms">${icon('refresh')}تحديث</button><button class="button small" data-action="export-events">${icon('download')}تصدير جميع الأحداث</button></div></div>${state.alarmsError ? `<p class="form-error" style="margin:18px">${esc(state.alarmsError)}</p>` : ''}${rows.length ? `<div class="alert-list">${rows.map(a => `<article class="alert-card ${a.severity === 'critical' ? 'danger' : a.severity === 'warning' ? 'warning' : ''}"><span class="event-indicator ${a.severity === 'critical' ? 'danger' : 'warning'}"></span><div class="event-copy"><strong>${esc(a.title)}</strong><p>${esc(a.detail)}</p><div class="alert-meta"><span>${esc(alarmKinds[a.kind] || a.kind)}</span><time class="ltr">${esc(dateText(a.timestamp))}</time><span>رقم ${esc(a.id)}</span></div>${a.acknowledged_at ? `<p>تمت المراجعة: ${ltr(dateText(a.acknowledged_at))}</p>` : ''}</div>${a.acknowledged_at ? pill('تم الاطلاع', 'good') : `<button class="button small" data-action="ack" data-id="${esc(a.id)}" data-mutation>${icon('check')}تم الاطلاع</button>`}</article>`).join('')}</div>` : empty('لا تنبيهات ضمن هذا العرض', 'المراجعة تسجل اطلاعك فقط؛ لا تمسح الحدث ولا تؤكد زوال سببه.', 'bell')}<div class="panel-footer">المعروض من السجل الدائم عبر الجلسات. توجد كل الأحداث في ملف التصدير.</div></section>`;
}
function historyPage() {
  const rows = state.readings;
  return `<section class="panel"><div class="toolbar"><label class="field"><span class="sr-only">نطاق السجل</span><select id="history-scope" class="field-select"><option value="all" ${state.historyScope === 'all' ? 'selected' : ''}>كل الجلسات</option><option value="current" ${state.historyScope === 'current' ? 'selected' : ''} ${!state.data?.session?.id ? 'disabled' : ''}>الجلسة الحالية</option></select></label><label class="field"><span class="sr-only">عدد القراءات</span><select id="history-limit" class="field-select">${[100, 250, 1000].map(n => `<option value="${n}" ${n === state.historyLimit ? 'selected' : ''}>آخر ${n} قراءة</option>`).join('')}</select></label><div class="toolbar-end"><button class="button small" data-action="refresh-history">${icon('refresh')}تحديث</button><button class="button small" data-action="export-readings">${icon('download')}كل القراءات CSV</button><button class="button small" data-action="export-report">${icon('list')}ملخص JSON</button></div></div>${state.historyError ? `<p class="form-error" style="margin:18px">${esc(state.historyError)}</p>` : ''}${!state.historyLoaded && !state.historyError ? '<div class="loading-block"><div class="loading-line"></div>جارٍ قراءة السجل…</div>' : rows.length ? `<div class="table-scroll"><table><thead><tr><th>القراءة</th><th>وقت المصدر</th><th>المصدر / الجلسة</th><th>القنوات</th><th>إشارة النموذج</th><th>الدرجة</th><th>القرار والسبب</th></tr></thead><tbody>${rows.map(row => { const p = predictionText(row); return `<tr><td>${esc(row.id)}<small class="sensor-foot" style="display:block">#${esc(row.sample_index ?? '—')}</small></td><td class="time">${esc(dateText(row.timestamp))}</td><td>${ltr(row.source_id || '—')}<small class="sensor-foot" style="display:block">${ltr((row.session_id || '').slice(0, 8))}</small></td><td class="reason">${Object.entries(row.channels || {}).map(([key,value]) => `${ltr(key)}: ${ltr(num(value, 4))}`).join(' · ')}</td><td>${pill(p.text,p.tone)}</td><td>${ltr(num(row.score,5))}</td><td class="reason"><strong>${esc(row.decision || '—')}</strong><br>${esc((row.reasons || []).join(' · '))}</td></tr>`; }).join('')}</tbody></table></div><div class="pagination"><span>${rows.length} قراءة معروضة</span><span>ملف CSV يشمل كل السجل المحفوظ</span></div>` : empty('السجل فارغ', 'ستُحفظ القراءات الفعلية أثناء إعادة العرض أو استقبال API، دون حذف الجلسات السابقة.', 'list')}<div class="panel-footer">السجل يصف قراءات البرنامج، وليس شهادة امتثال أو تقرير توفير مياه. قد تختلف ساعة المصدر عن وقت الاستقبال.</div></section>`;
}
function modelPage() {
  const model = state.data?.model, metrics = model?.metrics || {}, report = safeLink(state.data?.links?.model_report);
  return `<section class="model-hero"><span class="model-icon">${icon('brain')}</span><div><h2>كشف الشذوذ · ${esc(model?.version || 'بانتظار الخدمة')}</h2><p>${esc(model?.message || 'ستظهر هوية النموذج وحدود تأهيله من الخدمة المحلية.')}</p></div>${pill(model?.status === 'unavailable' ? 'غير مؤهل للمصدر' : model?.status === 'not_loaded' ? 'غير محمّل' : 'بحثي فقط', 'neutral')}</section><div class="stats-grid section-spacer">${statCard('أحداث مكتشفة في التطوير', finite(metrics.events_detected) ? `${metrics.events_detected} من ${metrics.events_total}` : '—', 'مقياس الحدث؛ لا تمثله دقة القراءات', 'wave', true)}${statCard('مقاطع إنذار كاذب', num(metrics.false_alarm_fragments,0), 'على كامل فترات التطوير', 'bell')}${statCard('دقائق إنذار كاذب', num(metrics.false_alarm_minutes,0), 'مدة الإنذار، لا عدد المقاطع', 'clock')}${statCard('فترات الاختبار', num(metrics.periods,0), 'فترات زمنية معلنة ومستخدمة في التطوير', 'list')}</div><div class="dashboard-grid"><section class="panel"><div class="panel-heading"><h2>التأهيل وحدود التشغيل</h2></div><div class="panel-body"><dl class="definition-list"><div><dt>الإصدار المستخدم</dt><dd>${esc(model?.version || '—')}</dd></div><div><dt>القبول الإحصائي</dt><dd>${model ? model.acceptance_passed ? 'بحسب دليل الخدمة' : 'لم يجتز معيار القبول' : 'غير متاح'}</dd></div><div><dt>المصادر البحثية</dt><dd>GECCO · WaterHub</dd></div><div><dt>الحساسات الميدانية</dt><dd>لا توجد تجربة ميدانية مثبتة</dd></div><div><dt>فتح الصمام بالذكاء</dt><dd>غير متاح</dd></div><div><dt>إصدار تلقائي جديد</dt><dd>لا ترقية صامتة</dd></div></dl><div class="info-callout section-spacer">${icon('info')}<p>${esc(model?.qualification || 'لا معلومات تأهيل متاحة بعد.')}</p></div>${report ? `<a class="button section-spacer" href="${esc(report)}" target="_blank" rel="noopener">${icon('external')}افتح تقرير التقييم الكامل</a>` : ''}</div></section><section class="panel"><div class="panel-heading"><h2>ما تعنيه الإشارة</h2></div><div class="panel-body"><ul class="limit-list">${(model?.limitations || ['لا يمكن تقييم صلاحية الماء من إشارة النموذج وحدها.','لا توجد نتائج نموذج متاحة حتى تتصل الخدمة المحلية.']).map(text => `<li>${icon('shield')}<div>${esc(text)}</div></li>`).join('')}</ul></div></section></div><div class="info-callout warning section-spacer">${icon('info')}<p><strong>التطبيق قابل للتشغيل، والنموذج ما زال بحثيًا.</strong> نجاح استدعاء النموذج أو تطابق درجاته برمجيًا لا يثبت جودة مياه الوضوء، ولا تصنيف الأعطال الخمسة، ولا زمن الاستجابة على Raspberry Pi. التنبؤ بالطلب والمساعد العربي مرحلتان لاحقتان.</p></div>`;
}
const settingsFields = [
  ['turbidity_max','أعلى عكارة تجريبية','NTU','0.01',0,1000],
  ['ph_min','أقل pH تجريبي','pH','0.1',0,14],
  ['ph_max','أعلى pH تجريبي','pH','0.1',0,14],
  ['chlorine_min','أقل كلور متبقٍ تجريبي','mg/L','0.01',0,20],
  ['chlorine_max','أعلى كلور متبقٍ تجريبي','mg/L','0.01',0,20],
  ['stale_seconds','مهلة تقادم قراءة الجهاز','ثانية','1',1,86400],
];
// Only the server's session-scoped telemetry snapshot is durable evidence.
// POST ingestion acknowledgements may refer to a different pinned session.
function telemetryView(data) {
  const session = data?.session, telemetry = data?.telemetry;
  const eligible = data?.source?.kind === 'telemetry' &&
    typeof session?.id === 'string' && session.id.length > 0 &&
    ['ready', 'paused'].includes(session.status) && telemetry?.session_id === session.id;
  if (!eligible) return { eligible: false, sessionId: null, lastDeviceId: null, lastReceivedAt: null, receipt: null };
  const text = value => typeof value === 'string' && value.length > 0 ? value : null;
  const receipt = telemetry.last_receipt;
  return {
    eligible: true, sessionId: session.id,
    lastDeviceId: text(telemetry.last_device_id), lastReceivedAt: text(telemetry.last_received_at),
    receipt: receipt?.session_id === session.id && text(receipt.measurement_id) &&
      Number.isSafeInteger(receipt.reading_id) && receipt.reading_id > 0
      ? { measurementId: receipt.measurement_id, readingId: receipt.reading_id } : null,
  };
}
function telemetryCardContent() {
  const view = telemetryView(state.data);
  const status = !view.eligible ? 'لا جلسة API جاهزة' : view.lastReceivedAt ? 'وصلت قراءة' : 'بانتظار أول قراءة';
  return `<div class="panel-heading"><div><h2>ربط جامع القراءات</h2><p>اختبار الاستقبال البرمجي على هذا الجهاز</p></div>${pill(status, 'neutral')}</div><div class="panel-body">${view.eligible ? `<p class="settings-note">ثبّت هذا المعرّف في إعداد الجامع. بدء جلسة أخرى يستلزم اختيارها صراحة؛ لا تنتقل القراءات تلقائيًا إلى جلسة إعادة عرض.</p><div class="telemetry-session"><span>معرّف جلسة API</span><code dir="ltr">${esc(view.sessionId)}</code><button type="button" class="button small" data-action="copy-telemetry-session" data-mutation ${!state.connected || state.mutation ? 'disabled' : ''}>نسخ معرّف الجلسة</button></div><dl class="telemetry-details"><div><dt>آخر جهاز أرسل</dt><dd>${view.lastDeviceId ? ltr(view.lastDeviceId) : 'لم يصل معرّف جهاز'}</dd></div><div><dt>آخر استلام لدى الخادم</dt><dd>${view.lastReceivedAt ? ltr(dateText(view.lastReceivedAt)) : 'لم تصل قراءة بعد'}</dd></div><div><dt>إيصال آخر قراءة</dt><dd>${view.receipt ? `${ltr(view.receipt.measurementId)}<small>رقم القراءة المحفوظة: ${ltr(view.receipt.readingId)}</small>` : view.lastReceivedAt ? 'لا يوجد إيصال مرقّم لهذه القراءة' : 'لم يصل إيصال بعد'}</dd></div></dl>${!state.connected ? '<p class="form-error">الخدمة غير متصلة؛ المعروض آخر حالة مستلمة. حدّث الاتصال قبل نسخ المعرّف.</p>' : ''}` : `<p class="settings-note">ابدأ جلسة «قراءات جهاز عبر API» قبل إعداد الجامع. معرّف جلسة إعادة العرض لا يصلح لاستقبال قياسات الجهاز، ولن يُستخدم بدلًا منها.</p><button type="button" class="button section-spacer" data-action="telemetry-session" data-mutation>اختيار جلسة API جديدة ${icon('arrow')}</button>`}<p class="settings-note section-spacer">يرسل جامع JSONL قراءة محفوظة في كل سطر إلى الجلسة المحددة. اتبع دليل الجامع المحلي لصيغة الملف وطريقة التشغيل؛ لا تُرسل هذه البطاقة أي قياسات.</p><div class="info-callout section-spacer">${icon('info')}<p>وصول قراءة أو إيصال يثبت الاستلام البرمجي فقط، ولا يثبت اتصال حساس أو صحة قياسه. نموذج V9 البحثي غير مؤهل لهذا المخطط؛ القواعد التجريبية فقط مفعّلة، وصمام البرنامج مغلق دون أوامر لعتاد.</p></div></div>`;
}
function updateTelemetryCard() {
  const card = $('#telemetry-card');
  if (!card) return;
  const html = telemetryCardContent();
  // Compare the source markup, since the browser normalizes empty attributes
  // in innerHTML. Unchanged polls must not recreate a focused copy button.
  if (card.telemetryMarkup !== html) {
    const focused = document.activeElement?.closest?.('#telemetry-card [data-action]')?.dataset.action;
    card.innerHTML = html; card.telemetryMarkup = html;
    if (['copy-telemetry-session', 'telemetry-session'].includes(focused))
      $(`#telemetry-card [data-action="${focused}"]`)?.focus({ preventScroll: true });
  }
}
async function copyTelemetrySession() {
  const view = telemetryView(state.data);
  if (!view.eligible || !state.connected || state.mutation) throw new Error('لا توجد جلسة API حالية جاهزة للنسخ. حدّث الحالة أولًا.');
  if (!globalThis.navigator?.clipboard?.writeText) throw new Error('النسخ التلقائي غير متاح. حدّد معرّف الجلسة الظاهر وانسخه يدويًا.');
  try { await navigator.clipboard.writeText(view.sessionId); }
  catch { throw new Error('تعذّر النسخ إلى الحافظة. حدّد معرّف الجلسة الظاهر وانسخه يدويًا.'); }
  const current = telemetryView(state.data);
  if (!current.eligible || current.sessionId !== view.sessionId || !state.connected)
    throw new Error('تغيّرت حالة الجلسة أثناء النسخ؛ لا تستخدم المعرّف المنسوخ حتى تحدّث الحالة وتنسخ الجلسة الحالية.');
  toast('نُسخ معرّف جلسة API الحالية.');
}
function settingsPage() {
  const settings = state.data?.settings;
  if (!settings) return `<section class="panel">${empty('الإعدادات غير متاحة', 'يلزم الاتصال بالخدمة المحلية لقراءة الإعدادات الحالية؛ لن نعرض حدودًا بديلة.', 'settings')}</section>`;
  return `<div class="settings-grid"><section class="panel"><div class="panel-heading"><div><h2>إعدادات القواعد التجريبية</h2><p>تُحفظ محليًا وتُراجع من الخادم</p></div>${pill('غير معتمدة تنظيميًا','warning',false)}</div><form class="panel-body" id="settings-form"><label class="field" style="margin-bottom:22px"><span>اسم الموقع / مساحة العمل</span><input name="site_name" maxlength="100" value="${esc(settings.site_name)}" required autocomplete="off"></label><div class="settings-fields">${settingsFields.map(([key,label,unit,step,min,max]) => `<label class="field"><span>${label} <small class="ltr">${unit}</small></span><input name="${key}" type="number" step="${step}" min="${min}" max="${max}" value="${esc(settings[key])}" required><small>الحد الحالي: ${esc(settings[key])} ${unit}</small></label>`).join('')}</div><p class="form-error" id="settings-error" role="alert" hidden></p><div class="settings-actions"><button class="button primary" type="submit" data-mutation>${icon('check')}حفظ الإعدادات</button><button class="button" type="button" data-action="reload-settings">إلغاء التعديلات</button><p class="settings-note">لا تتغير عتبات ML أو نماذجه.<br>القواعد تخص مخطط قراءات الجهاز.</p></div></form></section><div><section class="panel"><div class="panel-heading"><h2>الاحتجاز البرمجي</h2>${pill('مغلق','neutral')}</div><div class="panel-body"><p class="settings-note">يمكنك تثبيت احتجاز يدوي أو إزالة هذا الطلب. إزالة الاحتجاز <strong>لا تفتح الصمام</strong>؛ لا يوجد متحكم أمان مؤهل أو عتاد موصول بهذا التطبيق.</p><div class="settings-actions"><button class="button danger" data-action="hold" data-mutation>${icon('shield')}تثبيت الاحتجاز</button><button class="button" data-action="reset" data-mutation>إزالة الطلب اليدوي</button></div></div></section><section class="panel section-spacer" id="telemetry-card" aria-label="ربط جامع القراءات">${telemetryCardContent()}</section></div></div>`;
}

function render(force = false) {
  const focusedPresentation=document.activeElement?.dataset?.action;
  reconcilePresentation();
  if (state.page === 'settings' && state.settingsRendered && !force) { updateTelemetryCard(); mutationUI(); return; }
  const content = $('#page-content');
  if(GUIDE_PAGES.includes(state.page)) {
    renderGuide(content,state.page,state.data,state.guideUi,state.connected,Boolean(state.mutation),force);
  } else if (!state.data && state.connected === false && !$('#connection-error').hidden) {
    content.innerHTML = `<section class="panel">${empty('لا توجد بيانات متاحة الآن', 'عند تعذّر الاتصال لا يستبدل التطبيق القراءات ببيانات مولّدة. شغّل الخدمة المحلية ثم أعد المحاولة.', 'server', '<button class="button primary" data-action="retry">إعادة الاتصال</button>')}</section>`;
  } else if (state.page === 'engineering') {
    delete content.dataset.guidePage;
    if (force) content.innerHTML = plantPage(state.data, state.plantUi, Boolean(state.mutation) || !state.connected);
    else updatePlant(content, state.data, state.plantUi, Boolean(state.mutation) || !state.connected);
    state.plantUi.previousLevels = {};
  } else {delete content.dataset.guidePage;content.innerHTML = ({ overview, measurements, alerts: alertsPage, history: historyPage, model: modelPage, settings: settingsPage })[state.page]();}
  if (state.page === 'settings' && state.data?.settings) state.settingsRendered = true;
  syncJourneyScene(force);updatePresentationClock();mutationUI();
  if(['auto-pause','auto-resume'].includes(focusedPresentation)&&document.activeElement===document.body){const next=$('#page-content [data-action="'+focusedPresentation+'"]')||$('#page-content [data-action="auto-start"]');next?.focus({preventScroll:true});}
  // Do not let general busy-state handling re-enable exhausted replay actions.
  const step = $('[data-action="step"]'); if (step) step.disabled ||= !canReplay() || state.autoplay;
}
function route() {
  const page = location.hash.slice(1); state.page = Object.hasOwn(pages, page) ? page : 'start';
  document.body.dataset.experience=String(state.page==='plant');
  const [title, eyebrow, description] = pages[state.page];
  $('#page-title').textContent = title; $('#breadcrumb-current').textContent = title;
  $('#page-eyebrow').textContent = eyebrow; $('#page-description').textContent = description;
  $('.research-strip').hidden = GUIDE_PAGES.includes(state.page)||state.page==='engineering';
  $('#new-session-button').hidden = GUIDE_PAGES.includes(state.page)||state.page==='engineering';
  $('#export-top').hidden = GUIDE_PAGES.includes(state.page)||state.page==='engineering';
  $('#advanced-navigation').open ||= !GUIDE_PAGES.includes(state.page);
  document.title = `${title} | مورد`;
  document.querySelectorAll('[data-page]').forEach(node => { const active = node.dataset.page === state.page; node.classList.toggle('active', active); if (active) node.setAttribute('aria-current','page'); else node.removeAttribute('aria-current'); });
  state.settingsRendered = false; closeMenu(); render(true);
  $('#main-content').focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});
  if (state.page === 'history' && state.connected) loadHistory();
  if (state.page === 'alerts' && state.connected) loadAlarms();
}
function historySelectionKey() {
  return JSON.stringify([state.historyScope, state.historyLimit, state.historyScope === 'current' ? state.data?.session?.id || null : null]);
}
async function loadHistory() {
  const request = ++state.historyRequest, key = historySelectionKey();
  const sessionId = state.historyScope === 'current' ? state.data?.session?.id : undefined;
  const current = () => request === state.historyRequest && key === historySelectionKey();
  state.historyError = '';
  if (key !== state.historyKey) { state.readings = []; state.historyLoaded = false; state.historyKey = key; }
  if (state.page === 'history') render();
  try {
    if (state.historyScope === 'current' && !sessionId) throw new Error('لا توجد جلسة حالية لعرض سجلها. اختر كل الجلسات أو ابدأ جلسة جديدة.');
    const result = await api.readings({ limit: state.historyLimit, sessionId });
    if (!current()) return;
    if (!Array.isArray(result.readings)) throw new Error('وصل سجل قراءات غير صالح.');
    state.readings = result.readings; state.historyLoaded = true;
  } catch (error) { if (current()) state.historyError = error.message; }
  if (current() && state.page === 'history') render();
}
async function loadAlarms() {
  const request = ++state.alarmsRequest, generation = state.stateGeneration;
  const current = () => request === state.alarmsRequest && generation === state.stateGeneration;
  state.alarmsError = '';
  try {
    const result = await api.alarms(); if (!current()) return;
    if (!Array.isArray(result.alarms)) throw new Error('وصل سجل تنبيهات غير صالح.');
    state.alarms = result.alarms; state.alarmsLoaded = true;
  } catch (error) { if (current()) state.alarmsError = error.message; }
  if (current() && state.page === 'alerts') render();
}
function sessionFields(sourceId) {
  const source = state.sources.find(s => s.id === sourceId) || state.sources[0];
  if (!source) { $('#session-form-fields').innerHTML = '<p class="form-error">لا توجد مصادر متاحة من الخدمة. أعد الاتصال ثم حاول مجددًا.</p>'; mutationUI(); return; }
  const copy = {
    telemetry: {
      description: 'جلسة استقبال لقياساتك عبر API. لا توجد قراءات تلقائية، ولا ذكاء مؤهل لهذا المخطط؛ حالة الصمام برمجية مغلقة.',
      acknowledgement: 'أفهم أن هذه واجهة اختبار محلية دون عتاد أمان أو تأهيل للنموذج على قراءات جهازي.',
    },
    public_replay: {
      description: `إعادة عرض ${num(source.rows,0)} قراءة تاريخية، بفاصل مصدر قدره ${num(source.sample_seconds,0)} ثانية. يُحسب الاستدلال فعليًا؛ سرعة العرض لا تعني سرعة الحساس.`,
      acknowledgement: 'أفهم أن هذا نموذج بحثي على بيانات تاريخية، لم يُعتمد لسلامة مياه الوضوء أو تشغيل صمام فعلي.',
    },
    digital_twin: {
      description: 'منشأة افتراضية يحسب محركها الخزانات والتدفقات وحالة المعدات بقواعد تشغيل ثابتة. تتقدم ساعة المحاكاة بنبضة أساسية كل ثانية، بسرعة ×1 أو ×10 أو ×30؛ لا يشغّل هذا المصدر نموذج كشف الشذوذ.',
      acknowledgement: 'أفهم أنني أبدأ توأمًا رقميًا؛ قراءاته وأحجامه ناتجة عن محاكاة برمجية، ولا يرسل أوامر إلى عتاد فعلي.',
    },
  }[source.kind];
  if (!copy) { $('#session-form-fields').innerHTML = '<p class="form-error">نوع المصدر غير مدعوم. حدّث قائمة المصادر قبل بدء جلسة.</p>'; mutationUI(); return; }
  $('#session-form-fields').innerHTML = `<label class="field"><span>مصدر القراءات</span><select id="session-source" required>${state.sources.map(s => `<option value="${esc(s.id)}" ${s.id === source.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></label><div class="source-description">${esc(copy.description)}<br><span class="muted">${(source.channels || []).map(c => esc(c.name)).join(' · ')}</span></div><label class="acknowledgement"><input type="checkbox" id="research-ack" required><span>${esc(copy.acknowledgement)}</span></label><p class="settings-note">تُنشأ جلسة جديدة؛ تبقى الجلسات والقراءات السابقة محفوظة في السجل.</p>`;
  mutationUI();
}
async function openSession(sourceId) {
  stopAutoplay(); render(); $('#session-error').hidden = true;
  if (!state.connected) { toast('اتصل بالخدمة المحلية أولًا.', true); return; }
  if (!state.sources.length) {
    try { const result = await api.sources(); state.sources = result.sources; }
    catch (error) { toast(error.message, true); return; }
  }
  sessionFields(typeof sourceId === 'string' ? sourceId : state.data?.source?.id); $('#session-dialog').showModal();
}
function download(blob, filename) {
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
async function exportFile(type) {
  try {
    const date = new Date().toISOString().slice(0,10);
    if (type === 'report') download(new Blob([JSON.stringify(await api.report(), null, 2)], { type: 'application/json;charset=utf-8' }), `mawrid-summary-${date}.json`);
    else download(await api.export(type), `mawrid-${type}-${date}.csv`);
    toast('تم تجهيز الملف من السجل المحفوظ.');
  } catch (error) { toast(error.message, true); }
}
function syncMenuAccessibility() {
  const hidden=window.matchMedia?.('(max-width: 900px)')?.matches===true&&!$('#sidebar').classList.contains('open');
  $('#sidebar').inert=hidden;
  if(hidden)$('#sidebar').setAttribute('aria-hidden','true');else $('#sidebar').removeAttribute('aria-hidden');
}
function closeMenu() { const wasOpen=$('#sidebar').classList.contains('open');$('#sidebar').classList.remove('open'); $('#sidebar-backdrop').hidden = true; $('#menu-button').setAttribute('aria-expanded','false'); syncMenuAccessibility();if(wasOpen)$('#menu-button').focus(); }
async function startPlant() {
  if (!state.connected) throw new Error('اتصل بالخدمة المحلية قبل تشغيل المنشأة الافتراضية.');
  stopAutoplay();
  await mutate(() => api.createSession('virtual_plant', true));
  state.channel = null; state.readings = []; state.historyLoaded = false;
  state.guideUi.experienceSession=plantView(state.data).sessionId;state.guideUi.experienceRestored=false;
  state.guideUi.journeySession=plantView(state.data).sessionId;state.guideUi.journeyIndex=0;state.guideUi.journeyComplete=false;
  if(state.page!=='plant'){location.hash='plant';route();}else render();
  toast('بدأت المنشأة الافتراضية.');
}
async function controlPlant(key, value) {
  if (!plantView(state.data).active || !state.connected) throw new Error('شغّل جلسة المنشأة الافتراضية أولًا.');
  const valid = (key === 'mode' && Object.hasOwn(PLANT_MODES, value)) ||
    (key === 'fault' && Object.hasOwn(PLANT_FAULTS, value)) ||
    (key === 'speed' && [1, 10, 30].includes(value)) || (key === 'running' && typeof value === 'boolean');
  if (!valid) throw new Error('أمر المحاكاة غير صالح.');
  await mutate(() => api.plantControl({ [key]: value }));
}
function selectEquipment(id) {
  if (!Object.hasOwn(EQUIPMENT, id)) return;
  state.plantUi.equipment = id; render();
}
async function guideCommand(control) {
  if(!plantView(state.data).active) await startPlant();
  await mutate(()=>api.plantControl(control));
  // Keep the scene unobstructed: equipment details open only by user choice.

}

const presenter=new JourneyPresentation();
let cameraRequest=0,presentationTextOnly=false,presentationStarting=false;
const presentationNow=()=>globalThis.performance?.now?.()??Date.now();
function presentationContext(){const v=plantView(state.data),x=experienceState(state.data,state.guideUi,state.connected);return {v,x,ready:state.page==='plant'&&state.connected&&!document.hidden&&!$('#experience-details')?.open&&x.id==='journey'};}
function syncPresentationView(){state.guideUi.presentation={...presenter.view(),textOnly:presentationTextOnly};}
function pausePresentation(reason='reading',draw=true){if(presenter.pause(reason,presentationNow())){syncPresentationView();if(draw)render();}}
function reconcilePresentation(){
  const {v,x}=presentationContext();
  if(presenter.status!=='idle'&&presenter.sessionId!==v.sessionId){presenter.stop();presentationTextOnly=false;cameraRequest++;}
  if(presenter.status==='playing'){
    const reason=state.page!=='plant'?'navigation':document.hidden?'hidden':$('#experience-details')?.open?'details':!state.connected?'connection':x.id!=='journey'?'plant':null;
    if(reason)presenter.pause(reason,presentationNow());
  }
  syncPresentationView();
}
function updatePresentationClock(){
  const node=$('#presentation-clock');if(!node)return;
  node.textContent=presenter.status==='playing'?(presenter.waitingCamera?'جارٍ تقريب الجزء…':`الانتقال بعد ${Math.ceil(presenter.remainingMs/1000)} ثانية`):presenter.status==='paused'?`متبقي ${Math.ceil(presenter.remainingMs/1000)} ثانية`:'';
}
async function startPresentation(){
  if(state.mutation||presentationStarting)throw new Error('انتظر اكتمال العملية الحالية.');
  const {x}=presentationContext();if(!['start','paused','journey','normal','done'].includes(x.id))throw new Error('أعد المحاكاة إلى التشغيل الاعتيادي أولًا، ثم ابدأ العرض.');
  presentationStarting=true;state.guideUi.experienceError='';
  try{
    presenter.stop();
    if(x.id==='start')await startPlant();else if(x.id==='paused')await controlPlant('running',true);
    const v=plantView(state.data),next=experienceState(state.data,state.guideUi,state.connected);
    if(!v.active||!['journey','normal','done'].includes(next.id))throw new Error('المحاكاة غير جاهزة للعرض. راجع حالتها ثم حاول مجددًا.');
    state.guideUi.journeySession=v.sessionId;state.guideUi.journeyIndex=0;state.guideUi.journeyComplete=false;state.guideUi.experienceRestored=false;
    presentationTextOnly=false;cameraRequest++;presenter.start(v.sessionId,presentationNow());render();
  }catch(error){state.guideUi.experienceError=error.message;render();throw error;}
  finally{presentationStarting=false;mutationUI();}
}
function resumePresentation(){
  if(state.mutation||!presentationContext().ready)return;
  if(presenter.resume(presentationNow())){cameraRequest++;render();}
}
function stopPresentation(){presenter.stop();presentationTextOnly=false;cameraRequest++;render();}
function tickPresentation(){
  reconcilePresentation();
  if(presenter.status!=='playing'){syncPresentationView();return;}
  const now=presentationNow();
  let fallback=false;
  if(presenter.waitingCamera&&(presentationTextOnly||now-presenter.waitingSince>=8000)){presentationTextOnly=true;presenter.settle(journeyProgress(state.guideUi,presenter.sessionId).stage.id,now);fallback=true;}
  const changed=presenter.tick(now);
  if(changed||fallback){
    if(changed&&presenter.status==='playing'){state.guideUi.journeyIndex=presenter.index;cameraRequest++;}
    syncPresentationView();render();
  }else{syncPresentationView();updatePresentationClock();}
}
let lastJourneyWindow=null,lastJourneyMessage='';
function syncJourneyScene(force=false){
  if(state.page!=='plant'){lastJourneyWindow=null;lastJourneyMessage='';return;}
  const frame=$('#guide-scene'),v=plantView(state.data);if(!frame?.contentWindow)return;
  const x=experienceState(state.data,state.guideUi,state.connected),p=journeyProgress(state.guideUi,v.sessionId);
  const id=!v.active?null:x.id==='fault'?(v.fault==='sensor_dropout'?'verify':v.fault==='clogging'?'media':v.fault==='valve_stuck'?'irrigation':null):x.id==='done'||p.complete?'irrigation':p.stage.id;
  const camera=['playing','paused'].includes(presenter.status)&&presenter.sessionId===v.sessionId?'focus':'overview';
  const signature=JSON.stringify([v.sessionId,id,camera,cameraRequest]);
  if(force||lastJourneyWindow!==frame.contentWindow||lastJourneyMessage!==signature){frame.contentWindow.postMessage({type:'mawrid:journey',id,camera,requestId:cameraRequest},location.origin);lastJourneyWindow=frame.contentWindow;lastJourneyMessage=signature;}
}
function moveJourney(direction){
  if(['playing','paused'].includes(presenter.status)){presenter.stop();presentationTextOnly=false;cameraRequest++;}
  if(state.mutation||!state.connected)return;
  const v=plantView(state.data),x=experienceState(state.data,state.guideUi,state.connected),p=journeyProgress(state.guideUi,v.sessionId);
  if(direction==='previous'&&x.id==='journey'){state.guideUi.journeySession=v.sessionId;state.guideUi.journeyIndex=Math.max(0,p.index-1);}
  else if(direction==='replay'&&['done','normal'].includes(x.id)){state.guideUi.journeySession=v.sessionId;state.guideUi.journeyIndex=0;state.guideUi.journeyComplete=false;state.guideUi.experienceRestored=false;}
  else return;
  render();$('#page-content [data-action="experience-next"]')?.focus({preventScroll:true});
}
window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==$('#guide-scene')?.contentWindow)return;
  if(event.data?.type==='mawrid:scene-ready'){presentationTextOnly=false;syncJourneyScene(true);}
  if(event.data?.type==='mawrid:camera-settled'&&event.data.requestId===cameraRequest){
    presenter.settle(event.data.id,presentationNow());syncPresentationView();updatePresentationClock();
  }
  if(['mawrid:camera-interaction','mawrid:equipment'].includes(event.data?.type))pausePresentation('camera');
});

async function experienceNext() {
  if(state.mutation) throw new Error('انتظر اكتمال العملية الحالية.');
  if(presenter.status==='playing')pausePresentation('manual',false);
  const before=plantView(state.data);
  const action=experienceState(state.data,state.guideUi,state.connected).action;
  if(!action) return;
  if(['journey-next','test'].includes(action)&&['playing','paused'].includes(presenter.status)){presenter.stop();presentationTextOnly=false;cameraRequest++;}
  state.guideUi.experienceError='';
  try {
    if(action==='journey-next'){const p=journeyProgress(state.guideUi,before.sessionId);state.guideUi.journeySession=before.sessionId;state.guideUi.journeyIndex=Math.min(p.total-1,p.index+1);}
    else if(action==='start') await startPlant();
    else if(action==='release') {await mutate(()=>api.reset());return;}
    else {
      const control=action==='test'?{fault:'sensor_dropout',mode:'auto',speed:1,running:true}
        :action==='restore'?{fault:'none',mode:'auto',speed:1,running:true}:{running:true};
      const result=await mutate(()=>api.plantControl(control));
      const v=plantView(result);
      if(action==='test'&&v.fault==='sensor_dropout') {const p=journeyProgress(state.guideUi,before.sessionId);if(p.index===p.total-1){state.guideUi.journeySession=before.sessionId;state.guideUi.journeyComplete=true;}state.guideUi.experienceSession=v.sessionId;state.guideUi.experienceRestored=false;}
      if(action==='restore'&&before.fault==='sensor_dropout'&&before.equipment?.irrigation?.status==='closed'&&before.irrigation_flow_lpm===0&&v.fault==='none'&&v.mode==='auto'&&v.running) {state.guideUi.experienceSession=v.sessionId;state.guideUi.experienceRestored=true;}
    }
  } catch(error){state.guideUi.experienceError=error.message;throw error;}
  finally {render();if(state.page==='plant')$('#page-content [data-action="experience-next"]')?.focus({preventScroll:true});}
}

$('#page-content').addEventListener('click', async event => {
  const equipment = event.target.closest('[data-equipment]');
  if (equipment) { selectEquipment(equipment.dataset.equipment); return; }
  const filter = event.target.closest('[data-filter]');
  if (filter) { state.alarmFilter = filter.dataset.filter; render(); return; }
  const button = event.target.closest('[data-action]'); if (!button) return;
  const action = button.dataset.action;
  try {
    if(action==='auto-start') {await startPresentation();$('#page-content [data-action="auto-pause"]')?.focus({preventScroll:true});}
    else if(action==='auto-pause') {pausePresentation();$('#page-content [data-action="auto-resume"]')?.focus({preventScroll:true});}
    else if(action==='auto-resume') {resumePresentation();$('#page-content [data-action="auto-pause"]')?.focus({preventScroll:true});}
    else if(action==='auto-stop') {stopPresentation();$('#page-content [data-action="experience-next"]')?.focus({preventScroll:true});}
    else if(action==='experience-next') await experienceNext();
    else if(action==='journey-previous') moveJourney('previous');
    else if(action==='journey-replay') moveJourney('replay');
    else if(action==='experience-details') {pausePresentation('details',false);$('#experience-details')?.showModal();render();}
    else if(action==='experience-close') {$('#experience-details')?.close();render();}
    else if (action === 'guide-tour'||action === 'guide-tour-next') {
      state.guideUi.tourStep=action==='guide-tour-next'?Math.min(2,state.guideUi.tourStep+1):Math.max(0,Math.min(2,Number(button.dataset.step)||0));
      updateTour($('#page-content'),state.guideUi);mutationUI();
    }
    else if(action==='guide-component'){state.guideUi.component=button.dataset.component;updateComponent($('#page-content'),state.guideUi);}
    else if(action==='guide-normal') await guideCommand({fault:'none',mode:'auto',running:true});
    else if(action==='guide-fault') await guideCommand({fault:'sensor_dropout',mode:'auto',running:true});
    else if(action==='guide-clear') await guideCommand({fault:'none',mode:'auto',running:true});
    else if (action === 'new-session') await openSession();
    else if (action === 'plant-zoom') { state.plantUi.zoom = !state.plantUi.zoom; render(); }
    else if (action === 'plant-start') await startPlant();
    else if (action === 'plant-speed') await controlPlant('speed', Number(button.dataset.speed));
    else if (action === 'plant-running') {await controlPlant('running', !plantView(state.data).running);if(state.page==='plant')$('#page-content [data-action="experience-next"]')?.focus({preventScroll:true});}
    else if (action === 'telemetry-session') await openSession('telemetry');
    else if (action === 'copy-telemetry-session') await copyTelemetrySession();
    else if (action === 'retry') await refresh({ all: true });
    else if (action === 'play') await play();
    else if (action === 'pause') await pause();
    else if (action === 'step') { if (!canReplay()) return; await mutate(() => api.step(1)); }
    else if (action === 'ack') { await mutate(() => api.acknowledge(button.dataset.id)); await loadAlarms(); toast('سُجل اطلاعك على التنبيه.'); }
    else if (action === 'refresh-alarms') await loadAlarms();
    else if (action === 'refresh-history') await loadHistory();
    else if (action.startsWith('export-')) await exportFile(action.slice(7));
    else if (action === 'reload-settings') { const result = await api.settings(); state.data.settings = result.settings; render(true); }
    else if (action === 'hold') { await pause(); await mutate(() => api.stop()); toast('ثُبّت الاحتجاز البرمجي. لا أوامر لعتاد فعلي.'); }
    else if (action === 'reset') { await mutate(() => api.reset()); toast('أزيل الطلب اليدوي. يبقى الصمام البرمجي مغلقًا.'); }
    else if (action === 'telemetry-help') location.hash = 'settings';
  } catch (error) { toast(error.message, true); }
});
$('#page-content').addEventListener('input',event=>{
  if(event.target.id!=='guide-component-search')return;
  const query=event.target.value.trim();let count=0;
  $('#page-content').querySelectorAll('[data-component]').forEach(b=>{const show=b.textContent.includes(query);b.hidden=!show;if(show)count++;});
  $('#guide-component-count').textContent=count?`النتائج: ${count}`:'لا يوجد جزء بهذا الاسم. جرّب كلمة أخرى.';
});
$('#page-content').addEventListener('change', async event => {
  const target = event.target;
  if(target.id==='guide-speed') {try{await controlPlant('speed',Number(target.value));}catch(error){toast(error.message,true);render();}return;}
  if (target.id === 'plant-mode' || target.id === 'plant-fault') {
    try { await controlPlant(target.id === 'plant-mode' ? 'mode' : 'fault', target.value); }
    catch (error) { toast(error.message, true); render(); }
    return;
  }
  if (target.id === 'chart-channel') { state.channel = target.value; render(); }
  if (target.id === 'batch-size') state.batch = Math.max(1, Math.min(25, Number(target.value) || 1));
  if (target.id === 'history-scope') { state.historyScope = target.value; await loadHistory(); }
  if (target.id === 'history-limit') { state.historyLimit = Number(target.value); await loadHistory(); }
});
$('#page-content').addEventListener('keydown', event => {
  const equipment = event.target.closest('[data-equipment]');
  if (equipment && ['Enter', ' '].includes(event.key)) { event.preventDefault(); selectEquipment(equipment.dataset.equipment); }
});
$('#page-content').addEventListener('submit', async event => {
  if (event.target.id !== 'settings-form') return;
  event.preventDefault(); const form = event.target, values = new FormData(form), settings = { site_name: String(values.get('site_name')).trim() };
  for (const [key] of settingsFields) settings[key] = Number(values.get(key));
  const errorNode = $('#settings-error'); errorNode.hidden = true;
  if (settings.ph_min >= settings.ph_max || settings.chlorine_min >= settings.chlorine_max) { errorNode.textContent = 'يجب أن يكون الحد الأدنى أقل من الحد الأعلى.'; errorNode.hidden = false; return; }
  try { await mutate(() => api.saveSettings(settings)); state.settingsRendered = false; render(true); toast('حُفظت الإعدادات التجريبية. نموذج ML لم يتغير.'); }
  catch (error) { const current = $('#settings-error'); if (current) { current.textContent = error.message; current.hidden = false; } }
});
$('#session-form').addEventListener('change', event => { if (event.target.id === 'session-source') sessionFields(event.target.value); else mutationUI(); });
$('#session-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!$('#research-ack')?.checked) return;
  stopAutoplay(); $('#session-error').hidden = true;
  try {
    if (state.mutation) await state.mutation;
    await mutate(() => api.createSession($('#session-source').value, $('#research-ack').checked));
    state.readings = []; state.historyLoaded = false; state.alarmsLoaded = false;
    $('#session-dialog').close(); state.channel = null; location.hash = state.data?.source?.kind === 'digital_twin' ? 'plant' : 'overview'; route(); toast(state.data?.source?.kind === 'digital_twin' ? 'بدأت جلسة المنشأة الافتراضية.' : 'الجلسة جاهزة.');
  } catch (error) { $('#session-error').textContent = error.message; $('#session-error').hidden = false; }
});
document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => $('#session-dialog').close()));
$('#new-session-button').addEventListener('click', openSession);
$('#refresh-button').addEventListener('click', () => refresh({ all: true }));
$('#retry-button').addEventListener('click', () => refresh({ all: true }));
$('#menu-button').addEventListener('click', () => { const open = !$('#sidebar').classList.contains('open'); $('#sidebar').classList.toggle('open', open); $('#sidebar-backdrop').hidden = !open; $('#menu-button').setAttribute('aria-expanded',String(open));syncMenuAccessibility(); if(open)$('#main-nav a')?.focus(); });
$('#sidebar-backdrop').addEventListener('click', closeMenu);
document.addEventListener('keydown', event => { if (event.key === 'Escape') {const wasOpen=$('#sidebar').classList.contains('open');closeMenu();if(wasOpen)$('#menu-button').focus();} });
document.addEventListener('visibilitychange', () => { if(document.hidden)pausePresentation('hidden'); if (document.hidden && state.autoplay) pause(); else if (!document.hidden) refresh({ all: true }); });
window.addEventListener('hashchange', route);
window.addEventListener('beforeunload', () => {stopAutoplay();presenter.stop();});
window.matchMedia?.('(max-width: 900px)')?.addEventListener?.('change',syncMenuAccessibility);
$('#local-date').textContent = new Date().toLocaleDateString('ar-SA', { weekday:'long', day:'numeric', month:'long', calendar:'gregory' });
$('#page-content').innerHTML = '<div class="loading-block"><div class="loading-line"></div>جارٍ الاتصال بمورد…</div>';
route(); refresh();
setInterval(() => { if (!document.hidden && !state.autoplay) refresh(); }, 2000);
setInterval(tickPresentation,1000);
