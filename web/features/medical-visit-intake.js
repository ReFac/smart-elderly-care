import { asBase64 } from './document-original.js';
import { btn, canAct, node, today } from './shared.js';
import { residentLabel } from './people-labels.js';
import { reviewVisit, visitsFor } from './medical-visit-review.js';

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
  draw();
  return { input, element: node('fieldset', 'medical-visit-group', [
    node('legend', '', '本次就诊原件'),
    node('label', 'field', [node('span', '', '选择一组照片或 PDF'), input]),
    node('small', 'fx-muted', '支持 JPEG、PNG 和 PDF，每组最多 12 份，单份 8 MiB，合计 24 MiB。'),
    list, error,
  ]) };
}

export function openVisitEditor(ctx, resident = null, mode = 'ai', visitId = '') {
  if (!canAct(ctx, 'dossier.confirmVisit')) return ctx.toast('当前账号没有就诊病例核对权限。');
  const candidates = (ctx.state.residents || []).filter(row => !closed.has(row.status));
  if (resident && !candidates.some(row => row.id === resident.id)) return ctx.toast('这份档案当前只读。');
  const ai = mode === 'ai';
  const form = node('form', 'medical-visit-form medical-visit-wizard');
  form.autocomplete = 'off';
  const dialog = ctx.detail(ai ? '整理就诊资料' : '手动录入病例', form);
  dialog.classList.add('medical-visit-dialog');
  let person = resident, existing = null, date = '';
  const rows = [];
  let active;
  let requestId = crypto.randomUUID();
  dialog.addEventListener('close', () => active?.abort(), {once: true});

  function stage(title, fields, actions, showPerson = true) {
    form.replaceChildren(
      node('div', 'medical-visit-step', [
        showPerson && person ? node('p', 'medical-visit-target', [ctx.ui.icon('folder', 18), residentLabel(ctx, person)]) : null,
        node('h3', '', title), ...fields,
      ]),
      node('footer', 'medical-visit-actions', actions),
    );
    form.onsubmit = null;
    form.querySelector('[data-visit-autofocus]')?.focus();
  }
  const field = (label, control) => node('label', 'field', [node('span', '', label), control]);
  const back = action => btn(ctx, '上一步', action, 'ghost');
  const next = action => btn(ctx, '继续', action, 'primary');
  function setPerson(chosen) {
    if (person?.id !== chosen.id) {
      existing = null;
      date = '';
      rows.splice(0);
    }
    person = chosen;
    dialog.dataset.roundsResidentId = person.id;
  }
  function selectPerson() {
    const select = node('select');
    select.name = 'residentId';
    select.dataset.visitAutofocus = '';
    select.add(new Option('请选择长者', ''));
    const sorted = [...candidates].sort((a,b) => a.name.localeCompare(b.name, 'zh-CN'));
    const duplicateNames = new Set(sorted.filter((row, i) => i && row.name === sorted[i - 1].name).map(row => row.name));
    for (const row of sorted) {
      const option = new Option(row.name, row.id);
      if (!duplicateNames.has(row.name)) select.add(option);
      else {
        const group = node('optgroup');
        group.label = ctx.state.beds?.find(bed => bed.id === row.bedId)?.label
          || ctx.state.residentRooms?.[row.id] || '床位未登记';
        group.append(option);
        select.append(group);
      }
    }
    select.value = person?.id || '';
    const onward = next(() => {
      const chosen = candidates.find(row => row.id === select.value);
      if (!chosen) return;
      setPerson(chosen);
      selectRecord();
    });
    onward.disabled = !select.value;
    select.onchange = () => { onward.disabled = !select.value; };
    stage('选择长者', [field('长者姓名', select)], [onward], false);
  }
  function selectRecord() {
    const list = visitsFor(ctx.current?.() || ctx, person.id);
    const select = node('select');
    select.name = 'visitId';
    select.dataset.visitAutofocus = '';
    select.add(new Option('新建就诊记录', ''));
    list.forEach(row => select.add(new Option(
      '补充 · ' + [row.fields.eventDate, row.fields.facility, row.fields.department].filter(Boolean).join(' · '),
      row.id,
    )));
    select.value = existing?.id || '';
    stage('选择就诊记录', [
      field('要写入的就诊记录', select),
      list.length ? null : node('p', 'fx-muted', '这位长者暂无已存档的就诊记录。'),
    ], [
      resident ? null : back(selectPerson),
      next(() => {
        const chosen = list.find(row => row.id === select.value) || null;
        if (existing?.id !== chosen?.id) {
          date = '';
          rows.splice(0);
          requestId = crypto.randomUUID();
        }
        existing = chosen;
        if (existing) selectFiles();
        else selectDate();
      }),
    ]);
  }
  function selectDate() {
    const input = node('input');
    input.type = 'date';
    input.name = 'eventDate';
    input.required = true;
    input.max = today(ctx.current?.() || ctx);
    input.value = date;
    input.dataset.visitAutofocus = '';
    function proceed() {
      if (!input.reportValidity()) return;
      if (date !== input.value) requestId = crypto.randomUUID();
      date = input.value;
      selectFiles();
    }
    stage('填写就诊日期', [field('就诊日期', input)], [back(selectRecord), next(proceed)]);
    form.onsubmit = event => { event.preventDefault(); proceed(); };
  }
  function selectFiles() {
    const check = node('input');
    check.type = 'checkbox';
    check.required = true;
    const picker = attachmentsInput(ctx, rows, () => {
      requestId = crypto.randomUUID();
      check.checked = false;
    });
    const note = node('p', 'medical-visit-status');
    note.setAttribute('role', 'status');
    const error = node('p', 'form-error');
    error.setAttribute('role', 'alert');
    const submit = node('button', 'btn btn-primary', ai ? '开始识别并核对' : '继续核对');
    submit.type = 'submit';
    const targetDate = existing?.fields.eventDate || date;
    const inputGroup = node('fieldset', 'medical-visit-inputs', [
      node('p', 'medical-visit-selection', [node('strong', '', targetDate),
        existing ? ' · 补充 ' + (existing.fields.facility || '原就诊记录') : ' · 新建就诊记录']),
      picker.element,
      node('label', 'access-check', [check, ai
        ? '已核对资料归属，同意提交 DeepSeek 识别。'
        : '已核对长者与就诊日期。']),
      note, error,
    ]);
    stage(ai ? '上传就诊资料' : '添加原件与记录', [inputGroup], [
      back(existing ? selectRecord : selectDate), submit,
    ]);
    form.onsubmit = async event => {
      event.preventDefault();
      if (submit.disabled || !form.reportValidity()) return;
      if (ai && !rows.length) {error.textContent = '请上传至少一份本次就诊原件。'; return;}
      error.textContent = '';
      inputGroup.disabled = submit.disabled = true;
      const previous = form.querySelector('footer button');
      previous.disabled = true;
      active = new AbortController();
      note.textContent = ai ? '正在识别原件并整理需核对的字段…' : '正在准备病例核对…';
      try {
        const attachments = [];
        for (const row of rows) attachments.push({
          filename: row.file.name, mime: row.mime, category: row.category, imageBase64: await asBase64(row.file),
        });
        if (!dialog.open) return;
        const response = await fetch('/api/residents/' + encodeURIComponent(person.id) + '/medical-visits/preview', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, signal: active.signal,
          body: JSON.stringify({
            requestId, revision: (ctx.current?.() || ctx).state.revision,
            visitId: existing?.id || '', mode, fields: {eventDate: targetDate}, attachments,
            ...(ai ? {consent: true} : {}),
          }),
        });
        const draft = await response.json();
        if (response.status === 409) await ctx.refreshWorkspace();
        if (response.status === 401) { await ctx.refreshWorkspace(); return; }
        if (!response.ok) throw new Error(draft.error || '资料整理失败，请重试。');
        if (!dialog.open) return;
        if (draft.residentId !== person.id || draft.fixedDate !== targetDate ||
            (draft.parentVisitId || '') !== (existing?.id || '') || draft.attachments.length !== rows.length ||
            !draft.attachments.every((attachment, i) => attachment.bytes === rows[i].file.size &&
              attachment.mime === rows[i].mime && attachment.category === rows[i].category))
          throw new Error('返回的就诊对象或原件与刚才的选择不符，请重新核对。');
        const urls = rows.map(row => URL.createObjectURL(row.file));
        const review = reviewVisit(ctx, person, draft, urls, dialog);
        review.addEventListener('close', () => urls.forEach(url => URL.revokeObjectURL(url)), {once: true});
      } catch (problem) {
        if (dialog.open) error.textContent = problem.message || '连接失败，请重试。';
      } finally {
        inputGroup.disabled = submit.disabled = previous.disabled = false;
        note.textContent = '';
      }
    };
  }

  if (resident) {
    setPerson(resident);
    existing = visitsFor(ctx, resident.id).find(row => row.id === visitId) || null;
    if (existing) selectFiles();
    else selectRecord();
  } else selectPerson();
  return dialog;
}
