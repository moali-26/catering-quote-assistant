// Header gets a soft shadow once the page scrolls under it.
(function () {
  const header = document.querySelector('.site-header');
  if (!header) return;
  const onScroll = () => header.classList.toggle('is-scrolled', window.scrollY > 4);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();

// Confirm popovers (<details class="confirm-pop">): add a way to back out, and close on Escape or a tap outside.
(function () {
  const pops = Array.from(document.querySelectorAll('details.confirm-pop'));
  if (!pops.length) return;
  pops.forEach((pop) => {
    const body = pop.querySelector('.confirm-pop-body');
    const action = body && body.querySelector('form');
    if (!body || !action) return;
    const keep = document.createElement('button');
    keep.type = 'button';
    keep.className = 'btn btn-small btn-quiet';
    keep.textContent = pop.dataset.keep || 'Cancel';
    keep.addEventListener('click', () => { pop.open = false; pop.querySelector('summary').focus(); });
    const row = document.createElement('div');
    row.className = 'confirm-pop-actions';
    action.replaceWith(row);
    row.append(keep, action);
    pop.addEventListener('toggle', () => { if (pop.open) keep.focus(); }); // the safe choice gets focus
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    pops.filter((p) => p.open).forEach((p) => { p.open = false; p.querySelector('summary').focus(); });
  });
  document.addEventListener('click', (event) => {
    pops.filter((p) => p.open && !p.contains(event.target)).forEach((p) => { p.open = false; });
  });
})();

// Home page menu: show the featured dishes first, with a button to expand to the full menu.
// Without JavaScript the whole menu stays visible.
(function () {
  const board = document.querySelector('.menu-board[data-collapsible]');
  const button = document.querySelector('.menu-more button');
  if (!board || !button) return;
  const set = (open) => {
    board.classList.toggle('is-collapsed', !open);
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? button.dataset.less : button.dataset.more;
  };
  set(false);
  button.hidden = false;
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') !== 'true';
    set(open);
    if (!open) board.scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
})();
