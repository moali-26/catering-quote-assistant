// Owner review: count the checks done, keep the approve button honest, and explain a blocked submit
// in the page's own style instead of the browser's validation bubble.
(function () {
  const form = document.querySelector('form[action$="/approve"]');
  if (!form) return;
  const boxes = Array.from(form.querySelectorAll('input[name=ack]'));
  const progress = form.querySelector('[data-check-progress]');
  const hint = form.querySelector('[data-hint]');
  const button = form.querySelector('button[type=submit]');
  if (!boxes.length || !progress) return;
  form.noValidate = true;
  const left = () => boxes.filter((b) => !b.checked).length;
  const update = () => {
    const done = boxes.length - left();
    progress.hidden = false;
    progress.textContent = left() ? done + ' of ' + boxes.length + ' checks done' : 'All ' + boxes.length + ' checks done';
    button.textContent = left() ? 'Approve quote (' + left() + ' to go)' : 'Approve quote';
    button.setAttribute('aria-disabled', left() ? 'true' : 'false');
    if (!left() && hint) { hint.hidden = true; form.classList.remove('is-invalid'); }
  };
  boxes.forEach((b) => b.addEventListener('change', update));
  form.addEventListener('submit', (event) => {
    if (left()) {
      event.preventDefault();
      if (hint) hint.hidden = false;
      form.classList.add('is-invalid');
      boxes.find((b) => !b.checked).focus();
      return;
    }
    setTimeout(() => { button.disabled = true; button.textContent = 'Approving…'; }, 0);
  });
  update();
})();
