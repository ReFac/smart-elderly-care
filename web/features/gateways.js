import { commentInput } from '../lib/change-review.js';
import { voiceProposal } from './speech-input.js';
import { roundsInbox } from './rounds-desk.js';
import {
  node,
  page,
  btn,
  choose,
  facts,
  section,
  badge,
  runForm,
  field,
  memo,
  select,
  options,
  residentName,
  tabs,
  today,
} from './shared.js';

const sources = {
  youle: '优乐模型',
  radar: '超声波 / 雷达',
  sensor: '房间传感器',
  mijia: '米家授权设备',
  badge: '护理工牌',
};
const signals = { possible_fall: '疑似跌倒', prolonged_bedrest: '持续卧床提示' };

function has(ctx, permission) {
  const user = ctx.state.user;
  return user?.kind === 'owner' || user?.permissions?.includes(permission);
}
const choices = (obj) => Object.entries(obj).map(([value, label]) => ({ value, label }));
const roomName = (bed) => bed.ward + ' / ' + bed.label.replace(/-[^-]+$/, '');
const uniqueId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('');

function simulate(ctx) {
  const rooms = new Map();
  for (const bed of ctx.state.beds) if (!rooms.has(roomName(bed))) rooms.set(roomName(bed), bed.id);
  runForm(ctx, {
    title: '登记模拟信号',
    action: 'gw.ingest',
    description:
      '模拟设备上报一次观测。系统记录当时房间内的在住长者，护士现场复核后再记入相应档案。',
    fields: [
      select('source', '设备来源', choices(sources)),
      select('signal', '检测信号', choices(signals)),
      select(
        'bedId',
        '观测房间',
        Array.from(rooms, ([label, value]) => ({ value, label })),
      ),
      field('eventId', '源事件编号', { value: uniqueId() }),
      field('evidenceRef', '图片、示意图或片段的证据编号', { required: false }),
      memo('observation', '设备观测摘要'),
    ],
    submitLabel: '登记待复核预警',
  });
}

function newProposal(ctx) {
  const tasks = ctx.state.tasks.filter((t) => t.status === '待执行' && t.date <= today(ctx));
  return voiceProposal(
    ctx,
    tasks.map((t) => [
      t.id,
      residentName(ctx, t.residentId) + ' · ' + t.title + ' · ' + t.date + ' ' + t.time,
    ]),
    uniqueId(),
  );
}

function review(ctx, row) {
  const names = row.candidates.map((id) => ({ value: id, label: residentName(ctx, id) }));
  runForm(ctx, {
    title: '护士现场复核',
    action: 'gw.review',
    description:
      row.room +
      ' · ' +
      signals[row.signal] +
      '。请核对现场信息。已核实事件将追加到所选长者的历史档案。',
    fields: [
      select(
        'decision',
        '复核结论',
        options(row.candidates.length ? ['已核实', '误报', '无法核实'] : ['误报', '无法核实']),
      ),
      select(
        'residentId',
        '现场核实的长者',
        [{ value: '', label: '请选择，误报或无法核实可留空' }, ...names],
        { required: false },
      ),
      memo('note', '现场情况与处置记录', true),
    ],
    map: (v) => ({ ...v, alertId: row.id }),
    submitLabel: '保存复核结论',
  });
}

const stamp = (value) => (value ? value.slice(0, 19).replace('T', ' ') : '—');

function mark(ctx, name, tone = '') {
  return node('span', 'gw-mark ' + tone, ctx.ui.icon(name, 20));
}

