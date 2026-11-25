import { displayLocale } from '../lib/locale.js';
import { node, today } from './shared.js';
import { runtimeNames } from './evidence-runtime.js';

const endpoint = '/api/provider/usage';
const number = new Intl.NumberFormat(displayLocale);
const stamp = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
const units = { tokens: 'Token', pages: '页', seconds: '秒', characters: '字符', calls: '次' };
const statusNames = {
  pending: '请求中', uncertain: '待对账', review: '待复核', complete: '已核实',
  failed: '失败', empty: '无结果', settled: '已对账',
};
const views = [
  ['byFeature', '按功能'], ['byActor', '按员工'], ['byDay', '按日期'], ['records', '调用明细'],
];

let lastSelection;

function format(value) {
  return value == null ? '—' : number.format(value);
}

function amount(value, unit) {
  return value == null ? '—' : [format(value), units[unit] || unit].join(' ');
}

function label(text, control) {
  return node('label', 'usage-field', [node('span', '', text), control]);
}

function dateField(name, value, limit) {
  const input = node('input', 'fx-input');
  input.type = 'date';
  input.name = name;
  input.value = value;
  input.max = limit;
  input.required = true;
  return input;
}

function selectOptions(select, all, options, selected) {
  select.replaceChildren(new Option(all, ''));
  for (const { id, label, kind } of options)
    select.add(new Option(kind === 'owner' && label !== 'Owner' ? label + ' · Owner' : label, id));
  select.value = options.some(({ id }) => id === selected) ? selected : '';
}

function tokenDetails(totals) {
  const { cacheHitTokens, cacheMissTokens, outputTokens } = totals;
  const measured = cacheHitTokens + cacheMissTokens;
  const percentage = measured > 0 ? Math.round(cacheHitTokens * 1000 / measured) / 10 : null;
  const breakdown = [
    ['缓存命中', cacheHitTokens, 'hit'],
    ['缓存未命中', cacheMissTokens, 'miss'],
    ['输出', outputTokens, 'output'],
  ];
  const totalMeasured = measured + outputTokens;
  const info = [
    totals.inputTokens == null ? '' : '已知输入 ' + amount(totals.inputTokens, 'tokens'),
    percentage === null ? '' : '缓存命中率 ' + percentage + '%',
  ].filter(Boolean);
  const meter = node('div', 'usage-split', breakdown.filter(([, count]) => count > 0).map(([, count, type]) => {
    const bar = node('span', 'usage-' + type);
    bar.style.flexGrow = count;
    return bar;
  }));
  meter.setAttribute('aria-hidden', 'true');
  return node('div', 'usage-token-details', [
    totalMeasured > 0 ? meter : null,
    node('dl', 'usage-breakdown', breakdown.map(([name, count, type]) =>
      node('div', '', [
        node('dt', '', [node('i', 'usage-' + type), name]),
        node('dd', '', format(count)),
      ]))),
    info.length ? node('p', 'usage-muted', info.join(' · ')) : null,
  ]);
}

function summaryCards(totals) {
  const token = node('article', 'usage-token', [
    node('div', 'usage-card-label', '模型总用量'),
    node('div', 'usage-value', [node('strong', '', format(totals.tokens)), node('span', '', 'Token')]),
    tokenDetails(totals),
  ]);
  const service = (name, value, unit) => node('article', 'usage-service', [
    node('h3', '', name),
    node('div', 'usage-value', [node('strong', '', format(value)), node('span', '', unit)]),
  ]);
  return node('section', 'usage-summary', [
    token,
    node('div', 'usage-services', [
      service('文档识别 · OCR', totals.ocrPages, '页'),
      service('语音转写 · ASR', totals.asrSeconds, '秒'),
      service('语音朗读 · TTS', totals.ttsCharacters, '字符'),
      service('独立联网搜索', totals.searchCalls, '次'),
    ]),
  ]);
}

function statusBadge(value) {
  const style = ['complete', 'settled'].includes(value) ? 'ok' :
    ['pending', 'uncertain', 'review'].includes(value) ? 'wait' : 'neutral';
  return node('span', 'usage-status usage-status-' + style, statusNames[value] || '待核对');
}

function detailValue(value, missing) {
  const cell = node('span', '', format(value));
  if (missing) cell.title = value == null ? '供应商回执缺少此细项' : '仅显示已有回执细项的用量';
  if (missing && value != null) cell.append(node('sup', 'usage-partial', '*'));
  return cell;
}

function tableGrid(columns, rows, name) {
  const headers = node('tr', '', columns.map(([heading, , right]) => {
    const th = node('th', right ? 'fx-end' : '', heading);
    th.scope = 'col';
    return th;
  }));
  const grid = node('table', 'fx-table usage-table', [
    node('thead', '', headers),
    node('tbody', '', rows.map(row => node('tr', '', columns.map(([, cell, right]) =>
      node('td', right ? 'fx-end' : '', cell(row)))))),
  ]);
  grid.setAttribute('aria-label', name);
  return node('div', 'fx-table-wrap usage-table-wrap', grid);
}

