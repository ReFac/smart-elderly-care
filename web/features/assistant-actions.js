import { openScheduledMeal } from './scheduled-meals.js';
import { openMedicationRound } from './med-rounds.js';
import { staffLabel } from './people-labels.js';
import { badge, canAct, field, memo, node, select, table, today } from './shared.js';
import { taskForm } from './care.js';
import { routes } from '../lib/navigation.js';

// These destinations are also indexed by the keyboard quick finder.
export const quickDestinations = [
  { label: '定时工单', words: '自动工单 伙食排期 伙食工单 定时巡查 菜单 照护排程', route: 'care', tab: 'scheduledWork', grant: 'care.completeTask' },
  { label: 'DeepSeek 用量', words: '模型用量 API 用量 Token 用量 OCR ASR 缓存命中率 员工用量', route: 'settings', tab: 'deepseekUsage' },
  { label: '登记集体活动', words: '集体用餐 早餐 午餐 晚餐 登记餐单', route: 'care', tab: 'groupLife', grant: 'care.proposeGroupActivity' },
  { label: '核对活动参加名单', words: '集体活动待确认 用餐签认', route: 'care', tab: 'groupLife', grant: 'care.confirmGroupActivity' },
  { label: '意向客户', words: '来电登记 电话回访 客户反馈', route: 'leads' },
  { label: '接待时间表', words: '意向客户 来访排班 电话预约 参观时间', route: 'leads', tab: 'schedule' },
  {
    label: '办理老人入住',
    words: '创建老人入住 办理长者入住 老人入院 分配床位',
    route: 'residents',
    tab: 'all',
    grant: 'care.admit',
  },
  {
    label: '按平面图选床',
    words: '打开房间工作台 查找病房 楼层平面图',
    route: 'beds',
    tab: 'plan',
  },
  { label: '试住管理', words: '办理试住 试住转正式 试住回访', route: 'residents', tab: 'trials' },
  { label: '待出月账单', words: '月付账单 核算月费 账单日', route: 'billing', tab: 'due' },
  { label: '护理用具库存', words: '护理用品 物资情况 仓库盘点', route: 'inventory', tab: 'stock' },
  { label: '护理用具工单', words: '物资工单 物资任务 补货', route: 'inventory', tab: 'orders' },
];

function pageDestination(ctx, entry) {
  const route = entry?.route;
  if (!routes.has(route) || !ctx.available(route)) return null;
  // The admission shortcut also requires the legacy intake route grant.
  if (route === 'intake' && ctx.state.user.routes && !ctx.state.user.routes.includes('intake'))
    return null;
  const tab = entry.tab;
  if (tab != null && (typeof tab !== 'string' || !/^[a-z][a-zA-Z0-9]{0,39}$/.test(tab)))
    return null;
  const dest = route === 'intake' ? 'residents' : route === 'rooms' ? 'beds' : route;
  return {
    route,
    destination: dest,
    tab: route === 'intake' ? 'all' : route === 'rooms' ? 'plan' : tab,
    title: typeof entry.title === 'string' && entry.title.trim()
      ? entry.title.trim()
      : routes.get(dest).label,
    icon: routes.get(dest).icon,
  };
}

export function assistantPageLinks(ctx, message) {
  if (message.role !== 'assistant' || message.webSearched) return [];
  const links = [];
  for (const entry of Array.isArray(message.pageLinks) ? message.pageLinks : []) {
    const link = pageDestination(ctx, entry);
    if (link && !links.some((item) => item.destination === link.destination && item.tab === link.tab))
      links.push(link);
  }
  // Earlier conversations only stored a single navigate action.
  if (message.action?.kind === 'navigate') {
    const link = pageDestination(ctx, message.action);
    if (link && !links.some((item) => item.destination === link.destination))
      links.push(link);
  }
  return links;
}

export function assistantCommand(ctx, message) {
  const action = message?.action;
  if (message?.role !== 'assistant' || message.webSearched || !action) return null;
  if (action.kind !== 'navigate') return ['notice', 'workOrder', 'medicationRound', 'scheduledMeal'].includes(action.kind) ? action : null;
  const target = pageDestination(ctx, action);
  if (!target) return null;
  const links = assistantPageLinks(ctx, message).filter((link) => link.destination === target.destination);
  const link = links.find((item) => item.tab === target.tab) || links[0] || target;
  return { ...link, kind: 'navigate' };
}

