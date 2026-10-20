// Owner menu: mark edited fields, count unsaved changes, find a dish, and warn before leaving
// with unsaved edits. Without JavaScript the form still saves and "Discard" still resets it.
(function () {
  const form = document.querySelector('[data-menu-form]');
  if (!form) return;
  const status = form.querySelector('[data-save-status]');
  const bar = form.querySelector('[data-save-bar]');
  const save = form.querySelector('[data-save]');
  const discard = form.querySelector('[data-discard]');
  const fields = Array.from(form.querySelectorAll('input[name^="m:"], textarea[name^="m:"]'));
  let submitting = false;
  form.classList.add('js-ready');

  // compare with what is saved (not with what the page was drawn with: after an error it shows your typing)
  const saved = (el) => (el.type === 'checkbox' ? el.dataset.saved === 'true' : el.dataset.saved ?? el.defaultValue);
  const changed = (el) => (el.type === 'checkbox' ? el.checked !== saved(el) : el.value.trim() !== String(saved(el)).trim());

  function refresh() {
    let count = 0;
    fields.forEach((el) => {
      const dirty = changed(el);
      if (dirty) count += 1;
      (el.closest('.price-field, .switch') || el).classList.toggle('is-dirty', dirty);
    });
    form.querySelectorAll('[data-dish]').forEach((dish) => {
      const on = dish.querySelector('.dish-head .switch input');
      dish.classList.toggle('is-off', on && !on.checked);
      dish.classList.toggle('is-edited', !!dish.querySelector('.is-dirty'));
      dish.querySelectorAll('tbody tr').forEach((row) => {
        const box = row.querySelector('.switch input');
        row.classList.toggle('is-off', box && !box.checked);
      });
    });
    form.classList.toggle('has-changes', count > 0);
    bar.classList.toggle('is-active', count > 0);
    status.textContent = count ? `${count} unsaved change${count === 1 ? '' : 's'}` : 'All changes saved';
    discard.disabled = count === 0;
    save.setAttribute('aria-disabled', count === 0 ? 'true' : 'false');
    return count;
  }

  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  form.addEventListener('reset', (event) => { // put every field back to what is saved
    event.preventDefault();
    fields.forEach((el) => { if (el.type === 'checkbox') el.checked = saved(el); else el.value = saved(el); });
    form.querySelectorAll('.field-error').forEach((e) => e.remove());
    form.querySelectorAll('[aria-invalid="true"]').forEach((e) => { e.removeAttribute('aria-invalid'); (e.closest('.price-field') || e).classList.remove('is-invalid'); });
    form.querySelectorAll('.dish-desc').forEach((area) => area.dispatchEvent(new Event('input')));
    refresh();
  });
  form.addEventListener('submit', (event) => {
    if (refresh() === 0) { event.preventDefault(); status.textContent = 'Nothing to save yet.'; return; }
    submitting = true;
    setTimeout(() => { save.disabled = true; save.textContent = 'Saving…'; }, 0);
  });
  window.addEventListener('beforeunload', (event) => {
    if (!submitting && refresh() > 0) { event.preventDefault(); event.returnValue = ''; }
  });
  // Cmd/Ctrl+S saves, like a document
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      form.requestSubmit(save);
    }
  });

  // descriptions grow with their text
  form.querySelectorAll('.dish-desc').forEach((area) => {
    const fit = () => { area.style.height = 'auto'; area.style.height = area.scrollHeight + 2 + 'px'; };
    area.addEventListener('input', fit); fit();
  });

  // find a dish
  const search = document.querySelector('[data-menu-search]');
  const empty = form.querySelector('[data-menu-empty]');
  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      let shown = 0;
      form.querySelectorAll('[data-menu-section]').forEach((section) => {
        let any = false;
        section.querySelectorAll('[data-dish]').forEach((dish) => {
          const hit = !q || dish.dataset.search.includes(q) || dish.querySelector('.dish-name').value.toLowerCase().includes(q);
          dish.hidden = !hit;
          if (hit) { any = true; shown += 1; }
        });
        section.hidden = !any;
      });
      empty.hidden = shown > 0;
    });
  }

  // after a failed save, take the owner to the first problem
  const firstError = form.querySelector('[aria-invalid="true"]');
  if (firstError) { firstError.scrollIntoView({ block: 'center' }); firstError.focus({ preventScroll: true }); }
  refresh();
})();
