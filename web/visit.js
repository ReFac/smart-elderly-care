const visit = document.querySelector('#visit-form');
const callback = document.querySelector('#callback-form');
const dialog = document.querySelector('#callback');
const status = document.querySelector('#load-error');
const date = visit.elements.day;
const time = visit.elements.time;
const localDay = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());
date.min = localDay;

for (let hour = 0; hour < 24; hour++) {
  for (const minute of ['00', '30']) {
    const label = String(hour).padStart(2, '0') + ':' + minute;
    time.add(new Option(label, label));
  }
}
function updatePreference() {
  time.required = Boolean(date.value);
  date.required = Boolean(time.value);
}
date.addEventListener('change', updatePreference);
time.addEventListener('change', updatePreference);
document.querySelector('#open-callback').addEventListener('click', () => {
  callback.elements.campusId.value = visit.elements.campusId.value;
  dialog.showModal();
});
document.querySelector('#close').addEventListener('click', () => dialog.close());

const pick = document.querySelector('#pick-phone');
if (window.isSecureContext && typeof navigator.contacts?.select === 'function') {
  pick.hidden = false;
  pick.addEventListener('click', async () => {
    const error = callback.querySelector('.form-error');
    error.textContent = '';
    try {
      const [card] = await navigator.contacts.select(['tel'], { multiple: false });
      if (card?.tel?.length) callback.elements.phone.value = card.tel[0];
      else if (card) error.textContent = '这张名片没有电话号码，请手动填写。';
    } catch (e) {
      if (e.name !== 'AbortError') error.textContent = '可手动填写手机号。';
    }
  });
}

function enableForm(form, source) {
  const send = form.querySelector('[type=submit]');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (send.disabled || !form.reportValidity()) return;
    const value = name => form.elements[name].value.trim();
    const payload = { source, campusId: value('campusId'), phone: value('phone'), consent: form.elements.consent.checked };
    if (source === 'visit') {
      payload.name = value('name');
      if (value('note')) payload.note = value('note');
      if (value('day') && value('time')) payload.preferredAt = value('day') + 'T' + value('time');
    }
    const error = form.querySelector('.form-error');
    error.textContent = '';
    send.disabled = true;
    try {
      const response = await fetch('/api/public/leads', {
        method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '提交失败，请重试。');
      form.reset();
      form.hidden = true;
      const receipt = document.getElementById(source === 'visit' ? 'visit-receipt' : 'callback-receipt');
      receipt.hidden = false;
      receipt.focus();
    } catch (cause) {
      error.textContent = cause.message || '连接失败，请稍后重试。';
      send.disabled = false;
    }
  });
}
enableForm(visit, 'visit');
enableForm(callback, 'consent');

async function load() {
  try {
    const response = await fetch('/api/public/reception', { credentials: 'omit' });
    if (!response.ok) throw new Error();
    const { institutionName, campuses } = await response.json();
    if (!campuses?.length) throw new Error();
    document.querySelectorAll('[data-brand]').forEach(element => { element.textContent = institutionName; });
    document.title = institutionName + ' · 养老照护与参观';
    for (const form of [visit, callback]) {
      const select = form.elements.campusId;
      select.replaceChildren(...campuses.map(campus => new Option(campus.name, campus.id)));
      select.disabled = false;
      form.querySelector('[type=submit]').disabled = false;
    }
  } catch {
    status.textContent = '院区信息暂时无法载入，请刷新后重试。';
  }
}
load();
