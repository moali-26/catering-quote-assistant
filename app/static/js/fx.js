// Desktop-only finish: a themed cursor and light/depth on the paper tickets.
// Off for touch screens and for anyone who prefers reduced motion; purely decorative.
// The native cursor is only replaced while the pointer is actually over the page.
(function () {
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)');
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!fine.matches || calm.matches) return;

  const root = document.documentElement;
  let mx = 0, my = 0, rx = 0, ry = 0, seen = false;
  // A footer switch lets anyone keep their own system cursor; the choice stays in this browser.
  let enabled = true;
  try { enabled = localStorage.getItem('cqa-fx') !== 'off'; } catch (_) { /* storage blocked: keep effects on */ }
  const toggle = document.querySelector('[data-fx-toggle]');
  const label = () => { if (toggle) { toggle.textContent = 'Pointer effects: ' + (enabled ? 'on' : 'off'); toggle.setAttribute('aria-pressed', String(enabled)); } };
  if (toggle) {
    toggle.hidden = false; label();
    toggle.addEventListener('click', () => {
      enabled = !enabled;
      try { localStorage.setItem('cqa-fx', enabled ? 'on' : 'off'); } catch (_) { /* ignore */ }
      label();
      if (!enabled) { hide(); calmDown(); }
    });
  }

  // ---------- cursor ----------
  const ring = document.createElement('div');
  const dot = document.createElement('div');
  ring.className = 'fx-ring is-gone';
  dot.className = 'fx-dot is-gone';
  ring.setAttribute('aria-hidden', 'true');
  dot.setAttribute('aria-hidden', 'true');
  document.body.append(ring, dot);

  const LINKS = 'a, button, summary, label, select, .starter, [role="button"]';
  const TICKET_LINKS = '.pass-ticket a, .quote-row a';
  const TEXT = 'input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), textarea, [contenteditable="true"]';
  const DARK = '.kitchen-band, .kitchen-detail-band, .cta-band, .role-owner .site-header, .flash-band, .bubble-customer, .btn-primary, .btn-danger';
  let lastTarget = null;

  function classify(target) {
    if (target === lastTarget || !(target instanceof Element)) return;
    lastTarget = target;
    const onText = !!target.closest(TEXT);
    const onTicket = !onText && !!target.closest(TICKET_LINKS);
    const onLink = !onText && !onTicket && !!target.closest(LINKS);
    const dark = !!target.closest(DARK);
    ring.classList.toggle('is-text', onText); dot.classList.toggle('is-text', onText);
    ring.classList.toggle('is-ticket', onTicket);
    ring.classList.toggle('is-link', onLink); dot.classList.toggle('is-link', onLink);
    ring.classList.toggle('is-dark', dark); dot.classList.toggle('is-dark', dark);
  }

  function show() {
    root.classList.add('fx-on');
    ring.classList.remove('is-gone'); dot.classList.remove('is-gone');
  }
  function hide() {
    root.classList.remove('fx-on');   // hand the pointer back to the system cursor
    ring.classList.add('is-gone'); dot.classList.add('is-gone');
    seen = false;
  }

  document.addEventListener('pointermove', (e) => {
    if (!enabled || (e.pointerType && e.pointerType !== 'mouse')) return;
    mx = e.clientX; my = e.clientY;
    if (!seen) { seen = true; rx = mx; ry = my; show(); }
    dot.style.transform = `translate3d(${mx}px, ${my}px, 0)`;
    classify(e.target);
    wake();
  }, { passive: true });
  root.addEventListener('pointerleave', hide);
  window.addEventListener('blur', hide);
  document.addEventListener('pointerdown', (e) => {
    if (!enabled || !seen) return;
    ring.classList.add('is-down');
    if (e.target instanceof Element && e.target.closest(TEXT)) return;
    const ink = document.createElement('span');   // a little ink "stamp" where you click
    ink.className = 'fx-ink' + (ring.classList.contains('is-dark') ? ' is-dark' : '');
    ink.style.left = e.clientX + 'px'; ink.style.top = e.clientY + 'px';
    document.body.appendChild(ink);
    ink.addEventListener('animationend', () => ink.remove());
  });
  document.addEventListener('pointerup', () => ring.classList.remove('is-down'));

  // ---------- paper: tilt, sheen, magnetic buttons ----------
  const hero = document.querySelector('.hero');
  let papers = [], magnets = [], listStale = true, rectsStale = true;
  let rects = [], mrects = [], hrect = null;
  new MutationObserver(() => { listStale = true; }).observe(document.body, { childList: true, subtree: true });
  // positions only change on scroll, resize or page updates, so measure then (and now and again as a safety net)
  const restale = () => { rectsStale = true; };
  window.addEventListener('resize', restale);
  setInterval(restale, 1000);

  function refresh() {
    listStale = false;
    papers = Array.from(document.querySelectorAll('[data-tilt], [data-sheen]')).map((el) => {
      const paper = el.matches('.ticket') ? el : el.querySelector('.ticket');
      let sheen = paper && paper.querySelector(':scope > .fx-sheen');
      if (paper && !sheen) {
        sheen = document.createElement('span'); sheen.className = 'fx-sheen'; sheen.setAttribute('aria-hidden', 'true');
        paper.appendChild(sheen);
      }
      return { el, sheen, tilt: el.hasAttribute('data-tilt'), lit: false, key: '' };
    }).filter((p) => p.sheen);
    magnets = Array.from(document.querySelectorAll('[data-magnetic]')).map((el) => ({ el, key: '' }));
    listStale = false; // our own sheen insertions don't count as a change
  }

  function calmDown() { // put every tilted, lit or pulled element back at rest
    papers.forEach((p) => { p.el.classList.remove('is-lit'); p.lit = false; p.key = '';
      ['--rx', '--ry', '--shx', '--shy'].forEach((v) => p.el.style.removeProperty(v)); });
    magnets.forEach((m) => { m.key = ''; m.el.style.removeProperty('--mgx'); m.el.style.removeProperty('--mgy'); });
  }

  const NEAR = 150; // only paper near the pointer is touched
  const clamp = (v, m) => Math.max(-m, Math.min(m, v));
  let running = false, dirty = true;
  function wake() { dirty = true; if (!running) { running = true; requestAnimationFrame(frame); } }
  window.addEventListener('scroll', () => { rectsStale = true; if (seen) wake(); }, { passive: true });
  document.addEventListener('scroll', restale, { passive: true, capture: true });

  function frame() {
    rx += (mx - rx) * 0.22; ry += (my - ry) * 0.22;
    ring.style.transform = `translate3d(${rx.toFixed(1)}px, ${ry.toFixed(1)}px, 0)`;
    if (dirty) {
      dirty = false;
      if (listStale) { refresh(); rectsStale = true; }
      if (rectsStale) {
        // read every rectangle at once, before any writes, so the browser lays out once
        rectsStale = false;
        rects = papers.map((p) => p.el.getBoundingClientRect());
        mrects = magnets.map((m) => { const r = m.el.getBoundingClientRect(); const x = parseFloat(m.key.split(',')[0]) || 0, y = parseFloat(m.key.split(',')[1]) || 0; return new DOMRect(r.x - x, r.y - y, r.width, r.height); });
        hrect = hero && hero.getBoundingClientRect();
      }
      papers.forEach((p, i) => {
        const r = rects[i];
        const near = r.width && mx > r.left - NEAR && mx < r.right + NEAR && my > r.top - NEAR && my < r.bottom + NEAR;
        const lit = !!near && mx > r.left && mx < r.right && my > r.top && my < r.bottom;
        if (lit !== p.lit) { p.lit = lit; p.el.classList.toggle('is-lit', lit); }
        if (!near) return;
        const px = (mx - r.left) / r.width, py = (my - r.top) / r.height;
        const key = `${Math.round(px * 100)},${Math.round(py * 100)}`;
        if (key === p.key) return;
        p.key = key;
        p.sheen.style.setProperty('--sx', `${(px * 100).toFixed(0)}%`);
        p.sheen.style.setProperty('--sy', `${(py * 100).toFixed(0)}%`);
        if (p.tilt) {
          const dx = clamp((px - 0.5) * 2, 1), dy = clamp((py - 0.5) * 2, 1);
          p.el.style.setProperty('--ry', `${(dx * 4).toFixed(2)}deg`);
          p.el.style.setProperty('--rx', `${(-dy * 3).toFixed(2)}deg`);
          p.el.style.setProperty('--shx', `${(-dx * 12).toFixed(0)}px`);
          p.el.style.setProperty('--shy', `${(16 - dy * 5).toFixed(0)}px`);
        }
      });
      magnets.forEach((m, i) => {
        const r = mrects[i];
        const dx = mx - (r.left + r.width / 2), dy = my - (r.top + r.height / 2);
        const near = Math.abs(dx) < r.width / 2 + 40 && Math.abs(dy) < r.height / 2 + 30;
        const key = near ? `${clamp(dx * 0.08, 6).toFixed(1)},${clamp(dy * 0.15, 4).toFixed(1)}` : '0,0';
        if (key === m.key) return;
        m.key = key;
        const [x, y] = key.split(',');
        m.el.style.setProperty('--mgx', `${x}px`); m.el.style.setProperty('--mgy', `${y}px`);
      });
      if (hrect && my < hrect.bottom + 200) {
        hero.style.setProperty('--mx', `${(mx - hrect.left).toFixed(0)}px`);
        hero.style.setProperty('--my', `${(my - hrect.top).toFixed(0)}px`);
      }
    }
    // stop when the ring has caught up and nothing changed; the next move starts it again
    if (dirty || Math.abs(mx - rx) > 0.3 || Math.abs(my - ry) > 0.3) requestAnimationFrame(frame);
    else running = false;
  }
})();
