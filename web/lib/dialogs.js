import { el, button, toast } from './ui.js';

function modal(title) {
  const previous = document.activeElement;
  const dialog = el('dialog', 'dialog');
  dialog.setAttribute('aria-label', title);
  const head = el('header', 'dialog-head');
  const close = button('', () => dialog.close(), 'icon', 'close');
  close.setAttribute('aria-label', '关闭对话框');
  head.append(el('h2', '', title), close);
  dialog.append(head);
  dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (
      event.clientX < r.left ||
      event.clientX > r.right ||
      event.clientY < r.top ||
      event.clientY > r.bottom
    )
      dialog.close();
  });
  dialog.addEventListener(
    'close',
    () => {
      dialog.remove();
      if (previous?.isConnected) previous.focus();
    },
    {
      once: true,
    }
  );
  document.body.append(dialog);
  return dialog;
}

export function detail(title, content, { drawer = false } = {}) {
  const dialog = modal(title);
  if (drawer) dialog.classList.add('desk-detail-drawer');
  const body = el('section', 'dialog-body');
  body.append(content);
  dialog.append(body);
  dialog.showModal();
  return dialog;
}

export function formDialog({
  title,
  fields,
  onSubmit,
  description,
  content,
  submitLabel: submitLabel = '保存',
}) {
  const dialog = modal(title);
  const form = el('form', 'dialog-form');
  if (description) form.append(el('p', 'form-description', description));
  if (content) {
    const body = el('div', 'form-content');
    body.append(content);
    form.append(body);
  }
  const controls = [];
  for (const field of fields) {
    const label = el('label', 'field');
    const caption = el('span', '', field.label);
    if (field.required) caption.append(el('span', 'required', ' *'));
    let input;
    if (field.type === 'select') {
      input = el('select');
      for (const option of field.options || []) {
        const value = typeof option === 'object' ? option.value : option;
        const name = typeof option === 'object' ? option.label : option;
        input.add(new Option(name, value));
      }
    } else if (field.type === 'textarea') {
      input = el('textarea');
      input.rows = 3;
    } else {
      input = el('input');
      input.type = field.type || 'text';
    }
    input.name = field.name;
    input.required = Boolean(field.required);
    if (field.value != null) input.value = field.value;
    if (field.placeholder) input.placeholder = field.placeholder;
    for (const name of ['min', 'max', 'step', 'maxLength'])
      if (field[name] != null) input[name] = field[name];
    if (input.type === 'text' || field.type === 'textarea')
      input.maxLength = field.maxLength || 1500;
    controls.push(input);
    label.append(caption, input);
    form.append(label);
    if (field.type === 'select' && field.allowCustom) {
      const custom = el('input');
      custom.type = 'text';
      custom.maxLength = field.maxLength || 40;
      const otherValue = '__custom_option__';
      input.add(new Option('其他人员或班组…', otherValue));
      const row = el('label', 'field');
      row.append(el('span', '', '其他人员或班组名称'), custom);
      const sync = () => {
        const active = input.value === otherValue;
        row.hidden = custom.disabled = !active;
        custom.required = active;
        custom.name = active ? field.name : '';
        input.name = active ? '' : field.name;
      };
      input.addEventListener('change', sync);
      sync();
      form.append(row);
    }
  }
  const error = el('div', 'form-error');
  error.setAttribute('role', 'alert');
  const footer = el('footer', 'dialog-actions');
  const submit = el('button', 'btn btn-primary', submitLabel);
  submit.type = 'submit';
  footer.append(
    button('取消', () => dialog.close()),
    submit
  );
  form.append(error, footer);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (submit.disabled) return;
    submit.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(form));
      const saved = await onSubmit(values);
      if (saved) dialog.close();
      else if (saved === false)
        error.textContent =
          document.getElementById('announcer').textContent || '保存失败，请核对表单。';
    } catch (ex) {
      error.textContent = ex.message;
      toast(ex.message);
    } finally {
      submit.disabled = false;
    }
  });
  dialog.append(form);
  dialog.showModal();
  if (!content) controls[0]?.focus();
  return dialog;
}
