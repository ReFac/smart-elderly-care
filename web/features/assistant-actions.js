import { openMedicationRound } from './med-rounds.js';
import { manualFormAvailable, openManualForm } from './assistant-manual-forms.js';
import { staffLabel } from './people-labels.js';
import { badge, canAct, field, memo, node, select, table, today } from './shared.js';
import { taskForm } from './care.js';
import { routes } from '../lib/navigation.js';

// These destinations are also indexed by the keyboard quick finder.
export const quickDestinations = [
  { label: '区域设置', words: '护理区域 子区域 护工职责 楼栋分区', route: 'beds', tab: 'zones' },
  { label: '房型设置', words: '单人间 双人间 三人间 编辑房间', route: 'beds', tab: 'all', grant: 'facility.updateRoom' },
  { label: '平台更新', words: '版本检查 自动更新 升级前备份 软件更新', route: 'settings', tab: 'platformUpdates' },
  { label: '健康工作台', words: '健康管理 智慧照护 异常上报', route: 'care', tab: 'healthDesk' },
  { label: '等级判定', words: '评估结果 护理等级', route: 'assessments', tab: 'grading' },
  { label: '用药安全筛查', words: '用药冲突 过敏核对 重复用药', route: 'medications', tab: 'safety' },
  { label: '定时工单', words: '自动工单 伙食排期 伙食工单 定时巡查 菜单 照护排程', route: 'care', tab: 'scheduledWork', grant: 'care.completeTask' },
  { label: 'AI 用量', words: 'DeepSeek 用量 模型用量 API 用量 Token 用量 OCR ASR 缓存命中率 员工用量', route: 'settings', tab: 'deepseekUsage' },
  { label: '登记集体活动', words: '集体用餐 早餐 午餐 晚餐 登记餐单', route: 'care', tab: 'groupLife', grant: 'care.proposeGroupActivity' },
  { label: '核对活动参加名单', words: '集体活动待确认 用餐签认', route: 'care', tab: 'groupLife', grant: 'care.confirmGroupActivity' },
  { label: '意向客户', words: '来电登记 电话回访 客户反馈', route: 'leads' },
  { label: '接待时间表', words: '意向客户 来访排班 电话预约 参观时间', route: 'leads', tab: 'schedule' },
  {
    label: '办理老人入住',
    words: '创建老人入住 办理长辈入住 老人入院 分配床位',
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
  { label: '办理试住', words: '试住入住 开始试住', route: 'residents', tab: 'notAdmitted', grant: 'care.admit' },
  { label: '试住', words: '试住管理 试住转正式 试住记录', route: 'residents', tab: 'trials' },
  { label: '试住回访', words: '试住离院 回访报告', route: 'residents', tab: 'followups' },
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
  const params = {};
  if (dest === 'beds' && entry.params && typeof entry.params === 'object') {
    for (const key of ['campus', 'building', 'floor', 'room']) {
      if (/^[A-Za-z0-9_-]{1,100}$/.test(entry.params[key] || '')) params[key] = entry.params[key];
    }
    if (/^(?:[1-9]|1[0-2])$/.test(entry.params.capacity)) params.capacity = entry.params.capacity;
    if (/^(?:[1-9]|[12]\d|30)$/.test(entry.params.limit)) params.limit = entry.params.limit;
    if (['vacant', 'occupied'].includes(entry.params.status)) params.status = entry.params.status;
    if (['layout', 'room'].includes(entry.params.edit) && canAct(ctx, entry.params.edit === 'layout' ? 'facility.setLayout' : 'facility.updateRoom'))
      params.edit = entry.params.edit;
  }
  if (dest === 'faq' && typeof entry.params?.item === 'string' && /^[a-z][a-z0-9-]{1,60}$/.test(entry.params.item))
    params.item = entry.params.item;
  return {
    route,
    destination: dest,
    tab: route === 'intake' ? 'all' : route === 'rooms' ? 'plan' : tab,
    title: typeof entry.title === 'string' && entry.title.trim()
      ? entry.title.trim()
      : routes.get(dest).label,
    icon: routes.get(dest).icon,
    ...(Object.keys(params).length ? { params } : {}),
  };
}

export function assistantPageLinks(ctx, message) {
  if (message.role !== 'assistant' || message.webSearched) return [];
  const links = [];
  for (const entry of Array.isArray(message.pageLinks) ? message.pageLinks : []) {
    const link = pageDestination(ctx, entry);
    if (link && !links.some((item) => item.destination === link.destination && item.tab === link.tab &&
      JSON.stringify(item.params) === JSON.stringify(link.params)))
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
  if (action.kind === 'openForm') return manualFormAvailable(ctx, action) ? action : null;
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
  if (action.kind === 'openForm') return openManualForm(ctx, action);
  if (action.kind === 'scheduledMeal') {
    return ctx.go('care', 'scheduledWork');
  }
  if (action.kind === 'medicationRound') {
    return ctx.go('care', 'medRounds', () => openMedicationRound(ctx, { region: action.region }));
  }
  if (action.kind === 'navigate') {
    const link = pageDestination(ctx, action);
    if (!link) return ctx.toast('当前账号无法打开这个页面');
    const arrival = () => document.getElementById('content')?.focus({ preventScroll: true });
    return link.params ? ctx.go(link.destination, link.tab, arrival, link.params) :
      ctx.go(link.destination, link.tab, arrival);
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
    field('title', notice ? '通知标题' : '工单标题', { maxLength: 100 }),
    memo('description', notice ? '通知正文' : '执行内容', true, {
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
      submitLabel: '核对发布',
      onSubmit: (values) =>
        ctx.command(command, { ...values, assistantActionId: action.id }),
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