function inspectAlert(ctx, row) {
  const pending = row.status === '待复核';
  const headline = node('div', 'gw-event-heading', [
    mark(ctx, 'bell', pending ? 'gw-gold' : ''),
    node('div', '', [node('strong', '', row.room), node('small', '', sources[row.source])]),
    badge(ctx, row.status, pending ? 'amber' : 'blue'),
  ]);
  const observed = row.observations.map((entry) =>
    node('li', '', [
      node('div', 'gw-step-head', [
        node('h3', '', sources[entry.source] + '观测'),
        node('time', '', stamp(entry.observedAt)),
      ]),
      node('p', '', entry.observation || '设备未附观测摘要'),
      facts([
        ['设备提示的长者', row.residentHint ? residentName(ctx, row.residentHint) : '待现场核实'],
        ['证据编号', entry.evidenceRef],
        ['源事件编号', entry.eventId],
      ]),
    ]),
  );
  const resolution = node('li', pending ? 'gw-step-pending' : '', [
    node('div', 'gw-step-head', [
      node('h3', '', '现场复核'),
      node('time', '', pending ? '待处理' : stamp(row.reviewedAt)),
    ]),
    pending
      ? node('p', '', '护士核实房间和长者后，可填写现场情况。')
      : node('p', '', row.reviewNote),
    pending
      ? btn(ctx, '填写复核结论', () => review(ctx, row), 'primary')
      : facts([
          ['确认长者', residentName(ctx, row.residentId)],
          ['复核人账号', row.reviewedBy],
        ]),
  ]);
  ctx.detail(
    signals[row.signal],
    node('div', 'gw-detail', [headline, node('ol', 'gw-steps', [observed, resolution])]),
  );
}

function changePreview(ctx, task, row) {
  const record = (title, current, note, actor) =>
    node('section', 'gw-change-column', [
      node('h3', '', title),
      facts([
        ['工单状态', current],
        ['执行记录', note],
        ['执行人', actor],
      ]),
    ]);
  return node('div', 'gw-change', [
    record(
      '当前工单',
      task?.status || '不可用',
      task?.note || '尚未填写',
      task?.operator || '待登记',
    ),
    record('确认后写入', '已完成', row.note, ctx.state.user.displayName),
  ]);
}

async function confirmProposal(ctx, row, trigger) {
  try {
    const changes = await ctx.get('/api/voice-proposals/' + encodeURIComponent(row.id));
    if (!trigger.isConnected) return;
    row = { ...row, ...changes };
  } catch (error) {
    ctx.toast(error.message);
    return;
  }
  const task = ctx.state.tasks.find((t) => t.id === row.taskId);
  const comment = commentInput();
  const approve = btn(
    ctx,
    '确认并完成工单',
    async () => {
      approve.disabled = true;
      try {
        await ctx.command(
          'gw.confirm',
          { proposalId: row.id },
          { confirmed: true, comment: comment.read() },
        );
      } finally {
        approve.disabled = false;
      }
    },
    'primary',
  );
  const dismiss = btn(ctx, '退回申请', () => {
    runForm(ctx, {
      title: '退回语音申请',
      action: 'gw.dismiss',
      fields: [memo('reason', '退回原因', true)],
      map: (v) => ({ ...v, proposalId: row.id }),
      submitLabel: '确认退回',
    });
    const dialog = document.querySelector('dialog[open]:last-of-type');
    if (dialog) dialog.dataset.proposalId = row.id;
  });
  const content = node('div', 'gw-detail', [
    node('div', 'gw-event-heading', [
      mark(ctx, 'care'),
      node('div', '', [node('strong', '', row.title), node('small', '', row.taskId)]),
      badge(ctx, '待确认', 'amber'),
    ]),
    facts([
      ['服务长者', residentName(ctx, row.residentId)],
      ['申请时房间', row.room],
      ['申请人', row.requester],
      ['申请时间', stamp(row.createdAt)],
    ]),
    node('section', 'gw-transcript', [
      node('h3', '', '转写原文'),
      node('blockquote', '', row.transcript),
    ]),
    changePreview(ctx, task, row),
    comment.element,
    node('footer', 'gw-confirm-foot', [
      node('small', '', '确认后写入工单并从共用队列移除。'),
      choose(dismiss, approve),
    ]),
  ]);
  ctx.detail('确认语音申请', content).dataset.proposalId = row.id;
}

function searchBox(ctx, placeholder) {
  const input = node('input');
  input.type = 'search';
  input.placeholder = placeholder;
  input.setAttribute('aria-label', placeholder);
  return { input, label: node('label', 'gw-search', [ctx.ui.icon('search', 17), input]) };
}

