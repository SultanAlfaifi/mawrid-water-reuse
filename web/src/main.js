import './styles.css';
import './reading.css';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { UI, STAGES, MODES, EVIDENCE, DELIVERABLES } from './content.js';
import { DEMO_NORMAL, DEMO_MODES, evaluateDemo } from './reuse-logic.js';
import logoUrl from '../../assets/brand/mawrid-logo.svg?url';
import { createPalmStory } from './palm-story.js';
import { createCampusGallery } from './campus-gallery.js';

gsap.registerPlugin(ScrollTrigger);
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = { lang: 'ar', stage: 0, mode: 'normal', exploded: false, flow: true, tour: null };
try { state.lang = localStorage.getItem('mawrid-language') === 'en' ? 'en' : 'ar'; } catch {}
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
state.flow = !reducedMotion.matches;
const t = (key) => UI[key]?.[state.lang === 'ar' ? 0 : 1] ?? key;
const local = (value) => value[state.lang];
const pad = (n) => String(n).padStart(2, '0');
let model, animationContext, documentBlob, palmStory, campusGallery;
let documentRequest = 0;
const documentDialog = $('#document-dialog');
const docLoaders = {
  ...import.meta.glob('../../docs/*.md', { query: '?raw', import: 'default' }),
  ...import.meta.glob('../../references/README.md', { query: '?raw', import: 'default' })
};
const favicon = document.createElement('link');
favicon.rel = 'icon'; favicon.type = 'image/svg+xml'; favicon.href = logoUrl;
document.head.append(favicon);

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function renderStages() {
  $('#stage-tabs').replaceChildren(...STAGES.map((stage, index) => {
    const button = document.createElement('button');
    button.className = 'stage-tab';
    button.dataset.stage = index;
    button.setAttribute('aria-pressed', String(index === state.stage));
    button.append(textElement('span', pad(index + 1), 'mono'), textElement('span', local(stage).label));
    button.addEventListener('click', () => { stopTour(); selectStage(index, false, true); });
    return button;
  }));
}

function selectStage(index, fromModel = false, focus = false) {
  state.stage = Math.max(0, Math.min(5, Number(index)));
  const content = local(STAGES[state.stage]);
  $('#lesson-number').textContent = pad(state.stage + 1) + ' / 06';
  $('#stage-title').textContent = content.title;
  $('#stage-description').textContent = content.description;
  $('#stage-input').textContent = content.input;
  $('#stage-output').textContent = content.output;
  $('#stage-evidence').textContent = content.evidence;
  $('#model-caption').textContent = content.label;
  $$('.stage-tab').forEach((button, i) => button.setAttribute('aria-pressed', String(i === state.stage)));
  $('#previous').disabled = state.stage === 0;
  $('#next').disabled = state.stage === 5;
  model?.setStage(state.stage);
  if (focus) model?.focusStage?.(state.stage);
  if (fromModel) stopTour();
}

function renderScenarios() {
  $('#scenario-tabs').replaceChildren(...MODES.map((mode) => {
    const button = textElement('button', local(mode).label, 'scenario-tab');
    button.dataset.mode = mode.id;
    button.setAttribute('aria-pressed', String(mode.id === state.mode));
    button.addEventListener('click', () => selectMode(mode.id));
    return button;
  }));
}

