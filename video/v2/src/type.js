import './type.css';

const logoUrl = new URL('../../../assets/brand/logos/mawrid-primary-white.svg', import.meta.url).href;

const SHOTS = [
  { key: 'hero', start: 0, end: 6, lines: ['مياه الوضوء،', 'موردٌ للري.'], eyebrow: 'نموذج برمجي تفاعلي' },
  { key: 'source', start: 6, end: 14, lines: ['من المصدر،', 'تبدأ الرحلة.'] },
  { key: 'treatment', start: 14, end: 24, lines: ['مسار واضح.', 'ومراقبة مستمرة.'], caption: 'ترشيح أولي · رمل وكربون · تعقيم' },
  { key: 'sensor', start: 24, end: 31, lines: ['قبل الري…', 'نتحقّق.'] },
  { key: 'missing', start: 31, end: 36, lines: ['قراءة مفقودة.'], reading: true },
  { key: 'stop', start: 36, end: 44, lines: ['يتوقّف', 'الري الافتراضي.'] },
  { key: 'record', start: 44, end: 51, lines: ['كل قرار له سبب.', 'وكل حدث له سجل.'] },
  { key: 'end', start: 51, end: 60, lines: ['جرّب مورد.'], url: true },
];

const clamp = (x, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, x));
const easeOutCubic = t => 1 - (1 - clamp(t)) ** 3;
const easeInCubic = t => clamp(t) ** 3;
const easeSmooth = t => { const x = clamp(t); return x * x * (3 - 2 * x); };

function make(tag, className, parent, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text) node.textContent = text;
  parent.appendChild(node);
  return node;
}

/**
 * Deterministic, seekable typography over the full-bleed plant scene.
 * Rendering at a given t never depends on previous frames, CSS animations or timers.
 * Call after scene setup, and await document.fonts.ready before capture.
 */
export function setupTypography(container) {
  const root = make('div', 'film-type', container);
  root.setAttribute('aria-label', 'مورد — فيلم النموذج البرمجي');
  const identity = make('img', 'film-type__identity', root);
  identity.src = logoUrl;
  identity.alt = 'مورد';
  const disclosure = make('p', 'film-type__disclosure', root, 'محاكاة برمجية · لا قياسات ميدانية');
  const shots = SHOTS.map(spec => {
    const node = make('section', `film-type__shot film-type__shot--${spec.key}`, root);
    node.dataset.shot = spec.key;
    let eyebrow;
    if (spec.eyebrow) {
      eyebrow = make('p', 'film-type__eyebrow', node);
      make('i', 'film-type__fine-rule', eyebrow);
      eyebrow.append(document.createTextNode(spec.eyebrow));
    }
    const title = make('h1', 'film-type__title', node);
    const lines = spec.lines.map(text => {
      const mask = make('span', 'film-type__mask', title);
      return make('span', 'film-type__line', mask, text);
    });
    let extra;
    if (spec.caption) extra = make('span', 'film-type__caption', node, spec.caption);
    if (spec.reading) {
      extra = make('div', 'film-type__reading', node);
      make('div', 'film-type__reading-label', extra, 'حالة توضيحية · قراءة الكلور');
      const value = make('div', 'film-type__reading-value', extra);
      value.append(document.createTextNode('— '));
      make('small', '', value, 'mg/L');
    }
    if (spec.url) extra = make('div', 'film-type__url', node, 'sultalfaifi.com/mawrid-water-reuse/experience/');
    return { ...spec, node, lines, extra, eyebrow };
  });
  const boundary = make('p', 'film-type__boundary', root, 'محاكاة برمجية؛ الاختبار الميداني هو القادم.');
  let currentTime = 0;

  function update(tSeconds) {
    const t = Number.isFinite(tSeconds) ? clamp(tSeconds, 0, 60) : 0;
    currentTime = t;
    const brandIntro = easeSmooth(t / 1.2);
    identity.style.opacity = `${brandIntro}`;
    disclosure.style.opacity = `${.25 + brandIntro * .75}`;
    for (const shot of shots) {
      // A short outgoing fade clears the copy before the next camera cut.
      const local = t - shot.start;
      const isLast = shot.key === 'end';
      const visible = local >= 0 && t <= shot.end;
      shot.node.style.visibility = visible ? 'visible' : 'hidden';
      if (!visible) {
        shot.node.style.opacity = '0';
        continue;
      }
      const entrance = easeOutCubic(local / .85);
      const exit = isLast ? 1 : 1 - easeInCubic((t - (shot.end - .48)) / .48);
      shot.node.style.opacity = `${exit}`;
      shot.node.style.transform = `translateY(${-12 * (1 - exit)}px)`;
      for (let index = 0; index < shot.lines.length; index++) {
        const reveal = easeOutCubic((local - index * .14) / 1.0);
        const y = (1 - reveal) * 112;
        shot.lines[index].style.transform = `translateY(${y}%)`;
        shot.lines[index].style.opacity = `${clamp(reveal * 3)}`;
      }
      if (shot.eyebrow) {
        shot.eyebrow.style.opacity = `${entrance}`;
        shot.eyebrow.style.transform = `translateY(${12 * (1 - entrance)}px)`;
      }
      if (shot.extra) {
        const delay = shot.reading ? .8 : shot.url ? .65 : .95;
        const reveal = easeSmooth((local - delay) / .8);
        shot.extra.style.opacity = `${reveal}`;
        shot.extra.style.transform = `translateY(${18 * (1 - reveal)}px)`;
      }
    }
    boundary.style.opacity = `${easeSmooth((t - 53) / 1.1)}`;
    boundary.style.transform = `translateY(${14 * (1 - easeSmooth((t - 53) / 1.1))}px)`;
  }

  function diagnostics() {
    const base = root.getBoundingClientRect();
    const inspect = node => {
      const r = node.getBoundingClientRect();
      return {
        text: node.textContent,
        x: Math.round(r.left - base.left), y: Math.round(r.top - base.top),
        width: Math.round(r.width), height: Math.round(r.height),
        scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
        withinFrame: r.left >= base.left && r.top >= base.top && r.right <= base.right && r.bottom <= base.bottom,
        fitsWidth: node.scrollWidth <= node.clientWidth + 2,
      };
    };
    const active = shots.filter(shot => shot.node.style.visibility === 'visible');
    return {
      t: currentTime,
      fontsReady: document.fonts.status === 'loaded',
      arabicFontLoaded: document.fonts.check('600 100px "Mawrid Film Arabic"'),
      active: active.map(shot => ({ key: shot.key, lines: shot.lines.map(inspect), extra: shot.extra ? inspect(shot.extra) : null })),
      identityLoaded: identity.complete && identity.naturalWidth > 0,
      disclosure: inspect(disclosure),
      boundary: inspect(boundary),
    };
  }
  update(0);
  return { update, diagnostics, element: root };
}