function queueRow(ctx, row, alerts) {
  const pending = row.status === '待复核';
  const title = alerts ? signals[row.signal] : row.title;
  const meta = alerts
    ? row.observations.map((e) => sources[e.source]).join('、')
    : '申请人 ' + row.requester;
  const note = alerts ? row.observation : null;
  const action = btn(
    ctx,
    alerts ? (pending ? '查看并复核' : '查看记录') : '核对改动',
    (event) => (alerts ? inspectAlert(ctx, row) : confirmProposal(ctx, row, event.currentTarget)),
    'secondary',
  );
  return node('li', 'gw-event', [
    mark(ctx, alerts ? 'pulse' : 'care', alerts && pending ? 'gw-gold' : ''),
    node('div', 'gw-event-main', [
      node('div', 'gw-event-title', [
        node('strong', '', title),
        alerts && pending
          ? badge(ctx, row.priority, row.signal === 'possible_fall' ? 'red' : 'neutral')
          : null,
        badge(ctx, alerts ? row.status : '待确认', pending || !alerts ? 'amber' : 'blue'),
      ]),
      node('div', 'gw-event-meta', [
        node('span', '', row.room),
        node('span', '', alerts ? meta : residentName(ctx, row.residentId) + ' · ' + meta),
      ]),
      note ? node('p', '', note) : null,
    ]),
    node('div', 'gw-event-action', [
      node('time', '', stamp(alerts ? row.observedAt : row.createdAt)),
      action,
    ]),
  ]);
}

function queuePanel(ctx, alerts) {
  const rows = alerts ? ctx.state.gatewayAlerts : ctx.state.voiceQueue;
  const search = searchBox(ctx, alerts ? '搜索房间、事件编号或设备来源' : '搜索房间、工单或申请人');
  const filter = node('select', 'gw-select');
  filter.setAttribute('aria-label', '筛选预警状态');
  for (const [value, label] of [
    ['pending', '待复核'],
    ['resolved', '已复核记录'],
    ['all', '全部预警'],
  ])
    filter.add(new Option(label, value));
  const count = node('span', 'gw-count');
  count.setAttribute('aria-live', 'polite');
  const list = node('ul', 'gw-feed');
  const blank = node('div', 'gw-blank');
  const more = btn(ctx, '显示更多记录', () => {
    limit += 12;
    render();
  });
  let limit = 12;
  function render() {
    const needle = search.input.value.trim().toLocaleLowerCase();
    const subset = rows.filter((r) => {
      if (
        alerts &&
        ((filter.value === 'pending' && r.status !== '待复核') ||
          (filter.value === 'resolved' && r.status === '待复核'))
      )
        return false;
      const keys = alerts
        ? [
            r.room,
            r.priority,
            signals[r.signal],
            ...r.observations.flatMap((e) => [e.eventId, sources[e.source]]),
          ]
        : [r.room, r.title, r.requester, residentName(ctx, r.residentId)];
      return !needle || keys.join(' ').toLocaleLowerCase().includes(needle);
    });
    count.textContent = subset.length + ' 条';
    list.replaceChildren(...subset.slice(0, limit).map((r) => queueRow(ctx, r, alerts)));
    blank.hidden = !!subset.length;
    blank.replaceChildren(
      ctx.ui.icon(alerts ? 'bell' : 'check', 26),
      node(
        'span',
        '',
        needle
          ? '没有匹配的记录'
          : alerts
            ? filter.value === 'pending'
              ? '当前没有待复核预警'
              : '当前没有设备预警记录'
            : '当前没有待确认申请',
      ),
    );
    more.hidden = subset.length <= limit;
  }
  const reset = () => {
    limit = 12;
    render();
  };
  search.input.addEventListener('input', reset);
  filter.addEventListener('change', reset);
  render();
  return node('section', 'gw-panel', [
    node('header', 'gw-panel-head', [
      node('div', 'gw-title-line', [
        node('h2', '', alerts ? '房间设备事件' : '语音变更申请'),
        count,
      ]),
      node('div', 'gw-tools', [search.label, alerts ? filter : null]),
    ]),
    list,
    blank,
    node('div', 'gw-more', more),
  ]);
}

