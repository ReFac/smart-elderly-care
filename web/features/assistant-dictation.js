import { el } from '../lib/ui.js';
import { node } from './shared.js';

export function dictationReview(input, changed) {
  const toggle = el('button', 'assistant-dictation-toggle', '查看原话');
  toggle.type = 'button';
  toggle.setAttribute('aria-controls', 'assistant-dictation-original');
  const restore = el('button', 'assistant-dictation-toggle', '使用原话');
  restore.type = 'button';
  const text = el('p', 'assistant-dictation-text');
  const original = node('div', 'assistant-dictation-original', [text, restore]);
  original.id = 'assistant-dictation-original';
  const status = el('span', '', '已整理语音');
  const element = node('div', 'assistant-dictation', [
    node('div', 'assistant-dictation-bar', [status, toggle]), original,
  ]);
  let draft = null;

  function expand(open) {
    original.hidden = !open;
    toggle.textContent = open ? '收起原话' : '查看原话';
    toggle.setAttribute('aria-expanded', String(open));
  }

  function canRestore() {
    return draft && !draft.sent && !draft.restored && !input.disabled && !input.readOnly &&
      input.value.slice(draft.start, draft.start + draft.polished.length) === draft.polished;
  }

  function sync() {
    element.hidden = !draft;
    restore.hidden = !draft || draft.sent || draft.restored;
    restore.disabled = !canRestore();
  }

  toggle.addEventListener('click', () => expand(original.hidden));
  restore.addEventListener('click', () => {
    if (!canRestore()) return;
    const { raw, polished, start } = draft;
    input.setRangeText(raw, start, start + polished.length, 'end');
    draft.restored = true;
    status.textContent = '已使用原话';
    expand(false);
    changed();
    input.focus({ preventScroll: true });
  });
  expand(false);
  sync();
  return {
    element, sync,
    show(raw, polished, start) {
      draft = raw === polished ? null : { raw, polished, start };
      status.textContent = '已整理语音';
      text.textContent = draft ? raw : '';
      expand(false);
      sync();
    },
    clear() {
      draft = null;
      text.textContent = '';
      expand(false);
      sync();
    },
    sent() {
      if (draft) draft.sent = true;
      sync();
    },
  };
}
