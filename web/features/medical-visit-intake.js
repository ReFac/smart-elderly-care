import { asBase64 } from './document-original.js';
import { btn, canAct, node, today } from './shared.js';
import { residentLabel } from './people-labels.js';
import { clinicalKeys, reviewVisit, visitFields } from './medical-visit-review.js';

const types = ['就诊记录', 'CT影像', '检查报告', '处方', '医嘱', '其他'];
const mimeByExtension = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };
const mib = 1024 * 1024;
const closed = new Set(['已退住', '已归档', '归档', '已出院', '归档到期']);

function categoryFrom(filename) {
  if (/报告|结论/.test(filename)) return '检查报告';
  if (/ct|影像|扫描片/i.test(filename)) return 'CT影像';
  if (/处方|药单/.test(filename)) return '处方';
  if (/医嘱/.test(filename)) return '医嘱';
  return '就诊记录';
}

function attachmentsInput(ctx, rows, changed) {
  const input = node('input');
  input.type = 'file';
  input.multiple = true;
  input.accept = '.pdf,.png,.jpeg,.jpg,application/pdf,image/png,image/jpeg';
  const list = node('ul', 'medical-file-list');
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  function draw() {
    list.replaceChildren(...rows.map(row => {
      const type = node('select');
      type.setAttribute('aria-label', row.file.name + '的资料类别');
      types.forEach(t => type.add(new Option(t, t)));
      type.value = row.category;
      type.onchange = () => {row.category = type.value; changed();};
      return node('li', 'medical-file', [
        node('span', 'medical-file-name', [ctx.ui.icon('file', 15), row.file.name]),
        node('small', 'fx-muted', Math.ceil(row.file.size / 1024) + ' KiB'), type,
        btn(ctx, '移除', () => {rows.splice(rows.indexOf(row), 1); draw(); changed();}, 'ghost'),
      ]);
    }));
  }
  input.addEventListener('change', () => {
    error.textContent = '';
    const selected = Array.from(input.files);
    input.value = '';
    const next = [];
    for (const file of selected) {
      const mime = file.type || mimeByExtension[file.name.split('.').pop().toLowerCase()];
      if (!Object.values(mimeByExtension).includes(mime) || !file.size || file.size > 8 * mib) {
        error.textContent = '请检查「' + file.name + '」。仅支持有效的 JPEG、PNG 或 PDF，每份上限 8 MiB。';
        return;
      }
      next.push({ file, mime, category: categoryFrom(file.name) });
    }
    const all = [...rows, ...next];
    if (all.length > 12 || all.reduce((n, f) => n + f.file.size, 0) > 24 * mib) {
      error.textContent = '每组最多 12 份原件，合计上限 24 MiB。请重新选择本次资料。';
      return;
    }
    rows.push(...next);
    draw();
    changed();
  });
  return { input, element: node('fieldset', 'medical-visit-group', [
    node('legend', '', '本次就诊原件'),
    node('label', 'field', [node('span', '', '选择一组照片或 PDF'), input]),
    node('small', 'fx-muted', '支持 JPEG、PNG 和 PDF，每组最多 12 份，单份 8 MiB，合计 24 MiB。'),
    list, error,
  ]) };
}