function selectMode(mode) {
  stopTour();
  state.mode = mode;
  const evaluated = evaluateDemo(mode);
  const inputs = { ...DEMO_NORMAL, ...DEMO_MODES[mode] };
  const selected = MODES.find((item) => item.id === mode);
  const conditions = [
    ['conditionsPower', inputs.power], ['conditionsSensor', inputs.sensorValid],
    ['conditionsDisinfection', inputs.disinfectionValid], ['conditionsStorage', inputs.storageValid]
  ];
  $('#condition-list').replaceChildren(...conditions.map(([label, passed]) => {
    const row = document.createElement('div'); row.className = 'condition ' + (passed ? 'met' : 'unmet');
    row.append(textElement('span', passed ? '✓' : '×', 'condition-icon'),
      textElement('span', t(label)), textElement('span', passed ? t('accepted') : t('failed'), 'condition-status'));
    return row;
  }));
  $('#decision-result').classList.toggle('held', !evaluated.permitted);
  $('#decision-title').textContent = t(evaluated.permitted ? 'permittedTitle' : 'heldTitle');
  $('#decision-icon').textContent = evaluated.permitted ? '↗' : '↳';
  $('#decision-description').textContent = local(selected).description;
  $('#valve-state').textContent = t(evaluated.permitted ? 'openValve' : 'closedValve');
  $('#route-state').textContent = t(evaluated.permitted ? 'reuseRoute' : 'holdRoute');
  $$('.scenario-tab').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.mode === mode)));
  model?.setMode(mode);
  $('#model-container').dataset.mode = mode;
}

function renderEvidence() {
  $('#evidence-table').replaceChildren(...EVIDENCE.map((item, index) => {
    const content = local(item);
    const row = document.createElement('div'); row.className = 'evidence-row';
    const title = document.createElement('div');
    title.append(textElement('span', pad(index + 1), 'mono'), textElement('h3', content[0]));
    const description = textElement('p', content[1]);
    const status = textElement('span', content[2], 'evidence-status');
    status.dataset.evidence = item.code;
    const button = textElement('button', '↗', 'evidence-link');
    button.setAttribute('aria-label', t('openDocument') + ': ' + content[0]);
    button.addEventListener('click', () => openDocument(item.doc));
    row.append(title, description, status, button);
    return row;
  }));
}

function renderDeliverables() {
  const open = $$('.deliverable[open]').map((item) => item.dataset.index);
  $('#deliverables-list').replaceChildren(...DELIVERABLES.map((item, index) => {
    const content = local(item);
    const details = document.createElement('details');
    details.className = 'deliverable'; details.dataset.index = index;
    details.open = open.includes(String(index));
    const summary = document.createElement('summary');
    summary.append(textElement('span', pad(index + 1), 'mono'), textElement('h3', content[0]), textElement('span', '+', 'expand-sign'));
    const body = document.createElement('div'); body.className = 'deliverable-body';
    for (const [label, value] of [[t('existing'), content[1]], [t('needed'), content[2]]]) {
      const column = document.createElement('div');
      column.append(textElement('span', label, 'detail-label'), textElement('p', value)); body.append(column);
    }
    const button = textElement('button', t('openDocument') + ' ↗', 'text-button');
    button.addEventListener('click', () => openDocument(item.doc)); body.append(button);
    details.append(summary, body); return details;
  }));
}

function setLanguage(language) {
  stopTour();
  state.lang = language;
  document.documentElement.lang = language;
  document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
  document.title = language === 'ar' ? 'مورد — مياه الوضوء، مورد للري' : 'MAWRID — Ablution water, a resource for irrigation';
  $$('[data-i18n]').forEach((element) => { element.innerHTML = t(element.dataset.i18n); });
  $$('[data-i18n-aria]').forEach((element) => element.setAttribute('aria-label', t(element.dataset.i18nAria)));
  $('#language').textContent = language === 'ar' ? 'EN' : 'ع';
  $('#language').lang = language === 'ar' ? 'en' : 'ar';
  $('#language').setAttribute('aria-label', language === 'ar' ? 'Switch to English' : 'التبديل إلى العربية');
  const canvas = $('#model-container canvas');
  if (canvas) canvas.setAttribute('aria-label', t('dragHint'));
  $('#flow').setAttribute('aria-pressed', String(state.flow));
  try { localStorage.setItem('mawrid-language', language); } catch {}
  renderStages(); selectStage(state.stage); renderScenarios(); selectMode(state.mode);
  renderEvidence(); renderDeliverables();
  palmStory?.setLanguage(language);
  campusGallery?.setLanguage(language);
  if (!model && $('#model-container').dataset.fallback === 'true') renderFallback();
  requestAnimationFrame(() => { model?.resize(); ScrollTrigger.refresh(); });
}

