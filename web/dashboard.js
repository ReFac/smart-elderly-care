import { inquiryForm } from './features/residency.js';
import { completeTask } from './features/care.js';
import { badge, button, el, empty, icon } from './lib/ui.js';

const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
  timeZone: 'Asia/Shanghai',
});

function group(tag, className, ...children) {
  const node = el(tag, className);
  node.append(...children.filter(Boolean));
  return node;
}

function action(label, onClick, className) {
  const item = el('button', className, label);
  item.type = 'button';
  item.addEventListener('click', onClick);
  return item;
}

function dateBefore(today, offset) {
  const date = new Date(today + 'T12:00:00Z');
  date.setUTCDate(date.getUTCDate() - offset);
  return date.toISOString().slice(0, 10);
}

function header(ctx) {
  const s = ctx.state;
  const title = group(
    'div',
    'op-page-title',
    el('h1', '', '机构运营总览'),
    group(
      'div',
      'op-page-meta',
      icon('building', 15),
      el('span', '', s.uiSettings.institutionName),
      el('i', 'op-meta-sep'),
      el('span', '', dateFormat.format(new Date(s.today + 'T12:00:00+08:00')))
    )
  );
  const actions = el('div', 'op-header-actions');
  if (ctx.available('inbox'))
    actions.append(button('预警与确认', () => ctx.go('inbox'), 'secondary', 'bell'));
  if (ctx.available('intake') && ctx.permitted('intake'))
    actions.append(button('接待登记', () => inquiryForm(ctx), 'secondary', 'plus'));
  if (ctx.available('assistants')) {
    const link = group('a', 'btn btn-primary', icon('spark', 16), el('span', '', '发起 Agent 协作'));
    link.href = '#assistants';
    actions.append(link);
  }
  return group('header', 'op-header', title, actions);
}

function getMetrics(ctx, tasks) {
  const s = ctx.state,
    items = [];
  const add = (label, value, unit, note, ic, route, tab) =>
    items.push({ label, value, unit, note, ic, open: () => ctx.go(route, tab) });
  if (ctx.available('residents')) {
    const active = s.residents.filter((p) => p.status === '在住').length;
    add(
      '在住长者',
      active,
      '人',
      '本月入住 ' +
        s.residents.filter((p) => p.admittedAt?.startsWith(s.today.slice(0, 7))).length +
        ' 人',
      'people',
      'residents'
    );
  }
  if (ctx.available('beds')) {
    const vacant = s.beds.filter((b) => b.status === '空闲').length;
    add('可用床位', vacant, '床', '核定 ' + s.beds.length + ' 张床位', 'bed', 'beds');
  }
  if (ctx.available('care') && ctx.permitted('care')) {
    const done = tasks.filter((t) => t.status === '已完成').length;
    add('今日照护', tasks.length, '项', '已完成 ' + done + ' 项', 'care', 'care', 'tasks');
  }
  if (ctx.available('billing') && ctx.permitted('finance')) {
    const due = s.bills.filter((b) => b.balance > 0);
    add(
      '待缴账单',
      due.length,
      '笔',
      '待缴 ¥' + number.format(due.reduce((sum, b) => sum + b.balance, 0)),
      'wallet',
      'billing',
      'bills'
    );
  }
  if (items.length < 4 && ctx.available('inbox') && ctx.permitted('alerts')) {
    add(
      '待核实预警',
      s.gatewayAlerts.filter((a) => a.status === '待复核').length,
      '条',
      '待护士现场复核',
      'bell',
      'inbox',
      'alerts'
    );
  }
  if (items.length < 4 && ctx.available('shifts') && ctx.permitted('shifts')) {
    const shifts = s.shifts.filter((x) => x.date === s.today);
    add(
      '今日值班',
      new Set(shifts.map((x) => x.staff)).size,
      '人',
      '共 ' + shifts.length + ' 个班次',
      'shifts',
      'shifts'
    );
  }
  if (items.length < 4 && ctx.available('inventory') && ctx.permitted('inventory')) {
    add(
      '库存品类',
      s.inventory.length,
      '类',
      '低于库存下限 ' + s.inventory.filter((p) => p.quantity < p.minimum).length + ' 类',
      'box',
      'inventory',
      'stock'
    );
  }
  if (items.length < 4 && ctx.available('reports') && ctx.permitted('reports')) {
    add('报送草稿', s.reports.length, '份', '按月归集与校验', 'reports', 'reports', 'drafts');
  }
  return items;
}

