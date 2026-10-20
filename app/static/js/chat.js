// Chat: send messages without reloading the page. Without JavaScript the form still posts normally.
(function () {
  const form = document.getElementById('chat-form');
  if (!form) return;
  const input = document.getElementById('chat-input');
  const log = document.getElementById('chat-log');
  const messages = document.getElementById('chat-messages');
  const draft = document.getElementById('chat-draft');
  const typing = document.getElementById('chat-typing');
  const errorBox = document.getElementById('chat-error');
  const revision = document.getElementById('chat-revision');
  const send = form.querySelector('button[type=submit]');
  const announcer = document.getElementById('chat-announce');
  const TIMEOUT_MS = 130000; // longer than the server's worst case for one reply
  const narrow = window.matchMedia('(max-width: 880px)');

  const scrollDown = () => {
    log.scrollTop = log.scrollHeight;
    // On phones the page itself scrolls, so keep the newest message and the message box in view.
    if (narrow.matches) form.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
  const showError = (text) => { errorBox.textContent = text || ''; errorBox.hidden = !text; };
  // While waiting, say what the assistant is doing, in plain words.
  const STAGES = ['Reading your request…', 'Checking the menu…', 'Pricing your draft…', 'Almost there…'];
  const label = document.getElementById('chat-typing-label');
  let stageTimer = null;
  const runStages = (on) => {
    clearInterval(stageTimer);
    if (!label) return;
    let i = 0;
    label.textContent = STAGES[0];
    if (on) stageTimer = setInterval(() => { i = Math.min(i + 1, STAGES.length - 1); label.textContent = STAGES[i]; }, 2600);
  };
  const setBusy = (busy) => {
    send.disabled = busy; input.readOnly = busy; typing.hidden = !busy; runStages(busy);
    // While a reply is pending the draft may change, so it can't be sent or reset.
    document.querySelectorAll('#chat-draft button, .workspace-head button').forEach((b) => { b.disabled = busy; });
    document.body.classList.toggle('is-busy', busy);
    if (busy) document.getElementById('start-over')?.removeAttribute('open');
    if (busy) scrollDown();
  };
  const announce = (html) => {
    if (!announcer) return;
    const box = document.createElement('div');
    box.innerHTML = html || '';
    const replies = box.querySelectorAll('.bubble-assistant');
    const last = replies[replies.length - 1];
    announcer.textContent = last ? 'Assistant: ' + last.textContent.trim() : '';
  };

  function bubble(text) {
    const div = document.createElement('div');
    div.className = 'bubble bubble-customer';
    text.split(/\n+/).forEach((line) => { const p = document.createElement('p'); p.textContent = line; div.appendChild(p); });
    messages.querySelector('.starters')?.remove();
    messages.appendChild(div);
  }

  // The confirm box is checked here so the message matches the page instead of the browser's bubble.
  function prepareDraft() {
    draft.querySelectorAll('[data-confirm-form]').forEach((f) => { f.noValidate = true; });
  }

  function apply(data, fresh) {
    if (data.messages) { messages.innerHTML = data.messages; announce(data.messages); }
    if (data.draft) {
      const before = draft.querySelector('[data-total]')?.dataset.total || '';
      draft.innerHTML = data.draft;
      prepareDraft();
      const ticket = draft.querySelector('[data-total]');
      // After a real reply, the receipt "prints" again whenever the priced total changes.
      if (fresh && ticket && ticket.dataset.total && ticket.dataset.total !== before) ticket.classList.add('is-printing');
    }
    if (data.revision) revision.value = data.revision;
    const jump = document.getElementById('chat-jump');
    if (jump) jump.hidden = !data.ready;
    showError(data.error);
    requestAnimationFrame(scrollDown);
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;
    showError('');
    const body = new FormData(form);
    bubble(text);
    input.value = '';
    setBusy(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch(form.action, { method: 'POST', body, headers: { 'X-Requested-With': 'fetch' },
                                                   credentials: 'same-origin', signal: controller.signal });
      if (response.status === 401) { window.location.href = '/login?next=/chat'; return; }
      let data = {};
      try { data = await response.json(); } catch (_) { data = {}; }
      if (!response.ok && !data.messages) {
        showError(data.error || 'Something went wrong sending that. Try again in a moment.');
        input.value = text;
        messages.lastElementChild?.remove();
        return;
      }
      // A refusal (limit, another tab) shows the saved conversation and keeps what was typed.
      apply(data, response.ok);
      const startOver = document.getElementById('start-over');
      if (startOver && response.ok) startOver.hidden = false;
      if (data.error) input.value = text;
    } catch (err) {
      showError(err && err.name === 'AbortError'
        ? 'The assistant is taking too long. Reload the page to see if your message went through.'
        : 'Connection lost. Check your internet and try again.');
      input.value = text;
      messages.lastElementChild?.remove();
    } finally {
      clearTimeout(timer);
      setBusy(false);
      input.focus();
    }
  });

  // The draft form posts normally; check the confirm box first and stop a double click.
  draft.addEventListener('submit', (event) => {
    const target = event.target;
    const box = target.querySelector('input[name=confirm]');
    const hint = target.querySelector('[data-hint]');
    if (box && !box.checked) {
      event.preventDefault();
      if (hint) hint.hidden = false;
      target.classList.add('is-invalid');
      box.focus();
      return;
    }
    const button = target.querySelector('button[type=submit]');
    if (button) setTimeout(() => { button.disabled = true; button.textContent = 'Sending…'; }, 0);
  });
  draft.addEventListener('change', (event) => {
    if (event.target.name !== 'confirm') return;
    const target = event.target.form;
    target.classList.remove('is-invalid');
    const hint = target.querySelector('[data-hint]');
    if (hint) hint.hidden = true;
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // Example requests: with JavaScript they fill the box so the customer can edit before sending.
  messages.addEventListener('click', (event) => {
    const starter = event.target.closest('.starter');
    if (!starter) return;
    event.preventDefault();
    input.value = starter.dataset.text;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  });

  prepareDraft();
  log.scrollTop = log.scrollHeight;
})();