function stopTour() {
  if (state.tour) clearInterval(state.tour);
  state.tour = null;
  $('#start-journey [data-i18n]').textContent = t('startJourney');
}

function beginTour() {
  if (state.tour) { stopTour(); return; }
  selectMode('normal'); selectStage(0, false, true);
  if (reducedMotion.matches) { $('#stage-tabs').scrollIntoView({ block: 'center' }); return; }
  state.flow = true; model?.setFlow(true); $('#flow').setAttribute('aria-pressed', 'true');
  $('#start-journey [data-i18n]').textContent = t('stopJourney');
  state.tour = setInterval(() => {
    if (state.stage >= 5) { stopTour(); return; }
    selectStage(state.stage + 1, false, true);
  }, 5200);
}

function renderFallback() {
  $('#model-container').dataset.fallback = 'true';
  $('#model-container').replaceChildren(textElement('h3', t('fallbackTitle')), textElement('p', t('fallbackText')));
  for (const id of ['explode', 'flow', 'reset-view']) $('#' + id).disabled = true;
}

async function initModel() {
  try {
    const { createProcessView } = await import('./process-view.js');
    model = await createProcessView({
      container: $('#model-container'), reducedMotion: reducedMotion.matches,
      onSelect: (index) => selectStage(index, true, true)
    });
    $('#model-loading')?.remove();
    delete $('#model-container').dataset.fallback;
    for (const id of ['explode', 'flow', 'reset-view']) $('#' + id).disabled = false;
    model.setStage(state.stage); model.setMode(state.mode); model.setFlow(state.flow);
    model.setExploded(state.exploded);
    $('#model-container canvas')?.setAttribute('aria-label', t('dragHint'));
    document.documentElement.dataset.model = 'ready';
  } catch (error) {
    document.documentElement.dataset.model = 'fallback';
    renderFallback();
    console.warn('MAWRID 3D unavailable:', error.message);
  }
}

