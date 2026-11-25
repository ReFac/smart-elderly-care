import { colorModeControl } from './lib/color-mode.js';
import { icon } from './lib/ui.js';

let reception;

export function receptionInfo() {
  if (!reception) {
    reception = fetch('/api/public/reception', { credentials: 'omit' }).then(response => {
      if (!response.ok) throw new Error('院区暂时无法载入');
      return response.json();
    }).catch(error => {
      reception = undefined;
      throw error;
    });
  }
  return reception;
}

export function publicPage(title) {
  document.querySelector('.account-actions').prepend(colorModeControl());
  for (const target of document.querySelectorAll('[data-icon]')) target.append(icon(target.dataset.icon, 19));
  receptionInfo().then(({ institutionName }) => {
    if (!institutionName) return;
    for (const target of document.querySelectorAll('[data-brand]')) {
      target.translate = false;
      target.textContent = institutionName;
    }
    document.title = title + ' · ' + institutionName;
  }).catch(() => {});
}
