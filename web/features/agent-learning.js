import { confirmChange } from '../lib/change-review.js';
import { node } from './shared.js';

const endpoint = '/api/assistant/learning';

async function read(url, body) {
  const options = body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  } : {};
  const response = await fetch(url, { ...options, cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || '暂时无法读取规则');
  return data;
}

function select(options) {
  const element = node('select', 'fx-input');
  options.forEach(item => element.add(new Option(item.label || item.name, item.id)));
  return element;
}

function field(title, element) {
  return node('label', 'access-field', [node('span', '', title), element]);
}

function button(label, callback) {
  const element = node('button', 'btn', label);
  element.type = 'button';
  element.addEventListener('click', async () => {
    element.disabled = true;
    try { await callback(); } finally { element.disabled = false; }
  });
  return element;
}

function examples(rows) {
  return node('dl', 'fx-facts', rows.map(row => [
    node('dt', '', row.case),
    node('dd', '', [node('div', '', '原顺序　' + row.before.join('；')),
      node('div', '', '提案效果　' + row.after.join('；'))]),
  ]));
}

// Opening this dialog does not send the patient's message or draft to the skills ledger.
export async function openAgentLearning(ctx, campusId = '') {
  const root = node('div', 'fx-profile');
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const content = node('div', 'fx-profile');
  root.append(error, content);
  ctx.detail('助理写作规则', root);
  async function attempt(fn) {
    error.textContent = '';
    try { await fn(); } catch (cause) { error.textContent = cause.message; }
  }
  await attempt(async () => {
    const meta = await read(endpoint);
    if (!meta.topics.length) {
      content.textContent = '当前岗位没有可提议的规则类别。';
      return;
    }
    const campus = select(meta.campuses);
    if (meta.campuses.some(item => item.id === campusId)) campus.value = campusId;
    const topic = select(meta.topics);
    const body = node('section', 'fx-profile');
    content.append(node('div', 'access-field-pair', [field('生效院区', campus), field('规则类别', topic)]), body);
    let generation = 0;
    async function reload() {
      const current = ++generation;
      const scope = { campusId: campus.value, topic: topic.value };
      body.replaceChildren(node('p', 'fx-muted', '正在读取院区规则…'));
      const data = await read(endpoint + '?' + new URLSearchParams(scope));
      if (current !== generation) return;
      const post = (action, values) => read(endpoint + '/' + action, { ...scope, ...values });
      const correction = node('textarea', 'fx-input');
      correction.maxLength = 1200;
      correction.rows = 2;
      correction.placeholder = '例如，先写实际摄入，再写出席；缺少的项标明待核对';
      const category = meta.topics.find(item => item.id === scope.topic);
      const missing = select(meta.missing);
      const priorities = category.parts.map(() => select(category.parts));
      function populate(order) {
        priorities.forEach((box, index) => { box.value = order[index] || category.parts[index].id; });
        missing.value = order.at(-1)?.startsWith('missing-') ? order.at(-1) : meta.missing[0].id;
      }
      populate(data.order);
      const preview = node('div', 'fx-profile');
      function clearPreview() { preview.replaceChildren(); }
      for (const box of [...priorities, missing, correction]) box.addEventListener('input', clearPreview);
      async function showPreview(fromCorrection) {
        const fields = fromCorrection ? { correction: correction.value } :
          { order: [...priorities.map(box => box.value), missing.value] };
        const draft = await post('preview', fields);
        if (current !== generation) return;
        populate(draft.order);
        // Clear the private correction once we have a structured, de-identified proposal.
        correction.value = '';
        preview.replaceChildren(node('strong', '', '待提交的规则'), node('p', '', draft.instruction),
          examples(draft.examples), button('确认提交建议', () => attempt(async () => {
            await post('propose', { base: draft.base, order: draft.order });
            await reload();
          })));
      }
      const header = node('h3', '', data.version ? '当前规则 · v' + data.version : '当前使用默认规则');
      body.replaceChildren(header, node('p', '', data.releases[0]?.instruction || '按系统默认方式整理。'),
        field('你希望助理怎样改进？', correction), button('从纠错提取规则', () => attempt(() => showPreview(true))),
        node('div', 'access-field-pair', priorities.map((box, i) => field('第 ' + (i + 1) + ' 项', box))),
        field('遇到没有依据的项目', missing), button('预览规则与虚构案例', () => attempt(() => showPreview(false))), preview,
        node('h3', '', data.canReview ? '规则建议' : '我提交的建议'));
      async function decision(title, payload) {
        const confirm = await confirmChange({title, target: campus.selectedOptions[0].text, fields: [['规则类别', category.label], ['当前版本', data.version]], confirmLabel: '确认执行'});
        if (!confirm) return;
        await post('review', { ...payload, base: data.version });
        await reload();
      }
      for (const item of data.proposals) {
        const labels = { pending: '待审核', approve: '已发布', reject: '已驳回' };
        const card = node('section', 'access-settings', [
          node('strong', '', labels[item.decision]), node('small', 'fx-muted', item.created), node('p', '', item.instruction),
        ]);
        if (data.canReview && item.decision === 'pending') {
          card.append(examples(item.examples));
          if (item.base === data.version) {
            card.append(button('批准发布', () => attempt(() =>
              decision('把这条写作规则发布到所选院区？', { proposalId:item.id, decision:'approve' }))));
          } else card.append(node('p', 'fx-muted', '规则已有新版，请以当前版本重新提出。'));
          card.append(button('驳回建议', () => attempt(() =>
            decision('驳回这条规则建议？', { proposalId:item.id, decision:'reject' }))));
        }
        body.append(card);
      }
      if (!data.proposals.length) body.append(node('p', 'fx-muted', '还没有规则建议。'));
      if (data.canReview && data.releases.length) {
        body.append(node('h3', '', '发布与撤回记录'));
        for (const row of [...data.releases, {version:0, instruction:'系统默认规则'}]) {
          const entry = node('div', 'access-settings', [node('strong', '', 'v' + row.version),
            node('small', 'fx-muted', [row.created, row.actor].filter(Boolean).join(' · ')), node('p', '', row.instruction || '系统默认规则')]);
          if (row.version < data.version) entry.append(button('恢复此版', () => attempt(() =>
            decision('确认恢复到 v' + row.version + ' 的写作方式？', { decision:'rollback', restoreVersion:row.version }))));
          body.append(entry);
        }
      }
    }
    for (const control of [campus, topic]) control.addEventListener('change', () => attempt(reload));
    await reload();
  });
}
