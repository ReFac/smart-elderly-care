import { confirmChange } from '../lib/change-review.js';
import { icon } from '../lib/ui.js';
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
  const element = node('select');
  options.forEach(item => element.add(new Option(item.label || item.name, item.id)));
  return element;
}

function field(title, element) {
  return node('label', 'learning-field', [node('span', '', title), element]);
}

function button(label, callback, kind = '', symbol) {
  const element = node('button', 'learning-button ' + kind, [symbol && icon(symbol, 16), label]);
  element.type = 'button';
  element.addEventListener('click', async () => {
    element.disabled = true;
    try { await callback(); } finally { element.disabled = false; }
  });
  return element;
}

function examples(rows) {
  return node('div', 'learning-examples', rows.map(row =>
    node('section', 'learning-example', [
      node('h4', '', row.case),
      node('div', 'learning-comparison', [
        ['原顺序', row.before], ['提案效果', row.after],
      ].map(([label, lines]) => node('div', '', [
        node('strong', '', label),
        node('ul', '', lines.map(line => node('li', '', line))),
      ]))),
    ])
  ));
}

function heading(text, symbol) {
  return node('h3', 'learning-heading', [icon(symbol), text]);
}

function reviewReceipt(review) {
  if (!review?.engine || !review.version || !review.digest) return null;
  return node('details', 'learning-receipt', [
    node('summary', '', [icon('shield', 16), 'DeerFlow 规则校验记录']),
    node('p', '', [node('strong', '', String(review.engine)), ' · ', String(review.version)]),
    node('code', '', String(review.digest)),
  ]);
}

function reportPanel(readReport) {
  const panel = node('details', 'learning-receipt learning-report', [
    node('summary', '', [icon('assessment', 16), '查看审核依据']),
  ]);
  let loaded = false;
  panel.addEventListener('toggle', async () => {
    if (!panel.open || loaded) return;
    loaded = true;
    panel.querySelector('.learning-error')?.remove();
    const content = node('div', 'learning-report-content', '正在读取审核依据…');
    panel.append(content);
    try {
      const saved = await readReport();
      if (!panel.isConnected) return;
      content.replaceChildren();
      const sections = [
        ['调整前的规则', saved.baselineDocument], ['提交时的规则', saved.candidateDocument],
        ['DeerFlow 静态检查报告', saved.report], ['依据的审核记录', saved.experience],
      ];
      for (const [label, value] of sections) {
        if (value) content.append(node('details', '', [
          node('summary', '', label),
          node('pre', '', typeof value === 'string' ? value : JSON.stringify(value, null, 2)),
        ]));
      }
      if (!content.childElementCount) content.textContent = '这条历史建议未留存规则原文和检查报告。';
    } catch (cause) {
      content.remove();
      loaded = false;
      panel.append(node('p', 'learning-error', cause.message));
    }
  });
  return panel;
}

function proposals(data, decision, readReport) {
  const list = node('section', 'learning-reviews', heading(data.canReview ? '规则建议' : '我提交的建议', 'assessment'));
  const labels = { pending: '待审核', approve: '已发布', reject: '已驳回' };
  for (const item of data.proposals) {
    const status = node('strong', 'learning-state', labels[item.decision]);
    status.dataset.state = item.decision;
    const card = node('section', 'learning-card', [
      node('div', 'learning-meta', [status, node('small', '', item.created)]),
      node('p', '', item.instruction), reviewReceipt(item.skillReview),
      reportPanel(() => readReport(item.id)),
    ]);
    if (data.canReview && item.decision === 'pending') {
      card.append(examples(item.examples));
      const actions = node('div', 'learning-actions');
      if (item.base === data.version) {
        actions.append(button('批准发布', () => decision('把这条写作规则发布到所选院区？',
          { proposalId: item.id, decision: 'approve' }), 'learning-primary', 'check'));
      } else card.append(node('p', 'learning-note', '规则已有新版，请以当前版本重新提出。'));
      actions.append(button('驳回建议', () => decision('驳回这条规则建议？',
        { proposalId: item.id, decision: 'reject' })));
      card.append(actions);
    }
    list.append(card);
  }
  if (!data.proposals.length) list.append(node('p', 'learning-empty', '还没有规则建议。'));
  if (data.canReview && data.releases.length) {
    list.append(heading('发布与撤回记录', 'history'));
    for (const row of [...data.releases, {version: 0}]) {
      const entry = node('div', 'learning-card', [
        node('div', 'learning-meta', [node('strong', '', 'v' + row.version),
          node('small', '', [row.created, row.actor].filter(Boolean).join(' · '))]),
        node('p', '', row.instruction || '系统默认规则'),
      ]);
      if (row.version < data.version) entry.append(button('恢复此版', () =>
        decision('确认恢复到 v' + row.version + ' 的写作方式？', { decision: 'rollback', restoreVersion: row.version }), '', 'undo'));
      list.append(entry);
    }
  }
  return list;
}