function inbox(ctx) {
  const actions = choose(),
    views = [],
    metadata = {};
  if (has(ctx, 'gateway.simulate')) actions.append(btn(ctx, '模拟设备信号', () => simulate(ctx)));
  if (has(ctx, 'voice') && has(ctx, 'care'))
    actions.append(btn(ctx, '登记语音草稿', () => newProposal(ctx), 'primary'));
  if (has(ctx, 'audit') && ctx.available('activity'))
    actions.append(btn(ctx, '查看操作日志', () => ctx.go('activity')));
  if (has(ctx, 'alerts')) {
    metadata.alerts = [
      'bell',
      '待护士现场复核',
      ctx.state.gatewayAlerts.filter((a) => a.status === '待复核').length,
    ];
    views.push(['alerts', '设备预警', () => queuePanel(ctx, true)]);
  }
  if (has(ctx, 'voice.confirm') && has(ctx, 'care')) {
    metadata.voice = ['care', '待授权护工确认', ctx.state.voiceQueue.length];
    views.push(['voice', '待确认语音', () => queuePanel(ctx, false)]);
  }
  if (has(ctx, 'care') || has(ctx, 'clinical')) {
    metadata.rounds = ['care', '待核对的照护事项', null];
    views.push(['rounds', '巡查提醒', () => roundsInbox(ctx)]);
  }
  let queue;
  if (views.length) {
    queue = tabs('inbox', views);
    queue.classList.add('gw-queues');
    for (const tab of queue.querySelectorAll('[role=tab]')) {
      const label = tab.textContent,
        [ic, hint, count] = metadata[tab.dataset.key];
      tab.replaceChildren(
        mark(ctx, ic),
        node('span', 'gw-tab-text', [node('strong', '', label), node('small', '', hint)]),
        ...(count === null ? [] : [node('b', 'gw-tab-count', count)]),
      );
      tab.setAttribute('aria-label', label + '，' + hint + (count === null ? '' : count + '条'));
    }
  } else queue = ctx.ui.empty('可以通过上方按钮登记设备观测或提交语音变更申请。');
  return page(ctx, '预警与人工确认', '', actions, queue);
}

const groupIcons = {
  工牌与定位: 'location',
  质控与通知: 'shield',
  报表与人员: 'reports',
  院内设备: 'pulse',
  语音与文档: 'file',
};

function schemaDetails(ctx, title, schema, open = false) {
  const fields = Object.entries(schema.properties || {});
  const rows = fields.map(([name, spec]) => {
    const notes = [];
    if (spec.format) notes.push(spec.format);
    if (spec.enum) notes.push(spec.enum.join(' / '));
    if (spec.items) notes.push('成员 ' + spec.items.type);
    if (spec.minimum != null) notes.push('≥ ' + spec.minimum);
    if (spec.maximum != null) notes.push('≤ ' + spec.maximum);
    if (spec.minLength != null) notes.push('最少 ' + spec.minLength + ' 字符');
    if (spec.maxLength != null) notes.push('最多 ' + spec.maxLength + ' 字符');
    if (spec.pattern) notes.push(spec.pattern);
    return node('tr', '', [
      node('th', '', node('code', '', name)),
      node('td', '', spec.type),
      node('td', '', schema.required?.includes(name) ? '必填' : '选填'),
      node('td', '', notes.join(' · ') || '—'),
    ]);
  });
  const raw = node('details', 'gw-raw', [
    node('summary', '', '完整 JSON Schema'),
    node('pre', '', JSON.stringify(schema, null, 2)),
  ]);
  const table = node('table', 'gw-field-table', [
    node(
      'thead',
      '',
      node(
        'tr',
        '',
        ['字段', '类型', '填写规则', '约束'].map((h) => node('th', '', h)),
      ),
    ),
    node('tbody', '', rows),
  ]);
  table.setAttribute('aria-label', title);
  const box = node('details', 'gw-schema', [
    node('summary', '', [
      node('strong', '', title),
      node('span', '', fields.length + ' 个字段'),
      ctx.ui.icon('down', 15),
    ]),
    node('div', 'gw-schema-body', [node('div', 'gw-fields-scroll', table), raw]),
  ]);
  box.open = open;
  return box;
}

