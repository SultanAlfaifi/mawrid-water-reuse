import './campus-gallery.css';

// Only these WebP illustrations enter the build; the source PNGs are excluded.
// Missing new images use the existing concept during asset preparation, with
// an explicit temporary-image caption instead of implying that it depicts the
// selected activity. None of these images documents an implemented pilot.
const imageFiles = import.meta.glob('../../assets/images/campus-{concept,ablution,irrigation,testing,maintenance}.webp', { eager: true, query: '?url', import: 'default' });
const imageFor = (name) => Object.entries(imageFiles).find(([path]) => path.endsWith(`/campus-${name}.webp`))?.[1];
const fallbackImage = imageFor('concept');
const scenes = ['ablution', 'concept', 'testing', 'irrigation', 'maintenance'];
const count = scenes.length;
const stepAngle = 360 / count;
const gallerySnapshots = new WeakMap();
let instanceCount = 0;

const COPY = {
  ar: {
    label: 'المسار المقترح داخل الجامعة', carousel: 'معرض صور', slide: 'مشهد',
    note: 'صور مولّدة · تصور مقترح غير منفذ',
    previous: 'المشهد السابق', next: 'المشهد التالي',
    pause: 'إيقاف الدوران', resume: 'تشغيل الدوران', reduced: 'تنقل يدوي',
    pick: 'اختر مشهدًا', hint: 'اسحب أو استخدم الأسهم',
    temporary: 'صورة مؤقتة للوحدة؛ لقطة هذه الخطوة قيد التجهيز.',
    scenes: [
      { title: 'مصدر الوضوء', description: 'نجمع ماء الوضوء عبر خط منفصل.', alt: 'تصور مولّد لمرفق وضوء جامعي بصنابير ومقاعد وقنوات تصريف' },
      { title: 'وحدة مورد', description: 'نعالج الماء في وحدة قريبة من المصدر.', alt: 'تصور مولّد لوحدة مورد داخل حرم جامعي' },
      { title: 'فحص العينات', description: 'التحاليل المخبرية تختبر صلاحية الاستخدام.', alt: 'تصور مولّد لجمع عينات الماء وفحصها مخبريًا' },
      { title: 'الري بالتنقيط', description: 'الاستخدام المستهدف بعد التحقق من جودة الماء.', alt: 'تصور مولّد لري مساحة مزروعة بالتنقيط داخل الجامعة' },
      { title: 'صيانة الخرطوشة', description: 'نقارن أداء الوسط ونحدد موعد استبداله.', alt: 'تصور مولّد لصيانة خرطوشة الوسط الكربوني في وحدة مورد' },
    ],
  },
  en: {
    label: 'A proposed campus cycle', carousel: 'image carousel', slide: 'scene',
    note: 'Generated images · An unbuilt proposal',
    previous: 'Previous scene', next: 'Next scene',
    pause: 'Pause rotation', resume: 'Start rotation', reduced: 'Manual navigation',
    pick: 'Choose a scene', hint: 'Drag or use the arrows',
    temporary: 'Temporary unit image; this scene is being prepared.',
    scenes: [
      { title: 'Ablution source', description: 'Collect ablution water through a separate line.', alt: 'Generated concept of a campus ablution facility with taps, seats and drainage channels' },
      { title: 'The MAWRID unit', description: 'Treat the water close to its source.', alt: 'Generated concept of the MAWRID unit on a university campus' },
      { title: 'Sample testing', description: 'Laboratory analysis checks suitability for use.', alt: 'Generated concept of water sampling and laboratory testing' },
      { title: 'Drip irrigation', description: 'The intended use, after water quality is verified.', alt: 'Generated concept of drip irrigation in a planted campus area' },
      { title: 'Cartridge maintenance', description: 'Compare media performance and plan replacement.', alt: 'Generated concept of carbon-media cartridge maintenance in the MAWRID unit' },
    ],
  },
};

const wrap = (index) => ((index % count) + count) % count;
const textElement = (tag, className) => {
  const element = document.createElement(tag);
  element.className = className;
  return element;
};
const makeButton = (className) => {
  const element = textElement('button', className);
  element.type = 'button';
  return element;
};