function metric(item) {
  const value = group(
    'div',
    'op-metric-value',
    el('strong', '', number.format(item.value)),
    el('span', '', item.unit)
  );
  const label = group('div', 'op-metric-label', icon(item.ic, 17), el('span', '', item.label));
  const btn = action('', item.open, 'op-metric');
  btn.append(label, value, el('span', 'op-metric-note', item.note));
  return btn;
}

function svg(tag, attrs, content) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (content != null) node.textContent = content;
  return node;
}

function daySeries(ctx, period, mode) {
  const s = ctx.state;
  return Array.from({ length: period }, (_, i) => {
    const date = dateBefore(s.today, period - i - 1);
    if (mode === 'care') {
      const tasks = s.tasks.filter((t) => t.date === date && t.status !== '已取消');
      return { date, a: tasks.length, b: tasks.filter((t) => t.status === '已完成').length };
    }
    if (mode === 'billing') {
      return {
        date,
        a: s.depositEntries.filter((p) => p.date === date).reduce((n, p) => n + p.amount, 0),
        b: s.payments
          .filter((p) => p.date === date && ['线下登记', '微信支付', '支付宝'].includes(p.method))
          .reduce((n, p) => n + p.amount, 0),
      };
    }
    const moves = s.transactions.filter((t) => t.date === date);
    return {
      date,
      a: moves.filter((t) => t.type === '入库').length,
      b: moves.filter((t) => t.type === '出库').length,
    };
  });
}

