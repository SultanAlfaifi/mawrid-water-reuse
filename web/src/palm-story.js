import './palm-story.css';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

// Optimised WebP files are the website assets. The PNG originals stay in the
// repository as source material and are deliberately excluded from this glob.
const imageFiles = import.meta.glob('../../assets/images/palm-*.webp', { eager: true, query: '?url', import: 'default' });
// This optional glob lets the section mount while the separately owned research
// file is being prepared. A published build reads its RESEARCH_SOURCES export.
const researchFiles = import.meta.glob('./research-data.js', { eager: true });
const researchSources = Object.values(researchFiles).flatMap((module) => Array.isArray(module.RESEARCH_SOURCES) ? module.RESEARCH_SOURCES : []);
const SOURCE_LABELS = {
  'kaust-palm-soil-2024': ['كاوست', 'KAUST'],
  'khalifa-palm-column-2023': ['جامعة خليفة', 'Khalifa University'],
  'qatar-palm-review-2026': ['جامعة قطر', 'Qatar University'],
  'riyadh-raw-fiber-2024': ['Elsevier', 'Elsevier'],
  'kearns-wood-uva-2021': ['Sage', 'Sage'],
  'fang-field-review-2025': ['جامعة فلوريدا', 'University of Florida'],
  'alsawy-regeneration-review-2022': ['Springer Nature', 'Springer Nature'],
  'gastat-palm-base-2024': ['هيئة الإحصاء', 'GASTAT'],
};
const sourceMovementPreferences = new WeakMap();
let instanceCount = 0;

const COPY = {
  ar: {
    title: 'لماذا النخيل؟',
    introduction: 'مخلفات محلية نختبر تحويلها إلى وسط لمعالجة الماء.',
    navigation: 'اختر خطوة',
    imageNote: 'صور توضيحية مولّدة.',
    benefitsTitle: 'لماذا نختبره؟',
    researchTitle: 'الأبحاث التي نستند إليها',
    researchNote: 'شعارات مصادرنا؛ ليست شركاء مورد.',
    pause: 'إيقاف حركة المصادر', resume: 'تشغيل حركة المصادر',
    dragHint: 'اسحب لاستكشاف المصادر',
    hoverHint: 'ضع مؤشر الفأرة فوق البحث لعرض تفاصيله', touchHint: 'المس البحث لعرض تفاصيله',
    source: 'المصدر', supports: 'يدعم', limits: 'حدوده',
    readSource: 'افتح البحث', allReferences: 'كل المراجع', researchDetails: 'ماذا يدعم البحث؟',
    openStudy: 'افتح الدراسة ↗', sourceDetails: 'عرض تفاصيل البحث',
    statisticSource: 'هيئة الإحصاء · 2024',
    stages: [
      { title: 'النخلة', description: 'نجمع مخلفات التقليم من مصدر محدد.', alt: 'نخلة مثمرة في بيئة زراعية، صورة توضيحية مولّدة' },
      { title: 'المخلفات', description: 'نفرز المخلفات ونجففها قبل التحويل.', alt: 'سعف وبقايا تقليم نخيل قبل المعالجة، صورة توضيحية مولّدة' },
      { title: 'الفحم الحيوي', description: 'نحوّلها حراريًا في أكسجين محدود إلى فحم مسامي، ثم نختبر خصائصه.', alt: 'وسط كربوني من مخلفات النخيل، صورة توضيحية مولّدة' },
      { title: 'طبقة الفحم', description: 'نضيفه في طبقة منفصلة ونقارن أثره بالكربون التجاري.', alt: 'طبقة وسط كربوني داخل مرشح مقطعي، صورة توضيحية مولّدة' }
    ],
    benefits: [
      { title: 'قاعدة نخيل كبيرة', description: 'أكثر من 37.6 مليون نخلة في السعودية عام 2024.' },
      { title: 'تكلفة تحتاج قياسًا', description: 'نقارن كلفة التحضير والطاقة والنقل والتجديد بالكربون التجاري.' },
      { title: 'التقاط مواد ذائبة', description: 'اختبرت الأبحاث احتجاز مواد محددة؛ نتحقق من أثره على مياه الوضوء بالتحاليل.' }
    ]
  },
  en: {
    title: 'Why date palms?',
    introduction: 'Local residues we test as a material for water treatment.',
    navigation: 'Choose a step',
    imageNote: 'Generated illustrations.',
    benefitsTitle: 'Why test it?',
    researchTitle: 'Research we draw on',
    researchNote: 'Source identities, not MAWRID partners.',
    pause: 'Pause source movement', resume: 'Resume source movement',
    dragHint: 'Drag to explore sources',
    hoverHint: 'Hover over a study to see its details', touchHint: 'Touch a study to see its details',
    source: 'Source', supports: 'Supports', limits: 'Limits',
    readSource: 'Open the research', allReferences: 'All references', researchDetails: 'What does the research support?',
    openStudy: 'Open study ↗', sourceDetails: 'Show study details',
    statisticSource: 'GASTAT · 2024',
    stages: [
      { title: 'The palm', description: 'Collect pruning residues from an identified source.', alt: 'A fruiting date palm in an agricultural setting, generated illustration' },
      { title: 'The residues', description: 'Sort and dry the residues before conversion.', alt: 'Date-palm fronds and pruning residues before processing, generated illustration' },
      { title: 'Biochar', description: 'Use heat and limited oxygen to make porous carbon, then test its properties.', alt: 'Carbon medium from date-palm residues, generated illustration' },
      { title: 'Carbon layer', description: 'Add a separate layer and compare its contribution against commercial carbon.', alt: 'A carbon-medium layer inside a cutaway filter, generated illustration' }
    ],
    benefits: [
      { title: 'A substantial palm base', description: 'Over 37.6 million date palms in Saudi Arabia in 2024.' },
      { title: 'A cost to measure', description: 'Compare preparation, energy, transport and regeneration costs against commercial carbon.' },
      { title: 'Capture dissolved substances', description: 'Research tested the capture of selected substances; we check its effect on ablution water through laboratory analysis.' }
    ]
  }
};

