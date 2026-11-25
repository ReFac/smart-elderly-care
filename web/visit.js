import {internationalDeployment, nameEditor} from './lib/international-profile.js';
import { publicPage, receptionInfo } from './public-site.js';

publicPage('养老照护与参观');

const visit = document.querySelector('#visit-form');
const callback = document.querySelector('#callback-form');
let visitorName;
if (internationalDeployment()) {
  const display = visit.elements.name;
  const row = display.closest('label');
  visitorName = nameEditor(display);
  row.replaceWith(visitorName.element);
  for (const telephone of document.querySelectorAll('input[type=tel]')) {
    telephone.placeholder = '+1 202 555 0100';
    telephone.maxLength = 40;
  }
}
const booking = document.querySelector('#visit-request');
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
function openBooking() {
  if (!booking.open) booking.showModal();
}
document.querySelector('#book-visit').addEventListener('click', openBooking);
for (const link of document.querySelectorAll('a[href="#book-visit"],a[href="/visit#book-visit"]')) {
  link.addEventListener('click', event => {
    event.preventDefault();
    openBooking();
  });
}
if (location.hash === '#book-visit') openBooking();
document.querySelector('#open-callback').addEventListener('click', () => {
  callback.elements.campusId.value = visit.elements.campusId.value;
  callback.closest('dialog').showModal();
});
for (const close of document.querySelectorAll('[data-close]')) {
  close.addEventListener('click', () => close.closest('dialog').close());
}

function enableForm(form, source) {
  const send = form.querySelector('[type=submit]');
  const receipt = form.closest('dialog').querySelector('.receipt');
  receipt.querySelector('[data-again]').addEventListener('click', () => {
    receipt.hidden = true;
    form.hidden = false;
    send.disabled = false;
    form.elements.campusId.focus();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (send.disabled || !form.reportValidity()) return;
    const value = name => form.elements[name].value.trim();
    const payload = { source, campusId: value('campusId'), phone: value('phone'), consent: form.elements.consent.checked };
    if (source === 'visit') {
      payload.name = value('name');
      if (visitorName) payload.nameParts = visitorName.read();
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
      if (source === 'visit') { visitorName?.reset(); updatePreference(); }
      receipt.hidden = false;
      receipt.focus();
    } catch (cause) {
      error.textContent = cause.message || '连接失败，请稍后重试。';
      send.disabled = false;
    }
  });
}
enableForm(visit, 'visit');
enableForm(callback, 'callback');

async function load() {
  try {
    const { campuses } = await receptionInfo();
    if (!campuses?.length) throw new Error();
    for (const form of [visit, callback]) {
      const select = form.elements.campusId;
      select.replaceChildren(...campuses.map(campus => new Option(campus.name, campus.id)));
      select.disabled = false;
      form.querySelector('[type=submit]').disabled = false;
    }
  } catch {
    for (const form of [visit, callback]) {
      form.querySelector('.form-error').textContent = '院区信息暂时无法载入，请刷新后重试。';
    }
  }
}
load();