// Explicit viewBox dimensions preserve text size when the same plot is opened on a narrow display.
function chart(points, labels, unit, width) {
  const height = 164,
    left = 36,
    right = 24,
    top = 14,
    bottom = 130;
  const peak = Math.max(1, ...points.flatMap((p) => [p.a, p.b]));
  const power = 10 ** Math.floor(Math.log10(peak / 3));
  const step = Math.max(unit === '元' ? 0.01 : 1, Math.ceil(peak / (3 * power)) * power);
  const ceiling = step * 3;
  const x = (i) => left + (i * (width - left - right)) / (points.length - 1);
  const y = (n) => bottom - ((bottom - top) * n) / ceiling;
  const root = svg('svg', {
    viewBox: `0 0 ${width} ${height}`,
    role: 'img',
    'aria-labelledby': 'op-plot-title op-plot-desc',
    class: 'op-trend-plot',
  });
  root.append(
    svg('title', { id: 'op-plot-title' }, labels.join('与') + '每日趋势'),
    svg(
      'desc',
      { id: 'op-plot-desc' },
      points
        .map((p) => p.date + '，' + labels[0] + p.a + unit + '，' + labels[1] + p.b + unit)
        .join('。')
    )
  );
  const gradient = svg('linearGradient', {
    id: 'op-trend-fill',
    x1: '0%',
    y1: '0%',
    x2: '0%',
    y2: '100%',
  });
  gradient.append(
    svg('stop', { offset: '0%', 'stop-color': '#4597ff', 'stop-opacity': '.33' }),
    svg('stop', { offset: '100%', 'stop-color': '#4597ff', 'stop-opacity': '.01' })
  );
  const defs = svg('defs', {});
  defs.append(gradient);
  root.append(defs);
  for (let n = 0; n <= 3; n++) {
    const v = step * n;
    root.append(
      svg('line', { x1: left, x2: width - right, y1: y(v), y2: y(v), class: 'op-grid-line' })
    );
    root.append(
      svg(
        'text',
        { x: left - 9, y: y(v) + 4, 'text-anchor': 'end', class: 'op-axis' },
        number.format(v)
      )
    );
  }
  const line = (key) => points.map((p, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(p[key])).join(' ');
  root.append(
    svg('path', {
      d: line('b') + ` L ${x(points.length - 1)} ${bottom} L ${left} ${bottom} Z`,
      fill: 'url(#op-trend-fill)',
    })
  );
  root.append(
    svg('path', { d: line('a'), class: 'op-series-plan' }),
    svg('path', { d: line('b'), class: 'op-series-done' })
  );
  points.forEach((p, i) => {
    const dot = svg('circle', { cx: x(i), cy: y(p.b), r: 3.5, class: 'op-trend-dot' });
    dot.append(
      svg('title', {}, p.date + ' · ' + labels[0] + ' ' + p.a + ' / ' + labels[1] + ' ' + p.b)
    );
    root.append(dot);
    root.append(
      svg(
        'text',
        { x: x(i), y: 151, 'text-anchor': 'middle', class: 'op-axis' },
        p.date.slice(5).replace('-', '/')
      )
    );
  });
  return root;
}

function trend(ctx, mode) {
  const specs = {
    care: ['照护执行趋势', '计划工单', '已完成', '项'],
    billing: ['入款趋势', '预交到账', '账单实收', '元'],
    inventory: ['物资流转趋势', '入库单据', '出库单据', '笔'],
  };
  const [title, first, second, unit] = specs[mode];
  const picker = el('select', 'op-range');
  picker.setAttribute('aria-label', '趋势日期范围');
  picker.add(new Option('近 7 天', '7'));
  picker.add(new Option('近 3 天', '3'));
  const legend = (label, cls) => group('span', 'op-legend', el('i', cls), el('span', '', label));
  const legends = group(
    'div',
    'op-chart-legend',
    legend(first, 'op-key-plan'),
    legend(second, 'op-key-done'),
    el('span', 'op-chart-unit', '单位：' + unit)
  );
  const holder = el('div', 'op-chart-holder');
  const render = () =>
    holder.replaceChildren(
      chart(
        daySeries(ctx, Number(picker.value), mode),
        [first, second],
        unit,
        Math.max(280, Math.min(1000, holder.clientWidth || 450))
      )
    );
  picker.addEventListener('change', render);
  render();
  const panel = group(
    'section',
    'op-trend',
    group('div', 'op-panel-heading', el('h2', '', title), picker),
    legends,
    holder
  );
  // Recompute intrinsic chart coordinates when the card changes width.
  const observe = new ResizeObserver((entries) => {
    if (!holder.isConnected) {
      observe.disconnect();
      return;
    }
    const width = Math.round(entries[0].contentRect.width);
    if (width > 0 && Math.abs(Number(holder.dataset.chartWidth || 0) - width) > 1) {
      holder.dataset.chartWidth = String(width);
      render();
    }
  });
  observe.observe(holder);
  return panel;
}

function board(ctx, tasks) {
  const metrics = getMetrics(ctx, tasks);
  if (!metrics.length) return null;
  const mode =
    ctx.available('care') && ctx.permitted('care')
      ? 'care'
      : ctx.available('billing') && ctx.permitted('finance')
        ? 'billing'
        : ctx.available('inventory') && ctx.permitted('inventory')
          ? 'inventory'
          : '';
  const summary = group(
    'section',
    'op-summary',
    group('div', 'op-board-title', icon('pulse', 20), el('h2', '', '院区运行指标')),
    group('div', 'op-metrics', ...metrics.map(metric))
  );
  return group(
    'div',
    'op-board' + (mode ? '' : ' op-board-simple'),
    summary,
    mode ? trend(ctx, mode) : null
  );
}

function heading(title, actionNode) {
  return group('header', 'op-card-head', el('h2', '', title), actionNode);
}

function beds(ctx) {
  const all = ctx.state.beds,
    used = all.filter((b) => b.residentId).length;
  const percent = all.length ? (used / all.length) * 100 : 0;
  const ring = el('div', 'op-bed-ring');
  ring.style.setProperty('--occupied', String(percent) + '%');
  ring.setAttribute('aria-label', '床位使用率 ' + number.format(percent) + '%');
  ring.append(
    group(
      'div',
      'op-ring-inner',
      el('strong', '', number.format(percent) + '%'),
      el('span', '', '使用率')
    )
  );
  const wards = el('div', 'op-wards');
  for (const name of new Set(all.map((b) => b.ward))) {
    const ward = all.filter((b) => b.ward === name),
      occupied = ward.filter((b) => b.residentId).length;
    const line = group(
      'div',
      'op-ward-line',
      el('strong', '', name),
      el('span', '', occupied + ' / ' + ward.length + ' 床')
    );
    const strip = el('div', 'op-ward-strip');
    ward.forEach((b) => {
      const slot = el('i', b.residentId ? 'op-occupied' : '');
      slot.title = b.label + ' · ' + b.status;
      strip.append(slot);
    });
    wards.append(group('div', 'op-ward', line, strip));
  }
  return group(
    'section',
    'op-white-card op-bed-card',
    heading(
      '床位使用',
      action('床位管理', () => ctx.go('beds'), 'op-text-action')
    ),
    all.length ? group('div', 'op-beds-body', ring, wards) : empty('尚无床位记录'),
    group(
      'div',
      'op-bed-legend',
      group('span', '', el('i', 'op-key-occupied'), el('span', '', '已入住 ' + used + ' 床')),
      group(
        'span',
        '',
        el('i', 'op-key-vacant'),
        el('span', '', '空闲 ' + (all.length - used) + ' 床')
      )
    )
  );
}

function workQueue(ctx) {
  const s = ctx.state,
    entries = [];
  const add = (route, perm, tab, title, count, ic, hint) => {
    if (ctx.permitted(perm) && ctx.available(route))
      entries.push({ title, count, ic, hint, go: () => ctx.go(route, tab) });
  };
  add(
    'inbox',
    'alerts',
    'alerts',
    '设备预警',
    s.gatewayAlerts.filter((a) => a.status === '待复核').length,
    'bell',
    '待现场核实'
  );
  if (ctx.permitted('care'))
    add('inbox', 'voice.confirm', 'voice', '语音变更', s.voiceQueue.length, 'check', '待授权确认');
  add(
    'medications',
    'clinical',
    undefined,
    '用药计划',
    s.medications.filter((m) => m.status === '待复核').length,
    'pill',
    '待医护复核'
  );
  add(
    'assessments',
    'care',
    'plans',
    '照护计划',
    s.plans.filter((p) => p.status === '待复核').length,
    'assessment',
    '待复核派发'
  );
  if (!entries.length)
    add(
      'billing',
      'finance',
      'bills',
      '收费账单',
      s.bills.filter((b) => b.balance > 0).length,
      'wallet',
      '待缴费'
    );
  if (!entries.length)
    add(
      'inventory',
      'inventory',
      'stock',
      '库存补充',
      s.inventory.filter((i) => i.quantity < i.minimum).length,
      'box',
      '低于下限'
    );
  if (!entries.length) return null;
  const list = el('div', 'op-queue');
  entries.forEach((e) => {
    const b = action('', e.go, 'op-queue-item');
    b.append(
      group('span', 'op-queue-icon' + (e.ic === 'bell' ? ' op-warning' : ''), icon(e.ic, 18)),
      group('span', 'op-queue-text', el('strong', '', e.title), el('small', '', e.hint)),
      el('b', e.count ? 'op-open-count' : 'op-zero-count', e.count)
    );
    list.append(b);
  });
  return group('section', 'op-white-card', heading('人工处理队列'), list);
}

function taskDetails(ctx, t) {
  const r = ctx.state.residents.find((r) => r.id === t.residentId);
  const fields = [
    ['服务长者', r?.name],
    ['工单编号', t.id],
    ['计划时间', t.date + ' ' + t.time],
    ['责任人', t.assignee],
    ['状态', t.status],
    ['执行记录', t.note],
  ];
  const dl = el('dl', 'op-detail-facts');
  fields.forEach(([label, value]) =>
    dl.append(group('div', '', el('dt', '', label), el('dd', '', value || '—')))
  );
  const box = group('div', 'op-task-detail', dl);
  if (t.status === '待执行' && ctx.permitted('care'))
    box.append(button('登记执行', () => completeTask(ctx, t), 'primary', 'check'));
  ctx.detail(t.title, box);
}

function tasksPanel(ctx, tasks) {
  const panel = group(
    'section',
    'op-white-card op-tasks',
    heading(
      '今日照护工单',
      action('全部工单', () => ctx.go('care', 'tasks'), 'op-text-action')
    )
  );
  if (!tasks.length) {
    panel.append(empty('今天暂无照护工单'));
    return panel;
  }
  const body = el('tbody');
  const rows = [...tasks].sort(
    (a, b) =>
      Number(a.status === '已完成') - Number(b.status === '已完成') || a.time.localeCompare(b.time)
  );
  rows.slice(0, 5).forEach((t) => {
    const p = ctx.state.residents.find((r) => r.id === t.residentId);
    body.append(
      group(
        'tr',
        '',
        group(
          'td',
          '',
          action(t.title, () => taskDetails(ctx, t), 'op-task-open')
        ),
        el('td', '', p?.name || '—'),
        el('td', 'op-time', t.time),
        el('td', 'op-assignee', t.assignee),
        group('td', '', badge(t.status, t.status === '已完成' ? 'blue' : 'amber'))
      )
    );
  });
  const head = group(
    'tr',
    '',
    ...['服务项目', '服务长者', '计划时间', '责任人', '状态'].map((label, i) =>
      el('th', i === 3 ? 'op-assignee' : '', label)
    )
  );
  panel.append(
    group('div', 'op-table-wrap', group('table', 'op-task-table', group('thead', '', head), body))
  );
  return panel;
}

function shortcuts(ctx) {
  const destinations = [
    ['residents', '长者档案', 'people'],
    ['assessments', '能力评估', 'assessment'],
    ['shifts', '人员排班', 'shifts'],
    ['reports', '统计报送', 'reports'],
    ['inventory', '物资仓储', 'box'],
    ['billing', '财务结算', 'wallet'],
    ['dossier', '个人与医疗档案', 'folder'],
    ['activity', '操作日志', 'list'],
    ['integrations', '设备与接口', 'layers'],
  ];
  const items = destinations.filter(([route]) => ctx.available(route)).slice(0, 4);
  if (!items.length) return null;
  const grid = el('div', 'op-shortcuts');
  items.forEach(([route, label, ic]) => {
    const b = action('', () => ctx.go(route), 'op-shortcut');
    b.append(icon(ic, 20), el('span', '', label));
    grid.append(b);
  });
  return group('section', 'op-white-card', heading('岗位入口'), grid);
}

export function dashboard(ctx) {
  const tasks = ctx.state.tasks.filter((t) => t.date === ctx.state.today && t.status !== '已取消');
  const main = group('div', 'op-page', header(ctx), board(ctx, tasks));
  const first = [ctx.available('beds') ? beds(ctx) : null, workQueue(ctx)].filter(Boolean);
  if (first.length) main.append(group('div', 'op-pair', ...first));
  const last = [
    ctx.available('care') && ctx.permitted('care') ? tasksPanel(ctx, tasks) : null,
    shortcuts(ctx),
  ].filter(Boolean);
  if (last.length) main.append(group('div', 'op-pair op-lower', ...last));
  if (main.children.length === 1) main.append(empty('当前岗位尚未分配业务模块'));
  return main;
}
