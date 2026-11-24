import { badge, canAct, field, memo, node, select, table, today } from './shared.js';
import { taskForm } from './care.js';

// These destinations are also indexed by the keyboard quick finder.
export const quickDestinations = [
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
  { label: '护理用具库存', words: '护理用品 物资情况 仓库盘点', route: 'inventory', tab: 'stock' },
  { label: '护理用具工单', words: '物资工单 物资任务 补货', route: 'inventory', tab: 'orders' },
];

export function openAssistantAction(ctx, action) {
  if (!action || !ctx.available(action.route)) return ctx.toast('当前账号无法打开这个页面');
  if (action.kind === 'navigate') {
    if (action.route === 'intake') return ctx.go('residents', 'all');
    if (action.route === 'rooms') return ctx.go('beds', 'plan');
    return ctx.go(action.route);
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
          label: user.label + ' · ' + user.role,
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
        fields: [['执行人', row.assignee]],
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
      { label: '执行人', view: (row) => row.assignee },
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
      { label: '发布人', view: (row) => row.publisher },
      { label: '发布时间', view: (row) => row.createdAt.slice(0, 16).replace('T', ' ') },
    ],
  });
}
