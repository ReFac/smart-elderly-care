import { el } from './ui.js';

const renderers = new WeakMap();
const missingFile = '请选择需要上传的文件。';
let sequence = 0;

export function refreshFileSelection(input) {
  renderers.get(input)?.();
}

export function clearFileSelection(input) {
  input.value = '';
  refreshFileSelection(input);
}

function refreshAfterReset(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  queueMicrotask(() => {
    for (const input of form.elements) refreshFileSelection(input);
  });
}

export function fileControl(input, { action, selectedFiles = () => input.files } = {}) {
  const wrapper = el('span', 'file-control');
  const button = el('span', 'file-control-button', action || (input.multiple ? '选择多个文件' : '选择文件'));
  const status = el('span', 'file-control-status');
  status.id = 'file-selection-' + ++sequence;
  // The enclosing field label names the native control. Its description reports the selection.
  button.setAttribute('aria-hidden', 'true');
  status.setAttribute('aria-hidden', 'true');
  input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), status.id].filter(Boolean).join(' '));
  wrapper.append(input, button, status);
  const render = () => {
    const names = Array.from(selectedFiles(), file => file.name);
    const list = names.join('、');
    status.textContent = names.length > 1 ? '已选 ' + names.length + ' 个文件：' + list : list || '未选择文件';
    input.title = status.textContent;
    if (input.validity.customError && input.validationMessage === missingFile)
      input.setCustomValidity('');
  };
  renderers.set(input, render);
  input.addEventListener('input', render);
  input.addEventListener('change', render);
  input.addEventListener('invalid', () => {
    if (input.validity.valueMissing && !input.validity.customError) input.setCustomValidity(missingFile);
  });
  input.ownerDocument.addEventListener('reset', refreshAfterReset, true);
  render();
  return wrapper;
}