export function createCampusGallery({ container, lang = 'ar', reducedMotion } = {}) {
  if (!container) throw new TypeError('A container is required for the campus gallery.');
  const abort = new AbortController();
  const listen = (target, type, callback, options = {}) => target.addEventListener(type, callback, { ...options, signal: abort.signal });
  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const saved = gallerySnapshots.get(container);
  let reduce = typeof reducedMotion === 'boolean' ? reducedMotion : motionQuery.matches;
  let language = lang === 'en' ? 'en' : 'ar';
  let direction = language === 'ar' ? -1 : 1;
  let activeIndex = saved?.activeIndex ?? 1;
  let angle = -activeIndex * stepAngle * direction;
  let cardWidth = 560;
  let radius = 430;
  let flight = null;
  let pointer = null;
  let raf = 0;
  let timer = 0;
  let hoverPaused = false;
  let userPaused = saved?.userPaused ?? false;
  let inView = typeof IntersectionObserver === 'undefined';
  let disposed = false;
  let imagesPrimed = false;
  let suppressClickUntil = 0;
  let motionPointerIntent = null;
  const id = `campus-gallery-${++instanceCount}`;

  const root = textElement('div', 'campus-gallery');
  root.setAttribute('role', 'group');
  root.setAttribute('aria-describedby', `${id}-note`);
  const top = textElement('div', 'campus-gallery__top');
  const note = textElement('p', 'campus-gallery__note');
  note.id = `${id}-note`;
  // The rotation control precedes rotating content in keyboard order (WAI APG).
  const motionButton = makeButton('campus-gallery__motion');
  const motionIcon = textElement('span', 'campus-gallery__motion-icon');
  motionIcon.setAttribute('aria-hidden', 'true');
  const motionText = textElement('span', 'campus-gallery__motion-text');
  motionButton.append(motionIcon, motionText);
  top.append(note, motionButton);

  const viewport = textElement('div', 'campus-gallery__viewport');
  viewport.tabIndex = 0;
  viewport.setAttribute('aria-describedby', `${id}-hint`);
  const floor = textElement('div', 'campus-gallery__floor');
  floor.setAttribute('aria-hidden', 'true');
  const ring = textElement('div', 'campus-gallery__ring');
  const cards = scenes.map((key, index) => {
    const card = textElement('div', 'campus-gallery__card');
    card.setAttribute('role', 'group');
    const button = makeButton('campus-gallery__image-button');
    button.tabIndex = -1;
    const image = textElement('img', 'campus-gallery__image');
    image.width = 1672;
    image.height = 941;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.draggable = false;
    const requestedImage = imageFor(key);
    let temporary = !requestedImage;
    if (requestedImage || fallbackImage) image.src = requestedImage || fallbackImage;
    listen(image, 'error', () => {
      if (!temporary && fallbackImage) {
        temporary = true;
        image.src = fallbackImage;
        image.alt = COPY[language].scenes[1].alt;
        if (activeIndex === index) updateCaption();
      }
    });
    button.append(image);
    card.append(button);
    ring.append(card);
    listen(button, 'click', (event) => {
      if (performance.now() < suppressClickUntil) { event.preventDefault(); return; }
      userPaused = true;
      select(index);
    });
    return { card, button, image, get temporary() { return temporary; } };
  });
  viewport.append(floor, ring);

  const caption = textElement('div', 'campus-gallery__caption');
  caption.setAttribute('aria-atomic', 'true');
  const position = textElement('span', 'campus-gallery__position');
  position.setAttribute('aria-hidden', 'true');
  const captionCopy = textElement('div', 'campus-gallery__caption-copy');
  const title = textElement('h3', 'campus-gallery__title');
  const description = textElement('p', 'campus-gallery__description');
  captionCopy.append(title, description);
  caption.append(position, captionCopy);

  const controls = textElement('div', 'campus-gallery__controls');
  const previous = makeButton('campus-gallery__arrow');
  const next = makeButton('campus-gallery__arrow');
  const dots = textElement('div', 'campus-gallery__dots');
  dots.setAttribute('role', 'group');
  const dotButtons = scenes.map((_, index) => {
    const button = makeButton('campus-gallery__dot');
    button.append(textElement('span', 'campus-gallery__dot-mark'));
    listen(button, 'click', () => { userPaused = true; select(index); });
    dots.append(button);
    return button;
  });
  const hint = textElement('p', 'campus-gallery__hint');
  hint.id = `${id}-hint`;
  controls.append(previous, dots, next);
  const footer = textElement('div', 'campus-gallery__footer');
  footer.append(controls, hint);
  root.append(top, viewport, caption, footer);
  container.replaceChildren(root);

  const canAutoplay = () => !disposed && !reduce && !userPaused && !hoverPaused && inView && !document.hidden && !pointer?.dragging;
  function updateCaption() {
    const copy = COPY[language];
    title.textContent = copy.scenes[activeIndex].title;
    description.textContent = cards[activeIndex].temporary ? copy.temporary : copy.scenes[activeIndex].description;
    position.textContent = `${String(activeIndex + 1).padStart(2, '0')} / 05`;
  }
  function updateControls() {
    const copy = COPY[language];
    const paused = userPaused || reduce;
    motionButton.disabled = reduce;
    motionText.textContent = reduce ? copy.reduced : paused ? copy.resume : copy.pause;
    motionButton.setAttribute('aria-label', motionText.textContent);
    motionIcon.textContent = reduce ? '↔' : paused ? '▷' : 'Ⅱ';
    root.classList.toggle('is-reduced', reduce);
    caption.setAttribute('aria-live', canAutoplay() ? 'off' : 'polite');
  }
  function updateActive(index) {
    activeIndex = wrap(index);
    cards.forEach(({ card }, i) => {
      card.classList.toggle('is-current', i === activeIndex);
      card.setAttribute('aria-hidden', String(i !== activeIndex));
    });
    dotButtons.forEach((button, i) => button.setAttribute('aria-pressed', String(i === activeIndex)));
    updateCaption();
  }
  function renderAngle() {
    ring.style.transform = `translateZ(${-radius}px) rotateY(${angle}deg)`;
    const nearest = wrap(Math.round(-angle / (stepAngle * direction)));
    if (nearest !== activeIndex) updateActive(nearest);
  }
  function clearTimer() { if (timer) clearTimeout(timer); timer = 0; }
  function scheduleRotation() {
    clearTimer();
    if (canAutoplay() && !flight) timer = window.setTimeout(() => {
      timer = 0;
      if (canAutoplay()) move(1, 'auto');
    }, 4700);
  }
  function cancelFlight() {
    flight = null;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    root.classList.remove('is-moving');
  }
  function animate(time) {
    raf = 0;
    if (disposed || !flight) return;
    if (!inView || document.hidden || (flight.kind === 'auto' && !canAutoplay())) {
      flight.pausedAt ??= time;
      root.classList.remove('is-moving');
      return;
    }
    if (flight.pausedAt !== null) {
      flight.started += time - flight.pausedAt;
      flight.pausedAt = null;
    }
    const progress = Math.min(1, (time - flight.started) / flight.duration);
    const eased = progress * progress * (3 - 2 * progress);
    angle = flight.from + (flight.to - flight.from) * eased;
    renderAngle();
    if (progress < 1) {
      root.classList.add('is-moving');
      raf = requestAnimationFrame(animate);
    } else {
      angle = flight.to;
      cancelFlight();
      renderAngle();
      updateControls();
      scheduleRotation();
    }
  }
  function syncMotion() {
    if (disposed) return;
    if (inView && !imagesPrimed) {
      imagesPrimed = true;
      // Load the five small WebP assets when the gallery enters view, before a
      // rear photograph rotates forward. They remain lazy while offscreen.
      cards.forEach(({ image }) => { image.loading = 'eager'; });
    }
    updateControls();
    if (!canAutoplay()) clearTimer();
    if (flight) {
      if (inView && !document.hidden && (flight.kind !== 'auto' || canAutoplay())) {
        if (!raf) raf = requestAnimationFrame(animate);
      } else {
        // Record the pause immediately. Background tabs may suspend RAF before
        // animate can run, and otherwise return with a time-based visual jump.
        flight.pausedAt ??= performance.now();
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        root.classList.remove('is-moving');
      }
    } else if (!flight) scheduleRotation();
  }
  function goToAngle(target, kind = 'manual') {
    clearTimer();
    cancelFlight();
    if (reduce || Math.abs(target - angle) < 0.01) {
      angle = target;
      renderAngle();
      updateControls();
      scheduleRotation();
      return;
    }
    flight = { from: angle, to: target, kind, started: performance.now(), duration: kind === 'auto' ? 1000 : 720, pausedAt: null };
    root.classList.add('is-moving');
    updateControls();
    raf = requestAnimationFrame(animate);
  }
  function select(index) {
    const base = -wrap(index) * stepAngle * direction;
    goToAngle(base + Math.round((angle - base) / 360) * 360);
  }
  function move(amount, kind = 'manual') {
    const snapped = Math.round(angle / stepAngle) * stepAngle;
    goToAngle(snapped - amount * stepAngle * direction, kind);
  }

  function measure() {
    if (disposed) return;
    const width = viewport.getBoundingClientRect().width;
    if (width < 1) return;
    const mobile = width < 600;
    const spacing = mobile ? 1.02 : 1.13;
    const perspective = Math.max(660, width * 2.2);
    cardWidth = Math.min(660, width * (mobile ? 0.85 : 0.78));
    // A real five-sided Y ring. Desktop fits the swept side-card envelope.
    // Mobile gives the front photograph 85% of the viewport and lets angled
    // neighbours crop at the edges; fitting every corner made it too small.
    // Radius follows DeSandro's regular-polygon construction plus spacing.
    for (let pass = 0; !mobile && pass < 5; pass += 1) {
      radius = (cardWidth / 2) / Math.tan(Math.PI / count) * spacing;
      let extent = cardWidth / 2;
      // Check intermediate angles too: a half-turned photograph can project
      // wider than either resting neighbour during a carousel transition.
      for (let degrees = 0; degrees <= 80; degrees += 4) {
        const radians = degrees * Math.PI / 180;
        for (const corner of [-cardWidth / 2, cardWidth / 2]) {
          const x = radius * Math.sin(radians) + corner * Math.cos(radians);
          const z = radius * (Math.cos(radians) - 1) - corner * Math.sin(radians);
          extent = Math.max(extent, Math.abs(x / (1 - z / perspective)));
        }
      }
      if (extent * 2 <= width * 0.96) break;
      cardWidth *= width * 0.96 / (extent * 2);
    }
    radius = (cardWidth / 2) / Math.tan(Math.PI / count) * spacing;
    const height = cardWidth * 941 / 1672;
    root.style.setProperty('--campus-card-width', `${cardWidth}px`);
    root.style.setProperty('--campus-card-height', `${height}px`);
    root.style.setProperty('--campus-scene-height', `${height + (mobile ? 82 : 98)}px`);
    viewport.style.perspective = `${perspective}px`;
    cards.forEach(({ card }, index) => { card.style.transform = `rotateY(${index * stepAngle * direction}deg) translateZ(${radius}px)`; });
    renderAngle();
  }
  function setLanguage(value) {
    if (disposed) return;
    language = value === 'en' ? 'en' : 'ar';
    direction = language === 'ar' ? -1 : 1;
    cancelFlight();
    angle = -activeIndex * stepAngle * direction;
    const copy = COPY[language];
    root.lang = language;
    root.dir = language === 'ar' ? 'rtl' : 'ltr';
    root.setAttribute('aria-label', copy.label);
    root.setAttribute('aria-roledescription', copy.carousel);
    viewport.setAttribute('aria-label', copy.label);
    note.textContent = copy.note;
    previous.textContent = direction === -1 ? '→' : '←';
    next.textContent = direction === -1 ? '←' : '→';
    previous.setAttribute('aria-label', copy.previous);
    next.setAttribute('aria-label', copy.next);
    dots.setAttribute('aria-label', copy.pick);
    hint.textContent = copy.hint;
    cards.forEach(({ card, button, image, temporary }, index) => {
      card.setAttribute('aria-roledescription', copy.slide);
      card.setAttribute('aria-label', `${index + 1} / ${count}: ${copy.scenes[index].title}`);
      button.setAttribute('aria-label', copy.scenes[index].title);
      image.alt = temporary ? copy.scenes[1].alt : copy.scenes[index].alt;
      dotButtons[index].setAttribute('aria-label', copy.scenes[index].title);
    });
    updateActive(activeIndex);
    measure();
    syncMotion();
  }

  listen(previous, 'click', () => { userPaused = true; move(-1); });
  listen(next, 'click', () => { userPaused = true; move(1); });
  listen(motionButton, 'pointerdown', () => { motionPointerIntent = !userPaused; });
  listen(motionButton, 'click', (event) => {
    // Pointer focus pauses before click dispatch. Preserve the action shown at
    // pointerdown so the first click on Pause cannot accidentally restart it.
    userPaused = event.detail > 0 && motionPointerIntent !== null ? motionPointerIntent : !userPaused;
    motionPointerIntent = null;
    syncMotion();
  });
  listen(root, 'pointerenter', (event) => { if (event.pointerType !== 'touch') { hoverPaused = true; syncMotion(); } });
  listen(root, 'pointerleave', (event) => { if (event.pointerType !== 'touch') { hoverPaused = false; syncMotion(); } });
  // Focus stops rotation until the user explicitly activates the start control.
  listen(root, 'focusin', () => { userPaused = true; syncMotion(); });
  listen(viewport, 'keydown', (event) => {
    let amount = 0;
    if (event.key === 'ArrowRight') amount = direction;
    if (event.key === 'ArrowLeft') amount = -direction;
    if (!amount && !['Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    userPaused = true;
    if (amount) move(amount);
    else select(event.key === 'Home' ? 0 : count - 1);
  });
  listen(viewport, 'pointerdown', (event) => {
    if (!event.isPrimary || event.button !== 0 || pointer) return;
    pointer = { id: event.pointerId, startX: event.clientX, startY: event.clientY, startAngle: angle, startIndex: activeIndex, dragging: false, vertical: false };
  });
  listen(viewport, 'pointermove', (event) => {
    if (!pointer || event.pointerId !== pointer.id || pointer.vertical) return;
    const dx = event.clientX - pointer.startX;
    const dy = event.clientY - pointer.startY;
    const dragFactor = stepAngle / cardWidth * 0.95;
    if (!pointer.dragging) {
      if (Math.abs(dy) > 6 && Math.abs(dy) > Math.abs(dx) * 1.1) { pointer.vertical = true; return; }
      if (Math.abs(dx) <= 6 || Math.abs(dx) <= Math.abs(dy) * 1.1) return;
      userPaused = true;
      clearTimer();
      cancelFlight();
      pointer.dragging = true;
      pointer.startAngle = angle - dx * dragFactor;
      viewport.setPointerCapture(event.pointerId);
      root.classList.add('is-dragging');
      updateControls();
    }
    event.preventDefault();
    angle = pointer.startAngle + dx * dragFactor;
    renderAngle();
  }, { passive: false });
  const endPointer = (event) => {
    if (!pointer || event.pointerId !== pointer.id) return;
    const gesture = pointer;
    pointer = null;
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    if (!gesture.dragging) { syncMotion(); return; }
    root.classList.remove('is-dragging');
    suppressClickUntil = performance.now() + 250;
    let index = wrap(Math.round(-angle / (stepAngle * direction)));
    const dx = event.clientX - gesture.startX;
    if (event.type !== 'pointercancel' && index === gesture.startIndex && Math.abs(dx) > Math.max(28, cardWidth * 0.12)) index = wrap(index + (dx < 0 ? direction : -direction));
    select(index);
  };
  listen(window, 'pointerup', endPointer);
  listen(window, 'pointercancel', endPointer);
  listen(viewport, 'dragstart', (event) => event.preventDefault());
  listen(document, 'visibilitychange', syncMotion);
  listen(motionQuery, 'change', (event) => {
    reduce = event.matches;
    if (reduce) {
      const target = flight?.to ?? Math.round(angle / stepAngle) * stepAngle;
      cancelFlight();
      angle = target;
      renderAngle();
    }
    syncMotion();
  });
  const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
  resizeObserver?.observe(viewport);
  if (!resizeObserver) listen(window, 'resize', measure);
  const intersectionObserver = typeof IntersectionObserver !== 'undefined' ? new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting;
    syncMotion();
  }, { threshold: 0.08 }) : null;
  intersectionObserver?.observe(viewport);
  setLanguage(language);

  return {
    setLanguage,
    dispose() {
      if (disposed) return;
      // main disposes on pagehide and mounts again on a BFCache pageshow.
      // Retain the reader's chosen scene and explicit pause across that cycle.
      gallerySnapshots.set(container, { activeIndex, userPaused });
      disposed = true;
      clearTimer();
      cancelFlight();
      if (pointer && viewport.hasPointerCapture(pointer.id)) viewport.releasePointerCapture(pointer.id);
      pointer = null;
      abort.abort();
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      root.remove();
    },
  };
}
