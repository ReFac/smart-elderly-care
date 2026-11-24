import { add, btn, canAct, facts, node, today } from './shared.js';
import { residentLabel, staffLabel } from './people-labels.js';
import { hospitalOptions } from './medical-hospital-picker.js';

const fieldGroups = [
  ['就诊信息', [['eventDate', '就诊日期'], ['facility', '就诊机构'], ['department', '科室']]],
  ['就诊经过', [['reason', '就诊原因与症状'], ['diagnosis', '医生记录的诊断'], ['tests', '检查与报告结论']]],
  ['用药与医嘱', [['historyMeds', '就诊前用药'], ['prescriptions', '本次处方'], ['orders', '医嘱与注意事项'], ['followUp', '复诊安排']]],
];
export const clinicalKeys = fieldGroups.slice(1).flatMap(([, fields]) => fields.map(([key]) => key));

function visitFields(ctx, values = {}, refs = {}, fixedDate = '') {
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
        control.readOnly = Boolean(fixedDate);
      }
      controls.set(key, control);
      const item = node('div', 'medical-visit-field', node('label', 'field', [
        node('span', '', label + (key === 'eventDate' ? ' *' : '')), control,
      ]));
      if (key === 'facility') item.append(...hospitalOptions(ctx, control));
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
  const fields = visitFields(ctx, draft.fields, draft.sourceRefs, draft.fixedDate);
  const supplemental = Boolean(draft.parentVisitId);
  const check = node('input');
  check.type = 'checkbox';
  check.required = true;
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const submit = node('button', 'btn btn-primary', supplemental ? '确认补充资料' : '确认添加此病例');
  submit.type = 'submit';
  submit.disabled = Boolean(draft.identityConflict);
  const form = node('form', 'medical-visit-form');
  form.autocomplete = 'off';
  const factsLine = node('p', 'medical-visit-target', [ctx.ui.icon('folder', 18),
    supplemental ? '补充原就诊病例' : '写入长者档案', node('strong', '', residentLabel(ctx, person))]);
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
  const dialog = ctx.detail(supplemental ? '核对就诊补充资料' : '核对就诊病例', form);
  dialog.classList.add('medical-visit-dialog');
  dialog.dataset.roundsResidentId = person.id;
  form.append(node('footer', 'medical-visit-actions', [
    btn(ctx, '返回资料', () => dialog.close()), submit,
  ]));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    const values = fields.values();
    if (!clinicalContent(values) && !(draft.fixedDate && draft.attachments.length)) {error.textContent = '请至少填写一项就诊经过、检查、用药或医嘱。'; return;}
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
      document.querySelectorAll('[data-visit-history], [data-visit-detail]').forEach(panel =>
        panel.dispatchEvent(new Event('visit-saved')));
      ctx.toast(supplemental ? '补充资料已关联原就诊。' : '已将本次就诊病例写入' + residentLabel(ctx, person) + '的档案。');
    } catch (e) {
      if (dialog.open) error.textContent = e.message || '请检查网络后重试。';
    } finally {
      submit.disabled = Boolean(draft.identityConflict);
    }
  });
  return dialog;
}

function visitContent(ctx, record) {
  const fields = record.fields;
  const body = node('div', 'medical-visit-detail', facts([
    ['就诊日期', fields.eventDate], ['就诊机构', fields.facility], ['科室', fields.department],
    ['资料整理', record.mode === 'manual' ? '手工录入' : 'AI 整理后人工核对'],
    ['核对人员', staffLabel(ctx, {id: record.reviewerId, displayName: record.reviewer, role: record.reviewerRole})],
    ['存档时间', record.recordedAt?.replace('T', ' ').slice(0, 19)],
  ]));
  for (const [, group] of fieldGroups.slice(1)) {
    for (const [key, label] of group) {
      if (fields[key]) body.append(node('section', 'medical-visit-text', [
        node('h3', '', label), node('p', '', fields[key]),
        record.sourceRefs?.[key]?.length ? sourceNotes(record.sourceRefs[key]) : null,
      ]));
    }
  }
  body.append(originals(record.attachments));
  return body;
}

export function visitsFor(ctx, residentId) {
  const records = (ctx.state.medicalVisits || []).filter(row => row.residentId === residentId);
  const documents = new Map();
  for (const row of ctx.state.medicalDocuments || []) {
    if (row.residentId !== residentId || !row.visitId) continue;
    if (!documents.has(row.visitId)) documents.set(row.visitId, []);
    documents.get(row.visitId).push(row);
  }
  const byDate = (a, b) => (b.recordedAt || '').localeCompare(a.recordedAt || '');
  const children = new Map();
  for (const row of records) {
    if (!row.parentVisitId) continue;
    if (!children.has(row.parentVisitId)) children.set(row.parentVisitId, []);
    children.get(row.parentVisitId).push(row);
  }
  return records.filter(row => !row.parentVisitId).sort((a,b) => b.fields.eventDate.localeCompare(a.fields.eventDate) || byDate(a,b))
    .map(row => ({...row, supplements: (children.get(row.id) || []).sort(byDate),
      documents: documents.get(row.id) || []}));
}

