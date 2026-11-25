import { businessDashboard } from './features/business-dashboard.js';
import { billDetail } from './features/billing.js';
import { receiptFacts, receiptRows } from './features/receipt-ledger.js';
import { financeContext } from './features/finance-dialogs.js';
import { taskDetail, medicationWork } from './features/care.js';
import { inspectAlert, confirmProposal } from './features/gateways.js';
import { inquiryForm } from './features/residency.js';
import { residentAnchor, residentLabel, staffLabel } from './features/people-labels.js';
import { badge, btn, link, money, node, table } from './features/shared.js';

const granted = (ctx, route, permission) =>
  ctx.available(route) && (!permission || ctx.permitted(permission));
const dateIn = (day, range) =>
  day && (!range.start || day >= range.start) && (!range.end || day <= range.end);
const asYuan = (value) => (value == null ? '待核对' : money(value / 100));
const paymentChannel = (receipt) =>
  [receipt.method, receipt.channel !== receipt.method && receipt.channel].filter(Boolean).join(' · ') ||
  '未登记';

// A dormant tab can outlive a payment, a bed transfer, or an authorization change.
function currentAction(ctx, label, route, permission, resolve, open) {
  const button = link(ctx, label, async () => {
    if (button.disabled) return;
    button.disabled = true;
    const from = location.hash;
    const ledger = ctx.workspaceState?.operationsLedger?.view;
    try {
      if (ctx.checkNavigation && !(await ctx.checkNavigation())) return;
      const live = ctx.current?.() || ctx;
      if (
        location.hash !== from ||
        live.state.user.id !== ctx.state.user.id ||
        ctx.workspaceState?.operationsLedger?.view !== ledger
      ) return;
      if (!granted(live, route, permission)) return live.toast('当前岗位无权查看此项业务');
      const row = resolve(live.state);
      if (!row) return live.toast('记录已变化，请刷新台账后查看');
      return await open(live, row, button);
    } catch (error) {
      ctx.toast(error.message || '读取记录失败，请重试');
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function receipts(ctx, range) {
  return table(ctx, {
    title: '实收到款台账',
    rows: receiptRows(ctx.state).filter((r) => dateIn(r.date, range)),
    action: btn(ctx, '打开收费记录', () => ctx.go('billing', 'receipts')),
    search: {
      placeholder: '搜索长辈、凭证号、商户单号',
      value: (r) => [residentLabel(ctx, r.residentId), r.id, r.merchantOrder, r.transactionId].join(' '),
    },
    filter: { label: '收款方式', all: '全部方式', value: paymentChannel },
    cols: [
      { label: '到账日期', view: (r) => r.date },
      { label: '长辈', view: (r) => residentAnchor(ctx, r.residentId) },
      { label: '收款凭证号', view: (r) => r.id },
      { label: '方式', view: paymentChannel },
      { label: '实收金额', view: (r) => asYuan(r.gross) },
      { label: '机构手续费', view: (r) => asYuan(r.fee) },
      { label: '净入账', view: (r) => asYuan(r.net) },
      {
        label: '操作',
        view: (r) =>
          currentAction(
            ctx,
            '查看凭证',
            'billing',
            'finance',
            (s) => receiptRows(s).find((x) => x.id === r.id),
            (live, v) => financeContext(live).detail('实收凭证', receiptFacts(v)),
          ),
      },
    ],
  });
}
function unpaid(ctx) {
  return table(ctx, {
    title: '当前待收账单',
    rows: (ctx.state.bills || []).filter((b) => b.balance > 0),
    action: btn(ctx, '打开待收费', () => ctx.go('billing', 'unpaid')),
    search: {
      placeholder: '搜索长辈、账期、账单号',
      value: (b) => [residentLabel(ctx, b.residentId), b.month, b.id].join(' '),
    },
    filter: { value: (b) => b.status },
    cols: [
      { label: '账期', view: (b) => b.billingDate || b.month },
      { label: '长辈', view: (b) => residentAnchor(ctx, b.residentId) },
      { label: '账单号', view: (b) => b.id },
      { label: '应收', view: (b) => money(b.amount) },
      { label: '已核销', view: (b) => money(b.paid) },
      { label: '待收余额', view: (b) => money(b.balance) },
      { label: '状态', view: (b) => badge(ctx, b.status) },
      {
        label: '操作',
        view: (b) =>
          currentAction(
            ctx,
            '查看明细',
            'billing',
            'finance',
            (s) => s.bills?.find((x) => x.id === b.id && x.balance > 0),
            billDetail,
          ),
      },
    ],
  });
}
function careTasks(ctx, range) {
  return table(ctx, {
    title: '照护工单台账',
    rows: (ctx.state.tasks || []).filter((t) => dateIn(t.date, range)),
    action: btn(ctx, '打开照护工单', () => ctx.go('care', 'tasks')),
    search: {
      placeholder: '搜索护理项目、长辈、执行人',
      value: (t) => [t.title, residentLabel(ctx, t.residentId), t.assignee, t.operator].join(' '),
    },
    filter: { value: (t) => t.status },
    cols: [
      { label: '计划日期', view: (t) => t.date },
      { label: '时点', view: (t) => t.time || '当日安排' },
      { label: '护理项目', view: (t) => t.title },
      { label: '长辈', view: (t) => residentAnchor(ctx, t.residentId) },
      { label: '责任人', view: (t) => staffLabel(ctx, t.assignee, t.assigneeId) },
      { label: '状态', view: (t) => badge(ctx, t.status) },
      { label: '完成时间', view: (t) => t.completedAt || '—' },
      {
        label: '操作',
        view: (t) =>
          currentAction(
            ctx,
            '查看工单',
            'care',
            'care',
            (s) => s.tasks?.find((x) => x.id === t.id),
            taskDetail,
          ),
      },
    ],
  });
}
function beds(ctx) {
  const loc = (b) => ctx.state.bedDirectory?.[b.id] || {};
  const occupants = new Map((ctx.state.residents || []).filter((p) => p.bedId).map((p) => [p.bedId, p]));
  const status = (b) => (occupants.get(b.id)?.stayType === 'trial' ? '试住中' : b.status);
  return table(ctx, {
    title: '当前床位台账',
    rows: ctx.state.beds || [],
    action: btn(ctx, '打开床位全景', () => ctx.go('beds', 'all')),
    search: {
      placeholder: '搜索楼栋、楼层、床号或长辈',
      value: (b) =>
        [
          b.label,
          b.ward,
          loc(b).buildingName,
          loc(b).floorLabel,
          loc(b).roomNumber,
          occupants.get(b.id)?.name,
        ].join(' '),
    },
    filter: { value: status },
    cols: [
      { label: '楼栋', view: (b) => loc(b).buildingName || '—' },
      { label: '楼层', view: (b) => loc(b).floorLabel || '—' },
      { label: '床号', view: (b) => b.label },
      { label: '状态', view: (b) => badge(ctx, status(b)) },
      { label: '长辈', view: (b) => (occupants.has(b.id) ? residentAnchor(ctx, occupants.get(b.id)) : '—') },
      {
        label: '操作',
        view: (b) =>
          loc(b).roomId
            ? currentAction(
                ctx,
                '查看房间',
                'beds',
                null,
                (s) => s.beds?.some((x) => x.id === b.id) && s.bedDirectory?.[b.id],
                (live, v) => live.go('beds', 'all', null, { room: v.roomId }),
              )
            : null,
      },
    ],
  });
}

const queueSources = [
  {
    label: '设备预警',
    key: 'gatewayAlerts',
    route: 'inbox',
    tab: 'alerts',
    grant: 'alerts',
    pending: (r) => r.status === '待复核',
    target: (r) => r.room,
    info: (r) => ({ possible_fall: '疑似跌倒', prolonged_bedrest: '持续卧床提示' })[r.signal] || '设备告警',
    open: inspectAlert,
  },
  {
    label: '语音申请',
    key: 'voiceQueue',
    route: 'inbox',
    tab: 'voice',
    grant: 'voice.confirm',
    extra: 'care',
    pending: () => true,
    target: (r) => r.room,
    info: (r) => r.title,
    open: confirmProposal,
  },
  {
    label: '用药复核',
    key: 'medications',
    route: 'medications',
    grant: 'clinical',
    pending: (r) => r.status === '待复核',
    info: (r) => r.name,
    open: (live, r) => medicationWork(live).detail(r),
  },
  {
    label: '照护计划',
    key: 'plans',
    route: 'assessments',
    tab: 'plans',
    grant: 'care',
    pending: (r) => r.status === '待复核',
    info: (r) => r.title,
  },
  {
    label: '库存补充',
    key: 'inventory',
    route: 'inventory',
    tab: 'stock',
    grant: 'inventory',
    pending: (r) => r.quantity < r.minimum,
    info: (r) => r.name,
    target: (r) => r.location,
  },
];
function queues(ctx, sources) {
  const rows = sources.flatMap((source) =>
    (ctx.state[source.key] || []).filter(source.pending).map((r) => ({ source, r })),
  );
  const target = ({ r, source }) =>
    r.residentId ? residentLabel(ctx, r.residentId) : source.target?.(r) || '—';
  return table(ctx, {
    title: '待跟进事项',
    rows,
    search: {
      placeholder: '搜索对象、事项或记录编号',
      value: (item) => [target(item), item.source.label, item.source.info(item.r), item.r.id].join(' '),
    },
    filter: { label: '业务', all: '全部业务', value: ({ source }) => source.label },
    cols: [
      { label: '业务', view: ({ source }) => source.label },
      {
        label: '对象',
        view: (item) => (item.r.residentId ? residentAnchor(ctx, item.r.residentId) : target(item)),
      },
      { label: '事项', view: ({ source, r }) => source.info(r) || '待核对' },
      { label: '记录编号', view: ({ r }) => r.id },
      { label: '状态', view: ({ r }) => r.status || '待跟进' },
      {
        label: '操作',
        view: ({ source, r }) =>
          currentAction(
            ctx,
            source.open ? '查看并复核' : '进入办理',
            source.route,
            source.grant,
            (s) => s[source.key]?.find((x) => x.id === r.id && source.pending(x)),
            (live, v, trigger) => {
              if (source.extra && !live.permitted(source.extra)) return live.toast('当前岗位无权办理');
              return source.open ? source.open(live, v, trigger) : live.go(source.route, source.tab);
            },
          ),
      },
    ],
  });
}

export function operationalOverview(ctx) {
  const views = [];
  if (granted(ctx, 'billing', 'finance'))
    views.push(['receipts', '实收到款', receipts, true], ['unpaid', '待收账单', unpaid, false]);
  if (granted(ctx, 'care', 'care')) views.push(['tasks', '照护工单', careTasks, true]);
  if (ctx.available('beds')) views.push(['beds', '床位', beds, false]);
  const sources = queueSources.filter(
    (s) => granted(ctx, s.route, s.grant) && (!s.extra || ctx.permitted(s.extra)),
  );
  if (sources.length) views.push(['queue', '待跟进事项', (c) => queues(c, sources), false]);
  const header = node('header', 'fx-module-head', node('h1', '', '日常运营明细'));
  const shortcuts = node('div', 'fx-actions');
  if (ctx.available('residents') && ctx.state.allowedActions?.includes('care.register'))
    shortcuts.append(btn(ctx, '新建长辈档案', () => inquiryForm(ctx)));
  for (const [route, title] of [
    ['inbox', '预警与确认'],
    ['shifts', '人员排班'],
    ['reports', '统计报送'],
  ])
    if (ctx.available(route)) shortcuts.append(btn(ctx, title, () => ctx.go(route)));
  if (shortcuts.childElementCount) header.append(shortcuts);
  const page = node('section', 'fx-page', header);
  if (!views.length) {
    page.append(node('p', 'fx-empty', '当前岗位尚未获准查看运营台账'));
    return page;
  }
  const workspace = ctx.workspaceState || {},
    prefs = (workspace.operationsLedger ||= {
      view: views[0][0],
      start: ctx.state.today,
      end: ctx.state.today,
    });
  const picker = node('select', 'fx-input');
  picker.setAttribute('aria-label', '运营台账');
  for (const [key, title] of views) picker.add(new Option(title, key));
  picker.value = views.some((v) => v[0] === prefs.view) ? prefs.view : views[0][0];
  const controls = node('form', 'fx-table-tools'),
    body = node('div', 'fx-profile');
  const date = (value, label) => {
    const input = node('input', 'fx-input');
    input.type = 'date';
    input.max = ctx.state.today;
    input.value = value;
    input.setAttribute('aria-label', label);
    return input;
  };
  const start = date(prefs.start, '起始日期'),
    end = date(prefs.end, '截止日期');
  const startField = node('label', 'desk-filter', ['起始日期', start]),
    endField = node('label', 'desk-filter', ['截止日期', end]);
  const all = btn(ctx, '全部日期', () => {
    start.value = end.value = '';
    draw();
  });
  const day = btn(ctx, '今日', () => {
    start.value = end.value = ctx.state.today;
    draw();
  });
  controls.append(node('label', 'desk-filter', ['运营台账', picker]), startField, endField, day, all);
  function draw() {
    const [key, , render, dated] = views.find((v) => v[0] === picker.value);
    Object.assign(prefs, { view: key, start: start.value, end: end.value });
    for (const el of [startField, endField, all, day]) el.hidden = !dated;
    if (
      dated &&
      ((prefs.start && prefs.end && prefs.start > prefs.end) ||
        prefs.start > ctx.state.today ||
        prefs.end > ctx.state.today)
    ) {
      body.replaceChildren(node('p', 'form-error', '请选择有效日期，截止日期不能早于起始日期或晚于今天'));
      return;
    }
    body.replaceChildren(render(ctx, prefs));
  }
  controls.onsubmit = (e) => {
    e.preventDefault();
    draw();
  };
  controls.onchange = draw;
  page.append(controls, body);
  draw();
  return page;
}

export function dashboard(ctx) {
  return businessDashboard(ctx, () =>
    ctx.openWorkspaceTab
      ? ctx.openWorkspaceTab('overview', {
          id: 'operations-detail',
          view: 'cockpit',
          title: '日常运营明细',
          render: operationalOverview,
        })
      : ctx.detail('日常运营明细', operationalOverview(ctx)),
  );
}