// The employee's correction is transient. Only the structured proposal is submitted for review.
export async function openAgentLearning(ctx, campusId = '') {
  const root = node('div', 'learning-workspace');
  const error = node('p', 'learning-error');
  error.setAttribute('role', 'alert');
  const content = node('div', 'learning-content', '正在读取院区规则…');
  root.append(error, content);
  const dialog = ctx.detail('助理写作规则', root);
  dialog.classList.add('learning-dialog');
  dialog.querySelector('h2').prepend(node('span', 'learning-mark', icon('spark', 20)));
  async function attempt(fn) {
    error.textContent = '';
    try { await fn(); } catch (cause) {
      error.textContent = cause.message;
      error.scrollIntoView({ block: 'nearest' });
    }
  }
  await attempt(async () => {
    const meta = await read(endpoint);
    if (!meta.topics.length || !meta.campuses.length) {
      content.textContent = '当前岗位没有可提议的规则类别。';
      return;
    }
    const campus = select(meta.campuses);
    if (meta.campuses.some(item => item.id === campusId)) campus.value = campusId;
    const topic = select(meta.topics);
    const body = node('div', 'learning-body');
    content.replaceChildren(node('div', 'learning-scope', [field('生效院区', campus), field('规则类别', topic)]), body);
    let generation = 0;
    let page = 'edit';
    async function reload() {
      const current = ++generation;
      const scope = { campusId: campus.value, topic: topic.value };
      body.replaceChildren(node('p', 'learning-note', '正在读取院区规则…'));
      let data;
      try {
        data = await read(endpoint + '?' + new URLSearchParams(scope));
      } catch (cause) {
        if (current === generation) throw cause;
        return;
      }
      if (current !== generation || !dialog.open) return;
      const post = (action, values) => read(endpoint + '/' + action, { ...scope, ...values });
      const category = meta.topics.find(item => item.id === scope.topic);
      const liveOrder = data.order.length ? data.order : [...category.parts.map(p => p.id), meta.missing[0].id];
      const displayOrder = liveOrder.map(key => category.parts.find(part => part.id === key)).filter(Boolean);
      const missingRule = meta.missing.find(part => part.id === liveOrder.at(-1));
      const overview = node('section', 'learning-current', [
        node('span', 'learning-state', [icon('check', 14), data.version ? '当前规则 · v' + data.version : '当前使用默认规则']),
        node('ol', 'learning-sequence', displayOrder.map(part => node('li', '', part.label))),
        missingRule && node('p', '', missingRule.label),
      ]);
      const edit = node('section', 'learning-editor');
      async function decision(title, payload) {
        await attempt(async () => {
          const confirm = await confirmChange({title, target: campus.selectedOptions[0].text,
            fields: [['规则类别', category.label], ['当前版本', data.version]], confirmLabel: '确认执行'});
          if (!confirm || current !== generation) return;
          await post('review', { ...payload, base: data.version });
          if (current === generation) await reload();
        });
      }
      const review = proposals(data, decision, id =>
        read(endpoint + '?' + new URLSearchParams({ ...scope, proposalId: id })));
      const editTab = button('提出修改', () => activate('edit'));
      const reviewTab = button(data.canReview ? '审核与记录' : '我提交的建议', () => activate('review'));
      const tabs = node('div', 'learning-pages', [editTab, reviewTab]);
      tabs.setAttribute('role', 'group');
      tabs.setAttribute('aria-label', '助理写作规则');
      function activate(next) {
        page = next;
        edit.hidden = page !== 'edit';
        review.hidden = page !== 'review';
        editTab.setAttribute('aria-pressed', String(!edit.hidden));
        reviewTab.setAttribute('aria-pressed', String(!review.hidden));
      }
      const correction = node('textarea');
      correction.maxLength = 1200;
      correction.rows = 3;
      const prompts = {
        meals: '例如，先写实际摄入，再写出席；缺少的项标明待核对',
        handover: '例如，先写待签认事项，再写已完成的工作。',
        visit: '例如，先写就诊日期，再写签发日期，最后列明出处。',
        observations: '例如，先交代观察时间，再写已核实的变化和依据。',
      };
      correction.placeholder = prompts[scope.topic] || prompts.meals;
      const missing = select(meta.missing);
      const priorities = category.parts.map(() => select(category.parts));
      function populate(order) {
        priorities.forEach((box, index) => { box.value = order[index] || category.parts[index].id; });
        missing.value = meta.missing.find(part => part.id === order.at(-1))?.id || meta.missing[0].id;
      }
      populate(liveOrder);
      // Choosing a new position moves the displaced item into the vacated position.
      let priorOrder = priorities.map(box => box.value);
      priorities.forEach((box, index) => box.addEventListener('change', () => {
        const previousIndex = priorOrder.indexOf(box.value);
        if (previousIndex >= 0 && previousIndex !== index) priorities[previousIndex].value = priorOrder[index];
        priorOrder = priorities.map(control => control.value);
      }));
      const preview = node('section', 'learning-preview');
      let previewGeneration = 0;
      function clearPreview() { previewGeneration++; preview.replaceChildren(); }
      for (const box of [...priorities, missing, correction]) box.addEventListener('input', clearPreview);
      async function showPreview(source) {
        if (source === 'correction' && !correction.value.trim()) {
          correction.focus();
          correction.required = true;
          correction.reportValidity();
          return;
        }
        let fields;
        if (source === 'correction') fields = { correction: correction.value };
        else if (source === 'experience') fields = { experience: true };
        else fields = { order: [...priorities.map(box => box.value), missing.value] };
        clearPreview();
        const revision = previewGeneration;
        const draft = await post('preview', fields);
        if (current !== generation || revision !== previewGeneration || !dialog.open) return;
        populate(draft.order);
        priorOrder = priorities.map(box => box.value);
        correction.value = '';
        const title = heading('待提交的规则', 'assessment');
        title.tabIndex = -1;
        preview.replaceChildren(title, node('p', '', draft.instruction), examples(draft.examples));
        const receipt = reviewReceipt(draft.skillReview);
        if (receipt) preview.append(receipt);
        preview.append(
          node('div', 'learning-actions', [button('确认提交建议', () => attempt(async () => {
            await post('propose', { base: draft.base, order: draft.order,
              ...(draft.experienceId ? { experienceId: draft.experienceId } : {}) });
            if (current !== generation) return;
            page = 'review';
            await reload();
            body.querySelector('[aria-pressed="true"]')?.focus();
          }), 'learning-primary', 'check')]));
        title.focus();
      }
      const manual = node('details', 'learning-manual', [
        node('summary', '', [icon('list', 17), '手动调整顺序', icon('down', 16)]),
        node('div', 'learning-manual-body', [
          node('div', 'learning-order', priorities.map((box, i) => field('第 ' + (i + 1) + ' 项', box))),
          field('遇到没有依据的项目', missing),
          node('div', 'learning-actions', [button('预览规则与虚构案例', () => attempt(() => showPreview('order')))]),
        ]),
      ]);
      edit.append(node('section', 'learning-compose', [
        field('你希望助理怎样改进？', correction),
        node('div', 'learning-actions', [
          node('small', 'learning-note', 'DeerFlow 校验候选规则，员工审核后生效。'),
          button('预览修改效果', () => attempt(() => showPreview('correction')), 'learning-primary', 'spark'),
        ]),
      ]), manual,
        button('从审核记录提议', () => attempt(() => showPreview('experience')), 'learning-experience', 'history'),
        preview);
      activate(page);
      body.replaceChildren(overview, tabs, edit, review);
    }
    for (const control of [campus, topic]) control.addEventListener('change', () => attempt(reload));
    await reload();
  });
}
