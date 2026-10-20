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

  const scrollDown = () => { log.scrollTop = log.scrollHeight; };
  const showError = (text) => { errorBox.textContent = text || ''; errorBox.hidden = !text; };
  const setBusy = (busy) => {
    send.disabled = busy; input.readOnly = busy; typing.hidden = !busy;
    // While a reply is pending the draft may change, so it can't be sent or reset.
    document.querySelectorAll('#chat-draft button, .workspace-head button').forEach((b) => { b.disabled = busy; });
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

  function apply(data) {
    if (data.messages) { messages.innerHTML = data.messages; announce(data.messages); }
    if (data.draft) {
      const before = draft.querySelector('[data-total]')?.dataset.total || '';
      draft.innerHTML = data.draft;
      const ticket = draft.querySelector('[data-total]');
      // The receipt "prints" again whenever the priced total changes.
      if (ticket && ticket.dataset.total && ticket.dataset.total !== before) ticket.classList.add('is-printing');
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
      apply(data);
      if (data.reload) { window.location.reload(); return; }
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

  // Without fetch the draft form posts normally; stop a double click from sending it twice.
  draft.addEventListener('submit', (event) => {
    const button = event.target.querySelector('button[type=submit]');
    if (button) setTimeout(() => { button.disabled = true; button.textContent = 'Sending…'; }, 0);
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  messages.addEventListener('click', (event) => {
    const starter = event.target.closest('.starter');
    if (!starter) return;
    input.value = starter.dataset.text;
    input.focus();
  });

  scrollDown();
})();