function groupGrid(rows, group, setFilter) {
  const names = { byFeature: '功能', byActor: '账号', byDay: '日期' };
  function rowName(row) {
    if (group === 'byDay') return row.label || row.id;
    const button = node('button', 'usage-row-filter', row.label);
    button.type = 'button';
    button.addEventListener('click', () => setFilter(group, row.id));
    button.setAttribute('aria-label', '筛选' + names[group] + ' ' + row.label);
    return button;
  }
  const cells = [
    [names[group], rowName],
    ['调用数', row => format(row.calls), true],
    ['总 Token', row => format(row.tokens), true],
    ['缓存命中', row => detailValue(row.cacheHitTokens, row.unclassifiedCacheCalls), true],
    ['缓存未命中', row => detailValue(row.cacheMissTokens, row.unclassifiedCacheCalls), true],
    ['输出 Token', row => detailValue(row.outputTokens, row.unclassifiedTokenCalls), true],
    ['OCR 页', row => format(row.ocrPages), true],
    ['ASR 秒', row => format(row.asrSeconds), true],
    ['朗读字符', row => format(row.ttsCharacters), true],
    ['搜索次数', row => format(row.searchCalls), true],
  ];
  return tableGrid(cells, rows, 'AI ' + names[group] + '用量汇总');
}

function time(at) {
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? '—' : stamp.format(date);
}

function recordsGrid(records, selectTask) {
  function taskLink(row) {
    if (!row.taskId) return '—';
    const button = node('button', 'usage-row-filter', row.taskId);
    button.type = 'button';
    button.addEventListener('click', () => selectTask(row.taskId));
    return button;
  }
  return tableGrid([
    ['调用时间', row => time(row.at)],
    ['经办账号', row => row.actorLabel],
    ['功能', row => row.featureLabel],
    ['执行组件', row => runtimeNames[row.runtime] || '—'],
    ['任务编号', taskLink],
    ['状态', row => statusBadge(row.status)],
    ['已核实用量', row => amount(row.amount, row.unit), true],
    ['预留量', row => row.reserved > 0 ? amount(row.reserved, row.unit) : '—', true],
    ['输入 Token', row => detailValue(row.inputTokens, row.inputTokens == null && row.unit === 'tokens'), true],
    ['缓存命中', row => detailValue(row.cacheHitTokens, row.cacheHitTokens == null && row.unit === 'tokens'), true],
    ['缓存未命中', row => detailValue(row.cacheMissTokens, row.cacheMissTokens == null && row.unit === 'tokens'), true],
    ['输出 Token', row => detailValue(row.outputTokens, row.outputTokens == null && row.unit === 'tokens'), true],
  ], records, 'AI 调用明细');
}

function warning(totals) {
  const notices = [];
  if (totals.pendingCalls)
    notices.push(format(totals.pendingCalls) + ' 次调用正在处理或待对账，当前预留 ' +
      amount(totals.reservedTokens, 'tokens') + '。');
  if (totals.unclassifiedTokenCalls)
    notices.push(format(totals.unclassifiedTokenCalls) + ' 次模型调用缺少输入或输出细项。');
  if (totals.unclassifiedCacheCalls)
    notices.push(format(totals.unclassifiedCacheCalls) + ' 次模型调用缺少缓存细项。');
  if (totals.unclassifiedCacheCalls || totals.unclassifiedTokenCalls)
    notices.push('“—”表示细项未知，“*”表示仅合计了已有细项的部分。');
  return notices.length ? node('p', 'usage-notice', notices.join('')) : null;
}

