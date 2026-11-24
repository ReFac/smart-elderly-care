import { add, btn, canAct, facts, node, today } from './shared.js';
import { residentLabel, staffLabel } from './people-labels.js';

const fieldGroups = [
  ['就诊信息', [['eventDate', '就诊日期'], ['facility', '就诊机构'], ['department', '科室']]],
  ['就诊经过', [['reason', '就诊原因与症状'], ['diagnosis', '医生记录的诊断'], ['tests', '检查与报告结论']]],
  ['用药与医嘱', [['historyMeds', '就诊前用药'], ['prescriptions', '本次处方'], ['orders', '医嘱与注意事项'], ['followUp', '复诊安排']]],
];
export const clinicalKeys = fieldGroups.slice(1).flatMap(([, fields]) => fields.map(([key]) => key));

export function visitFields(ctx, values = {}, refs = {}) {
  const element = node('div', 'medical-visit-fields');
  const controls = new Map();
  for (const [group, fields] of fieldGroups) {
    const box = node('fieldset', 'medical-visit-group', node('legend', '', group));
    for (const [key, label] of fields) {
      const short = ['eventDate', 'facility', 'department'].includes(key);
      const control = node(short ? 'input' : 'textarea');
      control.name = key;
      control.value = values[key] || '';
      control.maxLength = short ? 200 : 4000;
      if (!short) control.rows = 2;
      else if (key === 'eventDate') {
        control.type = 'date';
        control.max = today(ctx);
        control.required = true;
      }
      controls.set(key, control);
      const item = node('div', 'medical-visit-field', node('label', 'field', [
        node('span', '', label + (key === 'eventDate' ? ' *' : '')), control,
      ]));
      if (refs[key]?.length) item.append(sourceNotes(refs[key]));
      box.append(item);
    }
    element.append(box);
  }
  return { element, values: () => Object.fromEntries([...controls].map(([k, v]) => [k, v.value.trim()])) };
}

function sourceNotes(refs) {
  return node('details', 'medical-visit-evidence', [
    node('summary', '', '识别时参考的原文（' + refs.length + '）'),
    node('ul', '', refs.map(ref => node('li', '', [
      node('small', '', [ref.filename, ref.page && '第 ' + ref.page + ' 页', ref.line && '第 ' + ref.line + ' 行'].filter(Boolean).join(' · ')),
      node('p', '', ref.text || ''),
    ]))),
  ]);
}

function originals(attachments, local = null) {
  const viewer = node('section', 'medical-visit-originals');
  if (!attachments?.length) return viewer;
  const title = node('h3', '', '本次就诊原件');
  const select = node('select');
  select.setAttribute('aria-label', '核对的就诊原件');
  attachments.forEach((a, i) => select.add(new Option((i + 1) + '. ' + a.category + ' · ' + a.filename, String(i))));
  const image = node('img', 'medical-visit-image');
  const link = node('a', 'btn btn-secondary');
  const info = node('small', 'fx-muted');
  const draw = () => {
    const i = Number(select.value);
    const a = attachments[i];
    const src = local ? local[i] : '/api/medical-visits/originals/' + encodeURIComponent(a.id);
    info.textContent = a.pageCount + ' 页 · ' + Math.ceil(a.bytes / 1024) + ' KiB';
    link.href = src;
    link.download = a.filename;
    link.textContent = '下载原件核对';
    image.hidden = !a.mime.startsWith('image/');
    if (image.hidden) image.removeAttribute('src');
    else {image.alt = a.filename; image.src = src;}
  };
  select.addEventListener('change', draw);
  draw();
  viewer.append(title, select, image, node('div', 'medical-visit-original-actions', [info, link]));
  return viewer;
}

function clinicalContent(fields) {
  return clinicalKeys.some(key => fields[key]);
}

