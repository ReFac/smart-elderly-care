// Count visible, foreground tour time once per browser tab. Visits never require an account.
export function inviteVisitor(stage) {
  const seen = 'roomtour.contact-offer.v1';
  try { if (sessionStorage.getItem(seen)) return; } catch { /* Storage can be disabled. */ }
  const dialog = document.getElementById('tour-invite');
  const form = document.getElementById('tour-contact');
  const wechat = dialog.querySelector('.invite-wechat');
  const submit = form.querySelector('[type="submit"]');
  const error = form.querySelector('[role="alert"]');
  const remember = () => { try { sessionStorage.setItem(seen, '1'); } catch {} };
  let remaining = 5000;
  let started = null;
  let timer;
  let inView = false;
  let requested = false;
  let anonymous = false;
  let finished = false;

  function manualInput() {
    wechat.hidden = true;
    form.hidden = false;
  }
  const observer = new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting && entry.intersectionRatio > 0;
    schedule();
  }, { threshold: [0, .01] });
  function stopWatching() {
    finished = true;
    observer.disconnect();
    document.removeEventListener('visibilitychange', schedule);
    window.removeEventListener('blur', schedule);
    window.removeEventListener('focus', schedule);
  }
  async function checkSession() {
    requested = true;
    try {
      const response = await fetch('/api/public/visitor/status', { credentials: 'same-origin', cache: 'no-store' });
      const status = response.ok ? await response.json() : null;
      if (status?.signedIn !== false) {
        stopWatching();
        return;
      }
      if (/MicroMessenger/i.test(navigator.userAgent) && status.wechatContactLink) {
        form.hidden = true;
        wechat.hidden = false;
        wechat.querySelector('a').href = status.wechatContactLink;
      }
      anonymous = true;
      schedule();
    } catch { stopWatching(); }
  }
  function schedule() {
    clearTimeout(timer);
    if (started !== null) {
      remaining = Math.max(0, remaining - (performance.now() - started));
      started = null;
    }
    if (finished || !inView || document.hidden || !document.hasFocus()) return;
    if (remaining > 0) {
      started = performance.now();
      timer = setTimeout(schedule, Math.ceil(remaining));
    } else if (!requested) {
      checkSession();
    } else if (anonymous) {
      stopWatching();
      dialog.showModal();
      remember();
    }
  }
  observer.observe(stage);
  document.addEventListener('visibilitychange', schedule);
  window.addEventListener('blur', schedule);
  window.addEventListener('focus', schedule);
  dialog.querySelector('.invite-close').addEventListener('click', () => dialog.close());
  const receipt = dialog.querySelector('.invite-receipt');
  receipt.querySelector('button').addEventListener('click', () => dialog.close());
  wechat.querySelector('button').addEventListener('click', () => {
    manualInput();
    form.elements.phone.focus();
  });
  wechat.querySelector('a').addEventListener('click', () => {
    // The published mini program confirms authorization. Keep manual entry ready on return.
    manualInput();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    submit.disabled = true;
    error.textContent = '';
    try {
      const response = await fetch('/api/public/leads', {
        method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: 'consent', consent: true, phone: form.elements.phone.value.trim() }),
      });
      const result = await response.json();
      if (!response.ok || !result.received) throw new Error(result.error || '提交未成功，请稍后重试。');
      form.reset();
      form.hidden = true;
      receipt.hidden = false;
      receipt.querySelector('button').focus();
    } catch (failure) {
      error.textContent = failure.message || '未能连接，请稍后重试。';
    } finally {
      submit.disabled = false;
    }
  });
}