export function openAssistantAction(ctx, action) {
  if (!action || !routes.has(action.route) || !ctx.available(action.route))
    return ctx.toast('当前账号无法打开这个页面');
  if (action.kind === 'scheduledMeal') {
    return openScheduledMeal(ctx, { text: action.text, region: action.region });
  }
  if (action.kind === 'medicationRound') {
    return openMedicationRound(ctx, {text: action.text, ...(action.region ? {region: action.region} : {})});
  }
  if (action.kind === 'navigate') {
    const link = pageDestination(ctx, action);
    if (!link) return ctx.toast('当前账号无法打开这个页面');
    return ctx.go(link.destination, link.tab, () =>
      document.getElementById('content')?.focus({ preventScroll: true }),
    );
  }
  if (!action.id) return ctx.toast('无法识别这项建议，请重新提问');
  if (action.kind === 'workOrder' && action.route === 'care') {
    if (!canAct(ctx, 'care.addTask')) return ctx.toast('当前账号没有照护工单权限');
    return ctx.go('care', 'tasks', () => taskForm(ctx, action));
  }
  const notice = action.kind === 'notice';
  if (!notice && (action.kind !== 'workOrder' || action.route !== 'inventory')) return;
  const command = notice ? 'ops.publishNotice' : 'ops.supplyOrder';
  if (!canAct(ctx, command)) return ctx.toast('当前账号没有发布权限');
  const dest = notice ? 'inbox' : 'inventory';
  const tab = notice ? 'notices' : 'orders';
  const entries = notice ? ctx.state.staffNotices : ctx.state.supplyOrders;
  if (
    (entries || []).some(
      (row) => row.assistantActionId === action.id && row.publisherId === ctx.state.user.id,
    )
  )
    return ctx.toast('这项建议已经发布，可直接查看办理记录');
  const fields = [
    field('title', notice ? '通知标题' : '工单标题', { value: action.title, maxLength: 100 }),
    memo('description', notice ? '通知正文' : '执行内容', true, {
      value: action.description,
      maxLength: 2000,
    }),
  ];
  if (!notice) {
    fields.push(
      select(
        'itemId',
        '涉及用具',
        [
          { value: '', label: '整体盘点或多项用具' },
          ...(ctx.state.inventory || []).map((item) => ({ value: item.id, label: item.name })),
        ],
        { required: false },
      ),
      select('assigneeId', '执行人', [
        { value: '', label: '选择负责员工' },
        ...(ctx.state.supplyAssignees || []).map((user) => ({
          value: user.id,
          label: staffLabel(ctx, {displayName:user.label, role:user.role, id:user.id}),
        })),
      ]),
      field('dueDate', '执行日期', { type: 'date', min: today(ctx), value: today(ctx) }),
    );
  }
  const review = () =>
    ctx.dialog({
      title: notice ? '审核全员通知' : '审核护理用具工单',
      description: notice
        ? '发布后，所有在岗员工都可以从右上角铃铛查看。'
        : '请核对用具和执行人。发布后，执行人的待办中会收到这项工单。',
      fields,
      submitLabel: '确认发布',
      onSubmit: (values) =>
        ctx.command(command, { ...values, assistantActionId: action.id }, { confirmed: true }),
    });
  return ctx.go(dest, tab, review);
}

function finishButton(ctx, row) {
  const b = node('button', 'btn btn-secondary', '标记完成');
  b.type = 'button';
  b.addEventListener('click', () =>
    ctx.command(
      'ops.finishSupplyOrder',
      { orderId: row.id },
      {
        title: '完成物资工单',
        target: row.title,
        fields: [['执行人', staffLabel(ctx, row.assignee, row.assigneeId)]],
      },
    ),
  );
  return b;
}

export function supplyOrders(ctx, mine = false) {
  const rows = (ctx.state.supplyOrders || []).filter(
    (row) => !mine || (row.assigneeId === ctx.state.user.id && row.status === '待执行'),
  );
  return table(ctx, {
    title: mine ? '我的物资待办' : '护理用具工单',
    rows,
    empty: '当前没有物资工单',
    cols: [
      {
        label: '工单',
        view: (row) =>
          node('div', 'fx-profile', [
            node('strong', '', row.title),
            node('small', '', row.description),
          ]),
      },
      { label: '执行人', view: (row) => staffLabel(ctx, row.assignee, row.assigneeId) },
      { label: '执行日期', view: (row) => row.dueDate },
      {
        label: '进度',
        view: (row) => (row.status === '待执行' ? finishButton(ctx, row) : badge(ctx, row.status)),
      },
    ],
  });
}

function noticeKey(ctx) {
  return 'nh-staff-notice:' + ctx.state.user.id;
}

export function hasNewNotice(ctx) {
  const latest = ctx.state.staffNotices?.[0];
  if (!latest) return false;
  try {
    return localStorage.getItem(noticeKey(ctx)) !== latest.id;
  } catch {
    return true;
  }
}

export function staffNotices(ctx) {
  const latest = ctx.state.staffNotices?.[0];
  if (latest) {
    try {
      localStorage.setItem(noticeKey(ctx), latest.id);
    } catch {}
  }
  return table(ctx, {
    title: '全员通知',
    rows: ctx.state.staffNotices || [],
    empty: '暂无已发布的全员通知',
    cols: [
      {
        label: '通知',
        view: (row) =>
          node('div', 'fx-profile', [
            node('strong', '', row.title),
            node('span', '', row.description),
          ]),
      },
      { label: '发布人', view: (row) => staffLabel(ctx, row.publisher, row.publisherId) },
      { label: '发布时间', view: (row) => row.createdAt.slice(0, 16).replace('T', ' ') },
    ],
  });
}