function documentLabel(doc) {
  return [doc.category, doc.eventDate, doc.source].filter(Boolean).join(' · ');
}

function encounterLabel(record) {
  const fields = record.fields;
  return [fields.eventDate, fields.facility, fields.department, fields.diagnosis || fields.reason]
    .filter(Boolean).join(' · ');
}

function documentRows(ctx, docs, onOpen, onLink, reopenVisit) {
  return node('div', 'medical-visit-document-rows', docs.map(doc => node('article', 'medical-visit-document-row', [
    node('div', 'fx-named', [
      node('strong', '', doc.category),
      node('small', '', [doc.eventDate, doc.source].filter(Boolean).join(' · ')),
    ]),
    onOpen ? btn(ctx, doc.summary ? '查看文书与原件' : '查看待核对原件', () => onOpen(ctx, doc, reopenVisit), 'ghost') : null,
    onLink ? btn(ctx, '选择所属病例', () => onLink(doc)) : null,
  ])));
}

function showVisit(ctx, person, record, openEditor, documents = {}) {
  const body = node('article', 'medical-visit-detail');
  body.dataset.visitDetail = person.id;
  function reopenVisit() {
    const live = ctx.current?.() || ctx;
    const current = visitsFor(live, person.id).find(row => row.id === record.id);
    if (!current) return;
    const openCase = [...document.querySelectorAll('dialog[data-dossier-visit-id][open]')].find(
      dialog => dialog.dataset.dossierVisitId === record.id);
    if (openCase) return;
    documents.reopen?.(live);
    showVisit(live, person, current, openEditor, documents);
  }
  function draw() {
    const live = ctx.current?.() || ctx;
    const current = visitsFor(live, person.id).find(row => row.id === record.id);
    if (!current) { body.replaceChildren(node('p', 'fx-muted', '该就诊档案暂不可查阅。')); return; }
    const details = current.supplements.map(item =>
      node('details', 'medical-visit-supplement', [
        node('summary', '', [
          '补充资料', item.recordedAt?.replace('T', ' ').slice(0, 16),
          item.attachments.length + ' 份原件',
        ].filter(Boolean).join(' · ')),
        visitContent(live, item),
      ]));
    body.replaceChildren(...[
      node('p', 'medical-visit-target', [live.ui.icon('folder', 18), residentLabel(live, person)]),
      node('div', 'medical-visit-actions', [
        openEditor && canAct(live, 'dossier.confirmVisit')
          ? btn(live, '补充本次就诊', () => openEditor(live, person, 'ai', record.id)) : null,
        documents.add && canAct(live, 'dossier.document')
          ? btn(live, '补充医疗文书', () => documents.add(live, person, current, reopenVisit), 'primary') : null,
      ]),
      visitContent(live, current),
      ...details,
      current.documents.length ? node('section', 'medical-visit-linked-documents', [
        node('h3', '', '本次就诊的补充文书'),
        documentRows(live, current.documents, documents.open, null, reopenVisit),
      ]) : null,
    ].filter(Boolean));
  }
  body.addEventListener('visit-saved', draw);
  draw();
  const dialog = ctx.detail('就诊病例详情', body);
  dialog.dataset.roundsResidentId = person.id;
  dialog.dataset.dossierVisitId = record.id;
  return dialog;
}

