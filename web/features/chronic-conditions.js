import { btn, choose, node } from './shared.js';
import { residentLabel, staffLabel } from './people-labels.js';

const states = { confirmed: '已确认慢性病', none: '经核对无已知慢性病', unknown: '待核实' };

function summary(record) {
  return record?.status === 'confirmed' ? record.items.map(item => item.name).join('、') :
    states[record?.status] || '未登记';
}

function label(title, control) {
  return node('label', 'field', [node('span', '', title), control]);
}

function edit(ctx, person, data, save) {
  const visits = (ctx.state.medicalVisits || []).filter(v => v.residentId === person.id && v.fields?.diagnosis);
  const record = data.chronic;
  const form = node('div', 'dossier-form');
  const suggestions = node('datalist');
  suggestions.id = 'chronic-names-' + crypto.randomUUID();
  for (const name of ['高血压', '糖尿病', '冠心病', '慢性阻塞性肺疾病', '慢性肾脏病', '骨质疏松症'])
    suggestions.append(new Option(name, name));
  const status = node('select');
  for (const [value, title] of Object.entries(states)) status.add(new Option(title, value));
  status.value = record?.status || 'unknown';
  const list = node('div', 'dossier-form');
  const sources = node('fieldset', 'dossier-form-group', [node('legend', '', '确诊病名及依据'), list]);
  const note = node('textarea');
  note.rows = 2;
  note.maxLength = 300;
  note.value = record?.reviewNote || '';
  const rows = new Map();
  function add(item = {}) {
    const block = node('div', 'dossier-form-group');
    const name = node('input');
    name.maxLength = 100;
    name.required = true;
    name.setAttribute('list', suggestions.id);
    name.value = item.name || '';
    const which = node('select');
    which.add(new Option('手工注明已核对的依据', ''));
    for (const v of visits) which.add(new Option([v.fields.eventDate, v.fields.facility,
      v.fields.diagnosis.slice(0, 35)].filter(Boolean).join(' · '), v.id));
    which.value = item.visitId || '';
    const source = node('input');
    source.maxLength = 300;
    source.value = item.source || '';
    source.placeholder = '如：某医院出院小结，注明日期';
    const manual = label('核对依据', source);
    const excerpt = node('blockquote', 'rounds-evidence');
    const sync = () => {
      const chosen = visits.find(v => v.id === which.value);
      source.required = !chosen;
      source.disabled = manual.hidden = Boolean(chosen);
      excerpt.hidden = !chosen;
      excerpt.textContent = chosen?.fields.diagnosis || '';
    };
    which.onchange = sync;
    sync();
    const remove = btn(ctx, '移除此项', () => { rows.delete(block); block.remove(); });
    block.append(label('病名（按确诊原文）', name), label('依据来源', which), manual, excerpt, remove);
    rows.set(block, () => ({name: name.value.trim(), visitId: which.value, source: which.value ? '' : source.value.trim()}));
    list.append(block);
  }
  for (const item of record?.items || []) add(item);
  sources.append(btn(ctx, '添加病名', () => add()));
  const sync = () => {
    sources.hidden = sources.disabled = status.value !== 'confirmed';
    if (!sources.hidden && !rows.size) add();
    note.required = status.value !== 'confirmed';
  };
  status.onchange = sync;
  sync();
  form.append(suggestions, label('登记状态', status), sources, label('核对说明', note));
  const revision = data.revision;
  const requestId = crypto.randomUUID();
  const dialog = ctx.dialog({
    title: '核对慢性病 · ' + residentLabel(ctx, person),
    description: '请核对这位长辈本人的确诊记录。疑似或已排除的诊断请保留在原就诊记录中。',
    content: form, fields: [], submitLabel: '核对并保存',
    onSubmit: () => {
      const items = status.value === 'confirmed' ? [...rows.values()].map(read => read()) : [];
      if (status.value === 'confirmed' && !items.length) throw Error('请至少添加一项已确认的慢性病');
      const reviewNote = note.value.trim();
      const fields = [['登记状态', states[status.value]], ...items.map(i => [i.name,
        i.source || visits.find(v => v.id === i.visitId)?.fields.diagnosis])];
      if (reviewNote) fields.push(['核对说明', reviewNote]);
      return save('dossier.recordChronic', {status: status.value, items, reviewNote, requestId}, revision,
        {title: '保存已核对的慢性病标注', fields});
    },
  });
  dialog.dataset.roundsResidentId = person.id;
}

export function chronicConditions(ctx, person, data, compact, save) {
  const record = data.chronic;
  const content = node('section', '', [node('h4', '', '慢性病'), node('p', '', summary(record))]);
  if (compact) return content;
  if (record?.day) content.append(node('small', 'fx-muted', '最近核对 · ' + (record.at?.slice(0, 16).replace('T', ' ') || record.day)));
  function basis(r) {
    const list = node('div', 'fx-profile');
    for (const item of r.items) {
      const visit = item.visitId && (ctx.state.medicalVisits || []).find(v => v.id === item.visitId && v.residentId === person.id);
      const source = visit ? [visit.fields.eventDate, visit.fields.facility, visit.fields.diagnosis].filter(Boolean).join(' · ') : item.source;
      if (source) list.append(node('p', '', item.name + ' · ' + source));
    }
    if (r.reviewNote) list.append(node('p', '', r.reviewNote));
    if (r.staff) list.append(node('small', 'fx-muted', staffLabel(ctx, {id:r.staffId, displayName:r.staff, role:r.role})));
    return list;
  }
  if (record) content.append(basis(record));
  const previous = (data.chronicHistory || []).slice(1);
  if (previous.length) content.append(node('details', '', [node('summary', '', '历史标注（' + previous.length + '）'),
    ...previous.map(r => node('article', 'fx-time-row', [node('time', '', r.at?.slice(0, 16).replace('T', ' ') || r.day),
      node('div', '', [node('strong', '', summary(r)), basis(r)])]))]));
  if (data.canRecordChronic) {
    const actions = choose();
    actions.append(btn(ctx, '核对慢性病', () => edit(ctx, person, data, save)));
    content.append(actions);
  }
  return content;
}