function inspectContract(ctx, row) {
  ctx.detail(
    row.title,
    node('div', 'gw-detail', [
      node('div', 'gw-contract-path', [node('b', '', row.method), node('code', '', row.path)]),
      facts([
        ['接口版本', row.version],
        [
          '资料依据',
          row.pages.length ? '工牌产品介绍第 ' + row.pages.join('、') + ' 页' : '机构补充需求',
        ],
        ['当前响应', 'HTTP 501 · 待接入'],
        ['配置权限', row.ownerOnly ? '仅总管理员' : '按机构授权'],
      ]),
      section('能力说明', node('p', 'gw-description', row.description)),
      section('接入条件', node('p', 'gw-description', row.policy)),
      schemaDetails(ctx, '请求参数', row.requestSchema, true),
      schemaDetails(ctx, '适配器响应', row.responseSchema),
    ]),
  );
}

function integrations(ctx) {
  const rows = ctx.state.integrationCatalog;
  const counts = new Map();
  for (const r of rows) counts.set(r.group, (counts.get(r.group) || 0) + 1);
  const nav = node('nav', 'gw-category');
  nav.setAttribute('aria-label', '接口分类');
  nav.append(node('h2', '', '能力分类'));
  const search = searchBox(ctx, '搜索接口名称、编号或用途');
  const grid = node('div', 'gw-contracts');
  const label = node('h2', '', '全部接口'),
    result = node('span', 'gw-count');
  result.setAttribute('aria-live', 'polite');
  let selected = '';
  const controls = new Map();
  for (const [group, count] of [['', rows.length], ...counts]) {
    const menu = node('button', 'gw-category-item', [
      ctx.ui.icon(groupIcons[group] || 'layers', 16),
      node('span', '', group || '全部接口'),
      node('b', '', count),
    ]);
    menu.type = 'button';
    menu.addEventListener('click', () => {
      selected = group;
      render();
    });
    controls.set(group, menu);
    nav.append(menu);
  }
  function render() {
    for (const [key, button] of controls)
      button.setAttribute('aria-pressed', String(key === selected));
    const needle = search.input.value.trim().toLocaleLowerCase();
    const matches = rows.filter(
      (r) =>
        (!selected || selected === r.group) &&
        [r.title, r.id, r.group, r.description].join(' ').toLocaleLowerCase().includes(needle),
    );
    result.textContent = matches.length + ' 个接口';
    label.textContent = selected || '全部接口';
    grid.replaceChildren(
      ...matches.map((r) => {
        const card = node('button', 'gw-contract', [
          node('span', 'gw-contract-meta', [
            node('span', '', [ctx.ui.icon(groupIcons[r.group], 15), r.group]),
            node('small', '', '待接入'),
          ]),
          node('strong', '', r.title),
          node('p', '', r.description),
          node('span', 'gw-contract-id', [node('code', '', r.id), ctx.ui.icon('chevron', 15)]),
        ]);
        card.type = 'button';
        card.addEventListener('click', () => inspectContract(ctx, r));
        return card;
      }),
    );
    if (!matches.length)
      grid.append(node('div', 'gw-blank', [ctx.ui.icon('search', 24), '没有匹配的接口']));
  }
  search.input.addEventListener('input', render);
  render();
  const catalog = node('div', 'gw-catalog', [
    nav,
    node('section', 'gw-catalog-main', [
      node('header', 'gw-panel-head', [
        node('div', 'gw-title-line', [label, result]),
        search.label,
      ]),
      grid,
    ]),
  ]);
  return page(
    ctx,
    '设备与模型接口',
    '查看设备能力、请求字段和接入条件。当前预留端口统一返回 HTTP 501。',
    null,
    catalog,
  );
}

export function renderGateways(route, ctx) {
  return route === 'integrations' ? integrations(ctx) : inbox(ctx);
}