async function openDocument(key) {
  const file = key === 'references' ? '../../references/README.md' : '../../docs/' + key + '.md';
  const load = docLoaders[file];
  if (!load) return;
  const request = ++documentRequest;
  $('#document-title').textContent = t('documentLoading');
  $('#document-body').replaceChildren();
  $('#document-source').hidden = true;
  if (!documentDialog.open) documentDialog.showModal();
  try {
    const raw = await load();
    if (request !== documentRequest || !documentDialog.open) return;
    $('#document-title').textContent = raw.match(/^#\s+(.+)$/m)?.[1] ?? key;
    $('#document-body').innerHTML = DOMPurify.sanitize(marked.parse(raw));
    $('#document-body').dir = /[أ-ي]/.test(raw.slice(0, 600)) ? 'rtl' : 'ltr';
    $('#document-body').querySelector('h1')?.remove();
    $('#document-body').querySelectorAll('a').forEach((anchor) => {
      const href = anchor.getAttribute('href');
      if (!href) return;
      if (/^(https?:|mailto:)/i.test(href)) { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; return; }
      if (href.startsWith('#')) return;
      const match = href.match(/(?:^|\/)([\w-]+)\.md(?:#.*)?$/);
      if (match) {
        const target = href.includes('references') ? 'references' : match[1];
        const targetFile = target === 'references' ? '../../references/README.md' : '../../docs/' + target + '.md';
        if (docLoaders[targetFile]) {
          anchor.addEventListener('click', (event) => { event.preventDefault(); openDocument(target); });
          return;
        }
      }
      const currentPath = key === 'references' ? 'references/README.md' : 'docs/' + key + '.md';
      const documentURL = new URL(currentPath, 'https://github.com/SultanAlfaifi/mawrid-water-reuse/blob/main/');
      const targetURL = new URL(href, documentURL);
      if (targetURL.pathname.endsWith('/')) targetURL.pathname = targetURL.pathname.replace('/blob/main/', '/tree/main/');
      anchor.href = targetURL.href;
      anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
    });
    if (documentBlob) URL.revokeObjectURL(documentBlob);
    documentBlob = URL.createObjectURL(new Blob([raw], { type: 'text/markdown;charset=utf-8' }));
    $('#document-source').href = documentBlob;
    $('#document-source').download = key + '.md';
    $('#document-source').hidden = false;
    $('#document-body').scrollTop = 0;
  } catch {
    if (request !== documentRequest || !documentDialog.open) return;
    $('#document-title').textContent = t('documentError');
  }
}

function closeDocument() {
  documentRequest++;
  documentDialog.close();
}

function setupMotion() {
  animationContext?.revert();
  if (reducedMotion.matches) return;
  animationContext = gsap.context(() => {
    gsap.from('.site-header', { y: -12, duration: 0.7, ease: 'power2.out' });
    gsap.from('.hero-copy > .eyebrow, #hero-title, .hero-lead, .hero-actions', {
      y: 24, duration: 0.95, stagger: 0.1, ease: 'power3.out', delay: 0.15
    });
    gsap.from('.hero-product', { y: 32, duration: 1.3, ease: 'power3.out', delay: 0.25 });
    $$('.section-top, .purpose-grid, #campus-gallery, .biochar-note, .closing').forEach((element) => {
      gsap.from(element, { y: 26, duration: 0.8, ease: 'power2.out',
        scrollTrigger: { trigger: element, start: 'top 88%', once: true } });
    });
  });
}

$('#language').addEventListener('click', () => setLanguage(state.lang === 'ar' ? 'en' : 'ar'));
$('#start-journey').addEventListener('click', beginTour);
$('#previous').addEventListener('click', () => { stopTour(); selectStage(state.stage - 1, false, true); });
$('#next').addEventListener('click', () => { stopTour(); selectStage(state.stage + 1, false, true); });
$('#explode').addEventListener('click', () => {
  state.exploded = !state.exploded; model?.setExploded(state.exploded);
  $('#explode').setAttribute('aria-pressed', String(state.exploded));
});
$('#flow').addEventListener('click', () => {
  stopTour(); state.flow = !state.flow; model?.setFlow(state.flow);
  $('#flow').setAttribute('aria-pressed', String(state.flow));
});
$('#reset-view').addEventListener('click', () => model?.resetCamera?.());
$('#stage-doc').addEventListener('click', () => openDocument(STAGES[state.stage].doc));
$$('[data-doc]').forEach((button) => button.addEventListener('click', () => openDocument(button.dataset.doc)));
$('#palm-story').addEventListener('opendocument', (event) => openDocument(event.detail.key));
$('#close-document').addEventListener('click', closeDocument);
documentDialog.addEventListener('cancel', () => { documentRequest++; });
documentDialog.addEventListener('click', (event) => {
  if (event.target === documentDialog) {
    const r = documentDialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDocument();
  }
});
$('#model-container').addEventListener('processviewerror', () => { model?.dispose(); model = null; renderFallback(); });
reducedMotion.addEventListener('change', () => {
  stopTour(); state.flow = !reducedMotion.matches;
  model?.setReducedMotion?.(reducedMotion.matches);
  model?.setFlow(state.flow);
  $('#flow').setAttribute('aria-pressed', String(state.flow)); setupMotion();
});
document.addEventListener('visibilitychange', () => { if (document.hidden) stopTour(); });
window.addEventListener('pagehide', () => { stopTour(); model?.dispose(); model = null; animationContext?.revert(); palmStory?.dispose(); palmStory = null; campusGallery?.dispose(); campusGallery = null; });
window.addEventListener('pageshow', (event) => {
  if (event.persisted) {
    $('#model-container').replaceChildren();
    palmStory = createPalmStory({container: $('#palm-story'), lang: state.lang});
    campusGallery = createCampusGallery({container: $('#campus-gallery'), lang: state.lang});
    initModel(); setupMotion();
  }
});

setLanguage(state.lang);
palmStory = createPalmStory({container: $('#palm-story'), lang: state.lang});
campusGallery = createCampusGallery({container: $('#campus-gallery'), lang: state.lang});
setupMotion();
initModel();