export function openVisitEditor(ctx, resident = null, mode = 'ai') {
  if (!canAct(ctx, 'dossier.confirmVisit')) return ctx.toast('当前账号没有就诊病例核对权限。');
  const candidates = (ctx.state.residents || []).filter(r => !closed.has(r.status));
  if (resident && !candidates.some(r => r.id === resident.id)) return ctx.toast('这份档案当前只读。');
  const ai = mode === 'ai';
  const form = node('form', 'medical-visit-form');
  form.autocomplete = 'off';
  const person = node('select');
  person.name = 'residentId';
  person.required = true;
  person.add(new Option('请选择本次就诊的长者', ''));
  candidates.forEach(r => person.add(new Option(residentLabel(ctx, r) + ' · ' + r.id, r.id)));
  const rows = [];
  const check = node('input');
  check.type = 'checkbox';
  check.required = true;
  let requestId = crypto.randomUUID();
  function renewRequest() {
    requestId = crypto.randomUUID();
    check.checked = false;
    person.disabled = Boolean(resident || rows.length);
  }
  const picker = attachmentsInput(ctx, rows, renewRequest);
  const updatePerson = () => {
    picker.input.disabled = !person.value;
    renewRequest();
  };
  person.onchange = updatePerson;
  person.value = resident?.id || '';
  updatePerson();
  const fields = ai ? null : visitFields(ctx, { eventDate: today(ctx) });
  fields?.element.addEventListener('input', renewRequest);
  const note = node('p', 'medical-visit-status');
  note.setAttribute('role', 'status');
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const submit = node('button', 'btn btn-primary', ai ? '整理这组就诊资料' : '核对本次病例');
  submit.type = 'submit';
  const group = node('fieldset', 'medical-visit-inputs', [
    node('label', 'field', [node('span', '', '长者档案'), person]),
    ai ? node('p', 'medical-visit-instruction', '一次只整理一位长者的一次就诊。可将 CT、检查报告、就诊简报和处方一起选入。') : null,
    fields?.element,
    picker.element,
    node('label', 'access-check', [check, ai
      ? '我已核对这组原件属于所选长者的同一次就诊，同意将文书交由 DeepSeek 识别整理。'
      : '我已核对长者和这一次就诊资料的归属。']),
  ]);
  form.append(group, note, error, submit);
  const dialog = ctx.detail(ai ? '整理一组就诊资料' : '手动录入就诊病例', form);
  dialog.classList.add('medical-visit-dialog');
  if (resident) dialog.dataset.roundsResidentId = resident.id;
  let active;
  dialog.addEventListener('close', () => active?.abort(), { once: true });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    const chosen = candidates.find(r => r.id === person.value);
    if (!chosen) {error.textContent = '请先选择要写入的长者档案。'; return;}
    if (ai && !rows.length) {error.textContent = '请选择本次就诊的至少一份原件。'; return;}
    const values = fields?.values() || {};
    if (!ai && !clinicalKeys.some(k => values[k])) {error.textContent = '请至少填写一项就诊经过、检查、用药或医嘱。'; return;}
    error.textContent = '';
    group.disabled = submit.disabled = true;
    active = new AbortController();
    dialog.dataset.roundsResidentId = chosen.id;
    note.textContent = ai ? '正在整理本次资料，请等待字段核对窗口…' : '正在准备本次病例供您核对…';
    try {
      const attachments = [];
      for (const row of rows) {
        attachments.push({ filename: row.file.name, mime: row.mime, category: row.category, imageBase64: await asBase64(row.file) });
      }
      if (!dialog.open) return;
      const response = await fetch('/api/residents/' + encodeURIComponent(chosen.id) + '/medical-visits/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: active.signal,
        body: JSON.stringify({ requestId, revision: (ctx.current?.() || ctx).state.revision,
          mode, fields: values, attachments, ...(ai ? { consent: true } : {}) }),
      });
      const draft = await response.json();
      if (response.status === 409) await ctx.refreshWorkspace();
      if (response.status === 401) {await ctx.refreshWorkspace(); return;}
      if (!response.ok) throw new Error(draft.error || '资料整理失败，请重试。');
      if (!dialog.open) return;
      if (draft.residentId !== chosen.id || draft.attachments.length !== rows.length ||
          !draft.attachments.every((attachment, i) => attachment.bytes === rows[i].file.size &&
            attachment.mime === rows[i].mime && attachment.category === rows[i].category)) {
        throw new Error('返回的档案或原件与本组资料不一致，请重新核对。');
      }
      const urls = rows.map(row => URL.createObjectURL(row.file));
      const review = reviewVisit(ctx, chosen, draft, urls, dialog);
      review.addEventListener('close', () => urls.forEach(url => URL.revokeObjectURL(url)), { once: true });
    } catch (e) {
      if (dialog.open) error.textContent = e.message || '连接失败，请重试。';
    } finally {
      group.disabled = submit.disabled = false;
      note.textContent = '';
    }
  });
}