function showUnlinkedDocuments(ctx, person, docs, visits, openEditor, documents) {
  const body = node('div', 'fx-profile');
  function chooseVisit(doc) {
    const live = ctx.current?.() || ctx;
    const available = visitsFor(live, person.id);
    const select = node('select', 'fx-input');
    select.required = true;
    select.add(new Option('请选择核对过的原就诊', ''));
    for (const visit of available) select.add(new Option(encounterLabel(visit), visit.id));
    const error = node('p', 'form-error');
    error.setAttribute('role', 'alert');
    const submit = node('button', 'btn btn-primary', '提交关联');
    submit.type = 'submit';
    const form = node('form', 'fx-profile', [
      facts([['医疗文书', documentLabel(doc)]]),
      node('label', 'field', [node('span', '', '归入就诊病例'), select]),
      error,
      node('div', 'dialog-actions', submit),
    ]);
    const dialog = live.detail('将历史文书归入病历', form);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const selected = available.find(visit => visit.id === select.value);
      if (!selected || submit.disabled) return;
      submit.disabled = true;
      try {
        const saved = await live.command('dossier.linkVisitDocument', {
          residentId: person.id, documentId: doc.id, visitId: selected.id,
        }, {
          title: '确认将历史文书归入病历',
          fields: [['医疗文书', documentLabel(doc)], ['所属就诊', encounterLabel(selected)]],
        });
        if (!saved) {
          error.textContent = '文书未关联，请核对所选病例后重试。';
          return;
        }
        if (dialog.open) dialog.close();
        const latest = live.current?.() || live;
        documents.reopen?.(latest);
        showVisit(latest, person, selected, openEditor, documents);
      } finally {
        submit.disabled = false;
      }
    });
  }
  if (documents.add && canAct(ctx, 'dossier.linkVisitDocument')) {
    body.append(node('p', 'fx-muted', visits.length
      ? '先核对旧原件，再手动选择该文书所属的就诊病例。'
      : '录入对应的历史就诊病例后，再为这些存量原件选择归属。'));
  }
  body.append(documentRows(ctx, docs, documents.open,
    documents.add && visits.length && canAct(ctx, 'dossier.linkVisitDocument') ? chooseVisit : null));
  ctx.detail('待归入病历的历史资料', body);
}

export function visitHistory(ctx, person, openEditor, documents = {}) {
  const panel = node('section', 'medical-visit-history');
  panel.dataset.visitHistory = person.id;
  const search = node('input', 'fx-input');
  search.type = 'search';
  search.placeholder = '搜索就诊日期、医院、科室或诊断';
  search.setAttribute('aria-label', search.placeholder);
  const searchBar = node('div', 'fx-table-tools');
  searchBar.append(node('label', 'fx-table-search', [ctx.ui.icon('search', 15), search]));
  const list = node('div', 'medical-visit-rows');
  let renderRows;
  const draw = () => {
    const live = ctx.current?.() || ctx;
    if (!live.state || !live.state.residents?.some(row => row.id === person.id)) {
      panel.replaceChildren();
      return;
    }
    const rows = visitsFor(live, person.id);
    const unlinked = (live.state.medicalDocuments || []).filter(doc =>
      doc.residentId === person.id && !doc.visitId
    );
    const actions = openEditor && canAct(live, 'dossier.confirmVisit') ? node('div', 'medical-visit-actions', [
      btn(live, '手动录入病例', () => openEditor(live, person, 'manual')),
      btn(live, '上传就诊资料', () => openEditor(live, person, 'ai'), 'primary'),
    ]) : null;
    const count = node('span', 'fx-count');
    count.setAttribute('aria-live', 'polite');
    const header = node('header', 'fx-timeline-head', [
      node('h3', '', [live.ui.icon('folder', 18), '就诊病例与过往记录']),
      count, actions,
    ]);
    renderRows = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const filtered = rows.filter(row => !query ||
        [row, ...row.supplements].some(({fields}) =>
          [fields.eventDate, fields.facility, fields.department, fields.diagnosis, fields.reason]
            .filter(Boolean).join(' ').toLocaleLowerCase().includes(query)) ||
        row.documents.some(doc => documentLabel(doc).toLocaleLowerCase().includes(query))
      );
      count.textContent = filtered.length + ' 次';
      const items = filtered.map(row => {
        const files = row.attachments.length + row.supplements.reduce((n, item) => n + item.attachments.length, 0) +
          row.documents.filter(doc => doc.hasImage).length;
        return node('article', 'fx-time-row', [
          node('time', '', row.fields.eventDate),
          node('div', 'fx-named', [
            node('strong', '', row.fields.diagnosis || row.fields.reason || '就诊记录'),
            node('small', '', [row.fields.facility, row.fields.department, files + ' 份原件',
              row.supplements.length ? row.supplements.length + ' 次补充' : '',
              row.documents.length ? row.documents.length + ' 份补充文书' : ''].filter(Boolean).join(' · ')),
          ]),
          btn(live, '查看病例', () => showVisit(live, person, row, openEditor, documents), 'ghost'),
        ]);
      });
      list.replaceChildren(...(items.length ? items : [node('p', 'fx-muted',
        rows.length ? '没有匹配的就诊记录。' : '尚无已核对的就诊病例。')]));
    };
    if (!rows.length) search.value = '';
    searchBar.hidden = !rows.length;
    panel.replaceChildren(header, searchBar, list);
    if (unlinked.length && documents.open) {
      panel.append(node('div', 'medical-visit-unlinked', btn(
        live, '待归入病历的历史资料（' + unlinked.length + '）',
        () => showUnlinkedDocuments(live, person, unlinked, rows, openEditor, documents), 'ghost',
      )));
    }
    renderRows();
  };
  search.addEventListener('input', () => renderRows?.());
  panel.addEventListener('visit-saved', draw);
  draw();
  return panel;
}