const IMAGE_NAMES = [['palm-tree', 'palm-source'], ['palm-residue', 'palm-residues'], ['palm-biochar'], ['palm-layer', 'palm-filter']];
function imageFor(index) {
  for (const name of IMAGE_NAMES[index]) {
    const path = Object.keys(imageFiles).find((key) => key.endsWith(`/${name}.webp`));
    if (path) return imageFiles[path];
  }
  return null;
}
function local(value, lang) {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value[lang === 'ar' ? 0 : 1] ?? value[0] ?? '';
  return value?.[lang] ?? value?.ar ?? value?.en ?? '';
}
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function safeUrl(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}
function logoUrl(value) {
  if (!value || typeof value !== 'string') return null;
  if (/^data:image\/(?:svg\+xml|png|webp|jpeg)(?:;[^,]*)?,/i.test(value)) return value;
  try { const url = new URL(value, window.location.href); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}

export function createPalmStory({ container, lang = 'ar', reducedMotion = false }) {
  if (!(container instanceof HTMLElement)) throw new TypeError('Palm story requires a container element.');
  const id = `palm-story-${++instanceCount}`;
  let language = lang === 'en' ? 'en' : 'ar';
  let disposed = false;
  let selected = 0;
  let selectionStatic;
  let storyTimeline = null;
  let userPaused = sourceMovementPreferences.get(container) ?? false;
  let pointerInside = false;
  let focusInside = false;
  let loopFrame = 0;
  let presentationFrame = 0;
  const removers = [];
  const previous = { dir: container.getAttribute('dir'), lang: container.getAttribute('lang'), labelledby: container.getAttribute('aria-labelledby') };
  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const touchQuery = window.matchMedia('(hover: none) and (pointer: coarse)');
  const shortQuery = window.matchMedia('(max-height: 620px)');
  const requestedReduced = typeof reducedMotion === 'boolean' ? reducedMotion : Boolean(reducedMotion?.matches);
  const reduce = () => requestedReduced || motionQuery.matches;
  const staticStory = () => reduce() || shortQuery.matches;
  const listen = (target, type, handler, options) => {
    target.addEventListener(type, handler, options);
    removers.push(() => target.removeEventListener(type, handler, options));
  };

  container.classList.add('palm-story');
  const track = element('div', 'palm-track');
  const shell = element('div', 'palm-shell');
  const header = element('header', 'palm-heading');
  const title = element('h2', 'palm-title');
  title.id = `${id}-title`;
  container.setAttribute('aria-labelledby', title.id);
  const introduction = element('p', 'palm-introduction');
  header.append(title, introduction);
  const sceneStack = element('div', 'palm-scenes');
  const scenes = COPY.ar.stages.map((_, index) => {
    const article = element('article', 'palm-scene');
    article.id = `${id}-step-${index + 1}`;
    const image = element('img', 'palm-scene-image');
    const src = imageFor(index);
    if (src) image.src = src;
    else article.classList.add('palm-scene-missing');
    image.decoding = 'async';
    image.loading = index === 0 ? 'eager' : 'lazy';
    image.draggable = false;
    const shade = element('div', 'palm-scene-shade');
    shade.setAttribute('aria-hidden', 'true');
    const copy = element('div', 'palm-scene-copy');
    const heading = element('h3', 'palm-scene-title');
    const description = element('p', 'palm-scene-description');
    copy.append(heading, description);
    article.append(image, shade, copy);
    sceneStack.append(article);
    return { article, image, heading, description };
  });
  const navigation = element('div', 'palm-navigation');
  navigation.setAttribute('role', 'group');
  const buttons = scenes.map((scene, index) => {
    const button = element('button', 'palm-step-button');
    button.type = 'button';
    button.setAttribute('aria-controls', scene.article.id);
    const number = element('span', 'palm-step-index', String(index + 1).padStart(2, '0'));
    number.setAttribute('aria-hidden', 'true');
    const label = element('span', 'palm-step-label');
    button.append(number, label);
    listen(button, 'click', () => {
      if (staticStory() || !storyTimeline?.scrollTrigger) {
        updateSelection(index);
        scene.article.scrollIntoView({ behavior: 'instant', block: 'start' });
      } else {
        const trigger = storyTimeline.scrollTrigger;
        const progress = index === 0 ? 0 : (index + 0.35) / storyTimeline.duration();
        window.scrollTo({ top: trigger.start + progress * (trigger.end - trigger.start), behavior: 'smooth' });
      }
    });
    navigation.append(button);
    return { button, label };
  });
  const imageNote = element('p', 'palm-image-note');
  shell.append(header, sceneStack, navigation, imageNote);
  track.append(shell);

  const benefits = element('section', 'palm-benefits');
  const benefitHeader = element('div', 'palm-benefits-heading');
  const benefitTitle = element('h3');
  benefitHeader.append(benefitTitle);
  const benefitGrid = element('div', 'palm-benefits-grid');
  const benefitNodes = COPY.ar.benefits.map((_, index) => {
    const article = element('article', 'palm-benefit');
    const heading = element('h4');
    const description = element('p', 'palm-benefit-description');
    article.append(heading, description);
    const source = index === 0 ? element('a', 'palm-statistic-source') : null;
    if (source) {
      source.href = safeUrl(researchSources.find((entry) => entry.id === 'gastat-palm-base-2024')?.url) ?? 'https://www.stats.gov.sa/en/w/news/127';
      source.target = '_blank';
      source.rel = 'noopener noreferrer';
      article.append(source);
    }
    benefitGrid.append(article);
    return { heading, description, source };
  });
  benefits.append(benefitHeader, benefitGrid);

  const research = element('section', 'palm-research');
  const researchHeader = element('div', 'palm-research-heading');
  const researchText = element('div');
  const researchTitle = element('h3');
  const researchNote = element('p', 'palm-research-note');
  researchText.append(researchTitle, researchNote);
  const researchActions = element('div', 'palm-research-actions');
  const dragHint = element('span', 'palm-drag-hint');
  const pauseButton = element('button', 'palm-loop-pause');
  pauseButton.type = 'button';
  const pauseIcon = element('span', 'palm-pause-icon', 'Ⅱ');
  pauseIcon.setAttribute('aria-hidden', 'true');
  const pauseLabel = element('span');
  pauseButton.append(pauseIcon, pauseLabel);
  const referencesButton = element('button', 'palm-all-references');
  referencesButton.type = 'button';
  listen(referencesButton, 'click', () => container.dispatchEvent(new CustomEvent('opendocument', { detail: { key: 'palm-research' }, bubbles: true })));
  researchActions.append(referencesButton, pauseButton, dragHint);
  researchHeader.append(researchText, researchActions);
  const viewport = element('div', 'palm-research-viewport');
  const researchTrack = element('div', 'palm-research-track');
  const sourceList = element('ul', 'palm-source-list');
  const details = element('details', 'palm-source-details');
  details.open = true;
  details.id = `${id}-source-details`;
  const detailSummary = element('summary');
  const detailBody = element('div', 'palm-source-detail-body');
  const detailPlaceholder = element('div', 'palm-source-placeholder');
  const placeholderIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  placeholderIcon.setAttribute('viewBox', '0 0 32 32');
  placeholderIcon.setAttribute('aria-hidden', 'true');
  const pointerPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  pointerPath.setAttribute('d', 'M7 4v23l6-7 5 10 4-2-5-10 10-1Z');
  pointerPath.setAttribute('fill', 'none');
  pointerPath.setAttribute('stroke', 'currentColor');
  pointerPath.setAttribute('stroke-width', '1.6');
  pointerPath.setAttribute('stroke-linejoin', 'round');
  placeholderIcon.append(pointerPath);
  const placeholderText = element('p');
  detailPlaceholder.append(placeholderIcon, placeholderText);
  const detailTitle = element('h4');
  const detailSupport = element('p');
  const detailLimit = element('p', 'palm-source-limit');
  const detailLink = element('a', 'palm-source-detail-link');
  detailLink.target = '_blank';
  detailLink.rel = 'noopener noreferrer';
  detailBody.append(detailTitle, detailSupport, detailLimit, detailLink);
  details.append(detailSummary, detailPlaceholder, detailBody);
  let hoverSourceIndex = null;
  let keyboardSourceIndex = null;
  let touchSourceIndex = null;
  let touchInput = touchQuery.matches;
  const sourceNodes = researchSources.flatMap((source) => {
    const href = safeUrl(source.url);
    if (!href) return [];
    const item = element('li', 'palm-source-item');
    const anchor = element('a', 'palm-source-link');
    anchor.href = href;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    const category = element('span', 'palm-source-category');
    const logo = element('img', 'palm-source-logo');
    logo.decoding = 'async';
    // A hidden lazy image never enters the loading viewport; load the eight
    // small identity assets immediately, then replace their text fallback.
    logo.loading = 'eager';
    logo.draggable = false;
    logo.hidden = true;
    const mark = element('span', 'palm-source-mark');
    const organization = element('span', 'palm-source-wordmark');
    const shortName = element('span', 'palm-source-name');
    shortName.dir = 'auto';
    const arrow = element('span', 'palm-source-arrow', '↗');
    arrow.setAttribute('aria-hidden', 'true');
    mark.append(logo, organization);
    anchor.append(mark, shortName, category, arrow);
    item.append(anchor);
    sourceList.append(item);
    const index = sourceList.children.length - 1;
    anchor.dataset.sourceIndex = String(index);
    return [{ source, anchor, category, logo, organization, shortName }];
  });
  let cloneLists = [];
  let loopAnimation = null;
  let loopDistance = 0;
  let loopDuration = 0;
  let loopOffset = 0;
  let dragGesture = null;
  let dragFrame = 0;
  let pendingDragOffset = null;
  let suppressDragClick = false;
  let pressedSource = null;
  let pressReleaseTimer = 0;
  let loopVisible = typeof IntersectionObserver === 'undefined';
  researchTrack.append(sourceList);
  viewport.append(researchTrack);
  research.append(researchHeader, viewport, details);
  research.hidden = sourceNodes.length === 0;
  container.replaceChildren(track, benefits, research);

  function updateSelection(index) {
    const next = Math.max(0, Math.min(3, index));
    const isStatic = staticStory();
    if (next === selected && selectionStatic === isStatic) return;
    selected = next;
    selectionStatic = isStatic;
    buttons.forEach(({ button }, i) => button.setAttribute('aria-pressed', String(i === selected)));
    scenes.forEach(({ article }, i) => {
      article.setAttribute('aria-hidden', String(!isStatic && i !== selected));
      article.inert = !isStatic && i !== selected;
    });
  }
  function showSource(index) {
    if (disposed || !sourceNodes.length) return;
    const source = sourceNodes[index].source;
    const copy = COPY[language];
    detailTitle.textContent = local(source.title, language);
    detailSupport.textContent = `${copy.supports}: ${local(source.supports, language)}`;
    detailLimit.textContent = `${copy.limits}: ${local(source.limits, language)}`;
    detailLink.textContent = copy.openStudy;
    detailLink.href = sourceNodes[index].anchor.href;
    detailBody.hidden = false;
    detailPlaceholder.hidden = true;
  }
  function syncSourcePresentation() {
    placeholderText.textContent = COPY[language][touchInput ? 'touchHint' : 'hoverHint'];
    const index = hoverSourceIndex ?? keyboardSourceIndex ?? touchSourceIndex;
    if (index !== null) showSource(index);
    else {
      detailBody.hidden = true;
      detailPlaceholder.hidden = false;
    }
  }
  function updateLoop() {
    if (disposed) return;
    const paused = reduce() || userPaused || pointerInside || focusInside || Boolean(dragGesture || pressedSource) || document.hidden || !loopVisible;
    research.dataset.paused = String(paused);
    research.dataset.reduced = String(reduce());
    pauseButton.hidden = reduce();
    pauseButton.setAttribute('aria-pressed', String(userPaused));
    pauseLabel.textContent = COPY[language][userPaused ? 'resume' : 'pause'];
    pauseIcon.textContent = userPaused ? '▷' : 'Ⅱ';
    if (loopAnimation) {
      if (paused) {
        // pause() can settle on the next frame. Hold the current phase now so
        // the card under a pointer cannot move between press and activation.
        const offset = readLoopOffset();
        loopAnimation.pause();
        setLoopOffset(offset);
      }
      else loopAnimation.play();
    }
  }
  function readLoopOffset() {
    if (!loopDistance) return 0;
    const offset = loopAnimation && loopDuration ? Number(loopAnimation.currentTime ?? 0) / loopDuration * loopDistance : loopOffset;
    return ((offset % loopDistance) + loopDistance) % loopDistance;
  }
  function setLoopOffset(offset) {
    if (!loopDistance) return;
    loopOffset = ((offset % loopDistance) + loopDistance) % loopDistance;
    if (loopAnimation) loopAnimation.currentTime = loopOffset / loopDistance * loopDuration;
    else researchTrack.style.transform = `translate3d(-${loopOffset}px, 0, 0)`;
  }
  function measureLoop() {
    if (disposed || !viewport.clientWidth || !sourceNodes.length) return;
    // One cycle is the exact width of the fixed-width source cards. There is
    // no inter-list gap: the final card borders the first card of the next copy.
    const distance = sourceList.getBoundingClientRect().width;
    if (!distance) return;
    // At the end of a cycle, another complete viewport must still be covered.
    // Two copies are sufficient only when a complete cycle is wider than it.
    const copies = Math.max(2, Math.ceil(viewport.clientWidth / distance) + 1);
    syncClones(copies - 1);
    research.dataset.loopCopies = String(copies);
    researchTrack.style.setProperty('--palm-loop-distance', `${distance}px`);
    const phase = loopDistance ? readLoopOffset() / loopDistance : 0;
    if (reduce()) {
      loopAnimation?.cancel();
      loopAnimation = null;
      loopDistance = distance;
      loopDuration = distance / 19 * 1000;
      setLoopOffset(phase * distance);
    } else if (!loopAnimation || Math.abs(distance - loopDistance) > 0.01) {
      loopAnimation?.cancel();
      loopDistance = distance;
      loopDuration = distance / 19 * 1000;
      researchTrack.style.removeProperty('transform');
      loopAnimation = researchTrack.animate([
        { transform: 'translate3d(0, 0, 0)' },
        { transform: `translate3d(-${distance}px, 0, 0)` }
      ], { duration: loopDuration, iterations: Infinity, easing: 'linear' });
      loopAnimation.currentTime = phase * loopDuration;
    }
    updateLoop();
  }
  function refreshLoop() {
    if (loopFrame) cancelAnimationFrame(loopFrame);
    loopFrame = requestAnimationFrame(() => { loopFrame = 0; measureLoop(); });
  }
  function syncClones(count, rebuild = false) {
    if (!rebuild && cloneLists.length === count) return;
    cloneLists.forEach((list) => list.remove());
    cloneLists = Array.from({ length: count }, () => {
      const list = sourceList.cloneNode(true);
      list.classList.add('palm-source-clone');
      list.setAttribute('aria-hidden', 'true');
      // Visual copies retain real, clickable anchors. Only the original cycle
      // participates in keyboard order and the accessibility tree.
      list.querySelectorAll('a').forEach((anchor) => { anchor.tabIndex = -1; anchor.removeAttribute('aria-describedby'); });
      researchTrack.append(list);
      return list;
    });
  }
  function refreshPresentation() {
    if (disposed) return;
    if (storyTimeline?.scrollTrigger) {
      const trigger = storyTimeline.scrollTrigger;
      trigger.refresh();
      trigger.update();
      // A newly mounted section can already be halfway down the document,
      // including after BFCache restores the previous native scroll position.
      storyTimeline.totalProgress(trigger.progress, false);
      updateSelection(Math.min(3, Math.floor(storyTimeline.time())));
    }
    updateLoop();
  }
  function queuePresentation() {
    if (disposed || presentationFrame) return;
    presentationFrame = requestAnimationFrame(() => { presentationFrame = 0; refreshPresentation(); });
  }
  function configureMotion() {
    storyTimeline?.scrollTrigger?.kill();
    storyTimeline?.kill();
    storyTimeline = null;
    container.classList.toggle('palm-static', staticStory());
    const articles = scenes.map((scene) => scene.article);
    const images = scenes.map((scene) => scene.image);
    gsap.set(articles, { clearProps: 'opacity,visibility' });
    gsap.set(images, { clearProps: 'transform' });
    if (!staticStory()) {
      gsap.set(articles, { autoAlpha: 0 });
      gsap.set(articles[0], { autoAlpha: 1 });
      gsap.set(images, { scale: 1.008 });
      storyTimeline = gsap.timeline({ scrollTrigger: {
        trigger: track, start: 'top top', end: 'bottom bottom', scrub: 0.65, invalidateOnRefresh: true,
        // Refresh restores animation progress with callbacks suppressed. Keep
        // the accessible selection aligned with the restored visual frame.
        onRefresh: () => { if (storyTimeline) updateSelection(Math.min(3, Math.floor(storyTimeline.time()))); }
      } });
      scenes.forEach((scene, index) => {
        storyTimeline.fromTo(scene.image, { scale: 1.008 }, { scale: 1.055, duration: 1.1, ease: 'none', immediateRender: false }, index);
        if (index < scenes.length - 1) {
          storyTimeline.fromTo(scene.article, { autoAlpha: 1 }, { autoAlpha: 0, duration: 0.36, ease: 'none', immediateRender: false }, index + 0.82);
          storyTimeline.fromTo(scenes[index + 1].article, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.36, ease: 'none', immediateRender: false }, index + 0.82);
        }
      });
      storyTimeline.eventCallback('onUpdate', () => updateSelection(Math.min(3, Math.floor(storyTimeline.time()))));
      refreshPresentation();
    }
    updateSelection(selected);
    updateLoop();
    refreshLoop();
    queuePresentation();
  }
  function setLanguage(next) {
    if (disposed) return;
    language = next === 'en' ? 'en' : 'ar';
    container.lang = language;
    container.dir = language === 'ar' ? 'rtl' : 'ltr';
    const copy = COPY[language];
    title.textContent = copy.title;
    introduction.textContent = copy.introduction;
    navigation.setAttribute('aria-label', copy.navigation);
    imageNote.textContent = copy.imageNote;
    scenes.forEach((scene, index) => {
      const stage = copy.stages[index];
      scene.image.alt = stage.alt;
      scene.heading.textContent = stage.title;
      scene.description.textContent = stage.description;
      buttons[index].label.textContent = stage.title;
    });
    benefitTitle.textContent = copy.benefitsTitle;
    benefitNodes.forEach((node, index) => {
      const benefit = copy.benefits[index];
      node.heading.textContent = benefit.title;
      node.description.textContent = benefit.description;
      if (node.source) node.source.textContent = copy.statisticSource;
    });
    researchTitle.textContent = copy.researchTitle;
    researchNote.textContent = copy.researchNote;
    referencesButton.textContent = copy.allReferences;
    detailSummary.textContent = copy.researchDetails;
    dragHint.textContent = copy.dragHint;
    sourceNodes.forEach(({ source, anchor, category, logo, organization, shortName }) => {
      organization.textContent = local(source.organization, language);
      shortName.textContent = local(SOURCE_LABELS[source.id], language);
      shortName.hidden = !shortName.textContent;
      logo.alt = local(source.logoAlt, language) || local(source.organization, language);
      const src = logoUrl(local(source.logoUrl, language));
      logo.hidden = true;
      organization.hidden = false;
      if (src) {
        if (logo.src !== src) logo.src = src;
        if (logo.complete && logo.naturalWidth > 0) { logo.hidden = false; organization.hidden = true; }
      } else logo.removeAttribute('src');
      category.textContent = local(source.category, language) || copy.source;
      anchor.title = local(source.title, language);
      anchor.setAttribute('aria-label', `${local(source.organization, language)}: ${local(source.title, language)}. ${touchQuery.matches ? copy.sourceDetails : copy.readSource}`);
      if (touchQuery.matches) anchor.setAttribute('role', 'button');
      else anchor.removeAttribute('role');
      anchor.dir = language === 'ar' ? 'rtl' : 'ltr';
    });
    syncSourcePresentation();
    syncClones(cloneLists.length, true);
    updateLoop();
    refreshLoop();
    queuePresentation();
  }

  listen(pauseButton, 'click', () => { userPaused = !userPaused; sourceMovementPreferences.set(container, userPaused); updateLoop(); });
  listen(viewport, 'pointerenter', (event) => { if (event.pointerType !== 'touch') pointerInside = true; updateLoop(); });
  listen(viewport, 'pointerleave', (event) => {
    if (event.pointerType !== 'touch') { pointerInside = false; hoverSourceIndex = null; syncSourcePresentation(); }
    updateLoop();
  });
  listen(viewport, 'pointerover', (event) => {
    const anchor = event.target.closest?.('.palm-source-link');
    if (event.pointerType !== 'touch' && !dragGesture?.active && anchor && viewport.contains(anchor)) {
      touchInput = false;
      hoverSourceIndex = Number(anchor.dataset.sourceIndex);
      syncSourcePresentation();
    }
  });
  listen(viewport, 'pointerout', (event) => {
    if (event.pointerType === 'touch') return;
    const anchor = event.target.closest?.('.palm-source-link');
    if (anchor && anchor !== event.relatedTarget?.closest?.('.palm-source-link')) {
      hoverSourceIndex = null;
      syncSourcePresentation();
    }
  });
  listen(viewport, 'pointerdown', (event) => {
    if (!event.isPrimary || event.button !== 0 || dragGesture || !loopDistance) return;
    suppressDragClick = false;
    clearPressedSource();
    touchInput = event.pointerType === 'touch';
    keyboardSourceIndex = null;
    const anchor = event.target.closest?.('.palm-source-link');
    if (anchor && viewport.contains(anchor)) pressedSource = { index: Number(anchor.dataset.sourceIndex), href: anchor.href, pointerType: event.pointerType };
    if (touchInput) touchSourceIndex = anchor ? Number(anchor.dataset.sourceIndex) : null;
    syncSourcePresentation();
    dragGesture = { id: event.pointerId, x: event.clientX, y: event.clientY, offset: readLoopOffset(), active: false };
    updateLoop();
  });
  function clearPressedSource() {
    clearTimeout(pressReleaseTimer);
    pressReleaseTimer = 0;
    pressedSource = null;
  }
  function flushDrag() {
    if (dragFrame) cancelAnimationFrame(dragFrame);
    dragFrame = 0;
    if (pendingDragOffset !== null) setLoopOffset(pendingDragOffset);
    pendingDragOffset = null;
  }
  listen(viewport, 'pointermove', (event) => {
    const gesture = dragGesture;
    if (!gesture || gesture.id !== event.pointerId) return;
    const dx = event.clientX - gesture.x;
    const dy = event.clientY - gesture.y;
    if (!gesture.active) {
      if (Math.abs(dy) >= 6 && Math.abs(dy) > Math.abs(dx)) {
        dragGesture = null;
        clearPressedSource();
        touchSourceIndex = null;
        syncSourcePresentation();
        updateLoop();
        return;
      }
      if (Math.abs(dx) < 6 || Math.abs(dx) <= Math.abs(dy)) return;
      gesture.active = true;
      viewport.setPointerCapture(event.pointerId);
      research.dataset.dragging = 'true';
      hoverSourceIndex = null;
      touchSourceIndex = null;
      syncSourcePresentation();
      updateLoop();
    }
    // Physical movement has the same direction in Arabic and English. Modulo
    // keeps the repeated cards continuous even across either cycle boundary.
    pendingDragOffset = gesture.offset - dx;
    if (!dragFrame) dragFrame = requestAnimationFrame(flushDrag);
  });
  function endDrag(event) {
    const gesture = dragGesture;
    if (!gesture || gesture.id !== event.pointerId) return;
    flushDrag();
    dragGesture = null;
    research.dataset.dragging = 'false';
    if (gesture.active && event.type === 'pointerup') suppressDragClick = true;
    if (gesture.active || event.type !== 'pointerup' || !viewport.contains(event.target)) clearPressedSource();
    else if (pressedSource) {
      // Keep the source and pause through the subsequent click. The fallback
      // releases a cancelled tap that generates no click, including touch.
      pressReleaseTimer = setTimeout(() => { clearPressedSource(); updateLoop(); }, 500);
    }
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    if (event.pointerType !== 'touch' && pointerInside) {
      const anchor = document.elementFromPoint(event.clientX, event.clientY)?.closest('.palm-source-link');
      hoverSourceIndex = anchor && viewport.contains(anchor) ? Number(anchor.dataset.sourceIndex) : null;
      syncSourcePresentation();
    }
    updateLoop();
  }
  listen(window, 'pointerup', endDrag);
  listen(window, 'pointercancel', endDrag);
  listen(viewport, 'lostpointercapture', endDrag);
  listen(viewport, 'click', (event) => {
    if (suppressDragClick && event.detail > 0) {
      suppressDragClick = false;
      clearPressedSource();
      updateLoop();
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const anchor = event.target.closest?.('.palm-source-link');
    const pressed = event.detail > 0 ? pressedSource : null;
    clearPressedSource();
    updateLoop();
    // A cancelled/repositioned press must never activate an adjacent study.
    if (pressed && (!anchor || Number(anchor.dataset.sourceIndex) !== pressed.index || anchor.href !== pressed.href)) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (anchor && (event.pointerType === 'touch' || pressed?.pointerType === 'touch' || touchInput || touchQuery.matches)) {
      event.preventDefault();
      touchInput = true;
      touchSourceIndex = Number(anchor.dataset.sourceIndex);
      details.open = true;
      syncSourcePresentation();
    }
  }, true);
  listen(viewport, 'dragstart', (event) => event.preventDefault());
  listen(viewport, 'keydown', (event) => {
    const anchor = event.target.closest?.('.palm-source-link');
    if (event.key === ' ' && touchQuery.matches && anchor) {
      event.preventDefault();
      touchSourceIndex = Number(anchor.dataset.sourceIndex);
      details.open = true;
      syncSourcePresentation();
    }
  });
  listen(document, 'pointerdown', (event) => {
    if (!viewport.contains(event.target) && !details.contains(event.target)) { touchSourceIndex = null; syncSourcePresentation(); }
  });
  listen(viewport, 'focusin', (event) => {
    focusInside = true;
    const anchor = event.target.closest?.('.palm-source-link');
    if (anchor) {
      const index = Number(anchor.dataset.sourceIndex);
      const keyboardFocus = anchor.matches(':focus-visible');
      if (keyboardFocus) { keyboardSourceIndex = index; syncSourcePresentation(); }
      const box = anchor.getBoundingClientRect();
      const frame = viewport.getBoundingClientRect();
      // Pointer clicks on visible clones must not jump to the original copy.
      // Keyboard focus on an offscreen original reveals it, then resumes from
      // that same phase instead of restarting the animation on blur.
      if (keyboardFocus && !dragGesture && !pressedSource && loopDistance && sourceList.contains(anchor) && (box.left < frame.left || box.right > frame.right)) {
        const item = sourceList.children[index];
        const offset = Math.max(0, Math.min(item.offsetLeft - sourceList.offsetLeft, loopDistance - viewport.clientWidth));
        setLoopOffset(offset);
      }
      if (keyboardFocus) viewport.scrollLeft = 0;
    }
    updateLoop();
  });
  listen(viewport, 'focusout', (event) => {
    focusInside = viewport.contains(event.relatedTarget);
    if (!details.contains(event.relatedTarget)) keyboardSourceIndex = null;
    syncSourcePresentation();
    updateLoop();
  });
  listen(details, 'focusout', (event) => {
    if (!details.contains(event.relatedTarget) && !viewport.contains(event.relatedTarget)) {
      keyboardSourceIndex = null;
      syncSourcePresentation();
    }
  });
  listen(viewport, 'load', (event) => {
    const image = event.target;
    if (!image.classList?.contains('palm-source-logo')) return;
    image.hidden = false;
    image.nextElementSibling.hidden = true;
    refreshLoop();
  }, true);
  listen(viewport, 'error', (event) => {
    const image = event.target;
    if (!image.classList?.contains('palm-source-logo')) return;
    image.hidden = true;
    image.nextElementSibling.hidden = false;
    refreshLoop();
  }, true);
  listen(document, 'visibilitychange', updateLoop);
  listen(window, 'pageshow', queuePresentation);
  listen(motionQuery, 'change', configureMotion);
  listen(shortQuery, 'change', configureMotion);
  listen(touchQuery, 'change', () => { touchInput = touchQuery.matches; setLanguage(language); });
  const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(refreshLoop);
  resizeObserver?.observe(viewport);
  const intersectionObserver = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver((entries) => {
    loopVisible = entries.some((entry) => entry.isIntersecting);
    updateLoop();
  });
  intersectionObserver?.observe(viewport);
  listen(window, 'resize', refreshLoop, { passive: true });
  setLanguage(language);
  configureMotion();
  document.fonts?.ready.then(() => { if (!disposed) { refreshLoop(); queuePresentation(); } });

  return {
    setLanguage,
    dispose() {
      if (disposed) return;
      disposed = true;
      storyTimeline?.scrollTrigger?.kill();
      storyTimeline?.kill();
      if (loopFrame) cancelAnimationFrame(loopFrame);
      if (presentationFrame) cancelAnimationFrame(presentationFrame);
      if (dragFrame) cancelAnimationFrame(dragFrame);
      clearPressedSource();
      loopAnimation?.cancel();
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      removers.forEach((remove) => remove());
      container.replaceChildren();
      container.classList.remove('palm-story', 'palm-static');
      for (const [attribute, value] of [['dir', previous.dir], ['lang', previous.lang], ['aria-labelledby', previous.labelledby]]) {
        if (value === null) container.removeAttribute(attribute);
        else container.setAttribute(attribute, value);
      }
    }
  };
}