export function reviewVisit(ctx, person, draft, localUrls, origin) {
  let revision = draft.revision ?? ctx.state.revision;
  const fields = visitFields(ctx, draft.fields, draft.sourceRefs);
  const check = node('input');
  check.type = 'checkbox';
  check.required = true;
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const submit = node('button', 'btn btn-primary', '确认添加此病例');
  submit.type = 'submit';
  submit.disabled = Boolean(draft.identityConflict);
  const form = node('form', 'medical-visit-form');
  form.autocomplete = 'off';
  const factsLine = node('p', 'medical-visit-target', [ctx.ui.icon('folder', 18), '写入长者档案', node('strong', '', residentLabel(ctx, person))]);
  const content = node('div', 'medical-visit-review-content', [
    draft.attachments?.length ? originals(draft.attachments, localUrls) : null,
    fields.element,
  ]);
  add(form,
    factsLine,
    draft.identityConflict ? node('p', 'medical-visit-warning', '这组资料存在长者身份或就诊日期冲突，请返回并按一位长者的一次就诊重新分组。') : null,
    ...(draft.warnings || []).map(w => node('p', 'medical-visit-warning', w)),
    content,
    node('label', 'access-check', [check, '我已核对长者、就诊日期、用药和医嘱，确认保存以上内容。']),
    error,
  );
  const dialog = ctx.detail('核对就诊病例', form);
  dialog.classList.add('medical-visit-dialog');
  dialog.dataset.roundsResidentId = person.id;
  form.append(node('footer', 'medical-visit-actions', [
    btn(ctx, '返回资料', () => dialog.close()), submit,
  ]));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    const values = fields.values();
    if (!clinicalContent(values)) {error.textContent = '请至少填写一项就诊经过、检查、用药或医嘱。'; return;}
    submit.disabled = true;
    error.textContent = '';
    try {
      const response = await fetch('/api/commands', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'dossier.confirmVisit', revision, payload: {
          residentId: person.id, draftId: draft.draftId, fields: values, confirmed: true,
        } }),
      });
      const result = await response.json();
      if (response.status === 409) {
        const current = await ctx.get('/api/version');
        revision = current.revision;
        check.checked = false;
        throw new Error('工作台记录刚刚更新。已保留本次编辑，请核对后再次确认。');
      }
      if (response.status === 401) {await ctx.refreshWorkspace(); return;}
      if (!response.ok) throw new Error(result.error || '病例暂未保存，请重试。');
      if (dialog.open) dialog.close();
      if (origin.open) origin.close();
      if (!(await ctx.refreshWorkspace())) return;
      document.querySelectorAll('[data-visit-history]').forEach(panel => panel.dispatchEvent(new Event('visit-saved')));
      ctx.toast('已将本次就诊病例写入' + residentLabel(ctx, person) + '的档案。');
    } catch (e) {
      if (dialog.open) error.textContent = e.message || '请检查网络后重试。';
    } finally {
      submit.disabled = Boolean(draft.identityConflict);
    }
  });
  return dialog;
}

function showVisit(ctx, person, record) {
  const fields = record.fields;
  const body = node('article', 'medical-visit-detail', [
    node('p', 'medical-visit-target', [ctx.ui.icon('folder', 18), residentLabel(ctx, person)]),
    facts([
      ['就诊日期', fields.eventDate], ['就诊机构', fields.facility], ['科室', fields.department],
      ['资料整理', record.mode === 'manual' ? '手工录入' : 'AI 整理后人工核对'],
      ['核对人员', staffLabel(ctx, { id: record.reviewerId, displayName: record.reviewer, role: record.reviewerRole })],
      ['存档时间', record.recordedAt?.replace('T', ' ').slice(0, 19)],
    ]),
  ]);
  for (const [, group] of fieldGroups.slice(1)) {
    for (const [key, label] of group) {
      if (!fields[key]) continue;
      body.append(node('section', 'medical-visit-text', [
        node('h3', '', label), node('p', '', fields[key]),
        record.sourceRefs?.[key]?.length ? sourceNotes(record.sourceRefs[key]) : null,
      ]));
    }
  }
  body.append(originals(record.attachments));
  ctx.detail('就诊病例详情', body);
}

export function visitHistory(ctx, person, openEditor) {
  const panel = node('section', 'medical-visit-history');
  panel.dataset.visitHistory = person.id;
  const draw = () => {
    const live = ctx.current?.() || ctx;
    if (!live.state || !live.state.residents?.some(r => r.id === person.id)) {panel.replaceChildren(); return;}
    const rows = (live.state.medicalVisits || []).filter(r => r.residentId === person.id).sort((a, b) =>
      b.fields.eventDate.localeCompare(a.fields.eventDate) || b.recordedAt.localeCompare(a.recordedAt));
    const header = node('header', 'fx-timeline-head', [
      node('h3', '', [live.ui.icon('folder', 18), '就诊病例与过往记录']), node('span', 'fx-count', rows.length + ' 次'),
      openEditor && canAct(live, 'dossier.confirmVisit') ? btn(live, '手动录入病例', () => openEditor(live, person, 'manual')) : null,
    ]);
    const items = rows.map(r => node('article', 'fx-time-row', [
      node('time', '', r.fields.eventDate),
      node('div', 'fx-named', [
        node('strong', '', r.fields.diagnosis || r.fields.reason || '就诊记录'),
        node('small', '', [r.fields.facility, r.fields.department, r.attachments.length + ' 份原件'].filter(Boolean).join(' · ')),
      ]),
      btn(live, '查看病例', () => showVisit(live, person, r), 'ghost'),
    ]));
    panel.replaceChildren(header, ...(items.length ? items : [node('p', 'fx-muted', '尚无已核对的就诊病例。')]));
  };
  panel.addEventListener('visit-saved', draw);
  draw();
  return panel;
}
