// Owner review: show how many checks are done and keep the approve button honest.
(function () {
  const form = document.querySelector('form[action$="/approve"]');
  if (!form) return;
  const boxes = Array.from(form.querySelectorAll('input[name=ack]'));
  const progress = form.querySelector('[data-check-progress]');
  const button = form.querySelector('button[type=submit]');
  if (!boxes.length || !progress) return;
  const update = () => {
    const done = boxes.filter((b) => b.checked).length;
    progress.hidden = false;
    progress.textContent = done === boxes.length ? 'All ' + done + ' checks done' : done + ' of ' + boxes.length + ' checks done';
    button.textContent = done === boxes.length ? 'Approve quote' : 'Approve quote (' + (boxes.length - done) + ' to go)';
  };
  boxes.forEach((b) => b.addEventListener('change', update));
  update();
})();
