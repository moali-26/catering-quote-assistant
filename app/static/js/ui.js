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