export function providerUsage(ctx) {
  if (ctx.state.user?.kind !== 'owner') return ctx.ui.empty('AI 用量仅 Owner 可查看');
  const owner = ctx.state.user.id;
  const currentDay = today(ctx);
  const monthStart = currentDay.slice(0, 7) + '-01';
  const defaults = { start: monthStart, end: currentDay, feature: '', actorId: '', view: 'byFeature' };
  const previous = lastSelection?.owner === owner ? lastSelection : defaults;
  const range = node('span', 'usage-muted');
  const status = node('p', 'usage-live');
  status.setAttribute('role', 'status');
  const output = node('div', 'usage-result');
  const start = dateField('start', previous.start, currentDay);
  const end = dateField('end', previous.end, currentDay);
  const features = node('select', 'fx-input');
  features.name = 'feature';
  const actors = node('select', 'fx-input');
  actors.name = 'actorId';
  const task = node('input', 'fx-input');
  task.name = 'taskId';
  task.placeholder = '粘贴或点击明细中的任务编号';
  task.value = previous.taskId || '';
  selectOptions(features, '全部功能', [], '');
  selectOptions(actors, '全部账号', [], '');

  const submit = node('button', 'btn btn-primary', '查询');
  submit.type = 'submit';
  const reset = ctx.ui.button('本月', () => {
    start.value = monthStart;
    end.value = currentDay;
    features.value = actors.value = task.value = '';
    form.requestSubmit();
  }, 'secondary');
  const form = node('form', 'usage-filters', [
    label('开始日期', start), label('结束日期', end),
    label('功能', features), label('经办账号', actors), label('任务编号', task),
    node('div', 'usage-filter-actions', [reset, submit]),
  ]);
  const root = node('section', 'usage-page', [
    node('header', 'usage-screen-header', [
      node('div', 'usage-heading', [ctx.ui.icon('spark', 22), node('h2', '', '用量概览')]),
      range,
    ]),
    form, status, output,
  ]);

  let generation = 0;
  let selected = previous.view;
  let criteria = { start: previous.start, end: previous.end, feature: previous.feature, actorId: previous.actorId, taskId: task.value };
  let data;

  const preferences = () => { lastSelection = { owner, ...criteria, view: selected }; };

  function setFilter(group, id) {
    (group === 'byFeature' ? features : actors).value = id;
    form.requestSubmit();
  }

  function draw() {
    const viewControls = node('div', 'usage-view-controls', views.map(([key, text]) => {
      const button = node('button', '', text);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(selected === key));
      button.addEventListener('click', () => {
        selected = key;
        preferences();
        draw();
        output.querySelector('button[aria-pressed="true"]')?.focus();
      });
      return button;
    }));
    viewControls.setAttribute('role', 'group');
    viewControls.setAttribute('aria-label', '用量汇总视图');

    const picked = data[selected];
    const records = selected === 'records';
    const rows = records ? picked.items : picked;
    const title = records ? '调用明细' : views.find(([key]) => key === selected)[1] + '汇总';
    const panel = node('section', 'fx-panel usage-ledger', [
      node('div', 'fx-toolbar usage-ledger-header', [
        node('h3', '', title),
        viewControls,
      ]),
      rows.length ? records ? recordsGrid(rows, id => {
        task.value = id;
        features.value = actors.value = '';
        form.requestSubmit();
      }) : groupGrid(rows, selected, setFilter)
        : node('p', 'fx-empty', '此筛选范围内没有调用记录。'),
    ]);
    if (records && picked.total > picked.pageSize) {
      const pages = Math.ceil(picked.total / picked.pageSize);
      const earlier = ctx.ui.button('上一页', () => load(picked.page - 1), 'secondary');
      const later = ctx.ui.button('下一页', () => load(picked.page + 1), 'secondary');
      earlier.disabled = picked.page <= 1;
      later.disabled = picked.page >= pages;
      panel.append(node('div', 'fx-pagination', [
        node('span', 'fx-muted', '第 ' + picked.page + ' / ' + pages + ' 页 · 共 ' + format(picked.total) + ' 条'),
        earlier, later,
      ]));
    }
    output.replaceChildren(summaryCards(data.summary), panel);
    const note = warning(data.summary);
    if (note) output.insertBefore(note, panel);
  }

  async function load(page = 1) {
    const requested = ++generation;
    const params = new URLSearchParams({ ...criteria, page: String(page) });
    status.textContent = '正在读取 AI 用量…';
    output.setAttribute('aria-busy', 'true');
    for (const input of [features, actors]) input.disabled = true;
    if (page === 1) output.replaceChildren();
    try {
      const result = await ctx.get(endpoint + '?' + params.toString());
      if (requested !== generation || !root.isConnected) return;
      data = result;
      selectOptions(features, '全部功能', data.features, criteria.feature);
      selectOptions(actors, '全部账号', data.actors, criteria.actorId);
      range.textContent = data.range.start + ' 至 ' + data.range.end + ' · 上海时间';
      status.textContent = format(data.summary.calls) + ' 次调用';
      draw();
    } catch (error) {
      if (requested !== generation || !root.isConnected) return;
      status.textContent = '';
      output.replaceChildren(node('div', 'usage-notice', [
        node('p', '', error.message || '暂时无法读取 AI 用量。'),
        ctx.ui.button('重试', () => load(page), 'secondary'),
      ]));
    } finally {
      if (requested === generation) {
        output.setAttribute('aria-busy', 'false');
        for (const input of [features, actors]) input.disabled = false;
      }
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (start.value > end.value) {
      status.textContent = '开始日期应早于或等于结束日期。';
      start.focus();
      return;
    }
    criteria = { start: start.value, end: end.value, feature: features.value, actorId: actors.value, taskId: task.value.trim() };
    preferences();
    load();
  });
  load();
  return root;
}
