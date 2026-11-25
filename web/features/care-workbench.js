import { residentAnchor, staffLabel } from './people-labels.js';
import { badge, canAct, hasGrant, node } from './shared.js';
import { dueMedicationCount } from './medication-rules.js';

function tile(ctx, label, icon, count, hint, open, urgent = false) {
  const title = node('span', 'cw-tile-label', [ctx.ui.icon(icon, 18), label]);
  const number = node('strong', 'cw-tile-number', count);
  const button = node('button', 'cw-tile' + (urgent ? ' cw-tile--urgent' : ''), [
    title,
    node('span', 'cw-tile-main', [number, ctx.ui.icon('chevron', 16)]),
    node('span', 'cw-tile-hint', hint),
  ]);
  button.type = 'button';
  button.addEventListener('click', open);
  return button;
}

export function assessmentStages(ctx, { total, classified, pendingPlans, dueReviews }) {
  const stages = [
    ['评估采集', 'assessment', total + ' 份', '线上采集与纸质量表', 'assess'],
    ['等级判定', 'shield', classified + ' 人', '查看评估等级与判定依据', 'grading'],
    ['照护方案', 'care', pendingPlans + ' 份待复核', '核对服务项目与责任人', 'plans'],
    ['复评提醒', 'calendar', dueReviews + ' 人到期', '按预约日期登记复评', 'review'],
  ];
  return node('section', 'cw-stages', [
    node('div', 'cw-grid', stages.map(([label, icon, count, detail, tab]) =>
      tile(ctx, label, icon, count, detail, () => ctx.go('assessments', tab),
        tab === 'review' && Boolean(dueReviews)))),
  ]);
}

function panel(ctx, title, glyph, body, action) {
  return node('section', 'cw-panel', [
    node('div', 'cw-panel-head', [node('h3', '', [ctx.ui.icon(glyph, 19), title]), action]),
    body,
  ]);
}

function action(ctx, label, open) {
  const button = node('button', 'cw-action', [label, ctx.ui.icon('chevron', 14)]);
  button.type = 'button';
  button.addEventListener('click', open);
  return button;
}

function queueList(rows, render, empty) {
  return rows.length
    ? node('ul', 'cw-list', rows.map((row) => node('li', '', render(row))))
    : node('p', 'cw-empty', empty);
}

class CareDesk extends HTMLElement {
  connectedCallback() {
    this.refreshDue();
    this.clock = setInterval(() => this.refreshDue(), 30_000);
  }
  disconnectedCallback() {
    clearInterval(this.clock);
  }
}
if (!customElements.get('care-health-desk')) customElements.define('care-health-desk', CareDesk);

export function healthDesk(ctx, { vitalForm, inspectVital, resolveVital }) {
  const state = ctx.state;
  const allVitals = state.vitals || [];
  const canVitals = canAct(ctx, 'care.vital');
  const canResolve = canAct(ctx, 'care.resolveVital');
  const canAlert = hasGrant(ctx, 'alerts') && ctx.available('inbox');
  const canOrders = canAct(ctx, 'care.giveMedication') && ctx.available('medications');
  const canHandover = canAct(ctx, 'care.handover');
  const canManageFamily = ctx.available('access');
  const canViewResidents = ctx.available('residents');
  const canShareConsent = canAct(ctx, 'family.consent');
  const todayVitals = allVitals.filter((row) => row.date === state.today);
  const pendingVitals = allVitals.filter((row) => row.status === '待复核')
    .sort((a,b) => b.date.localeCompare(a.date));
  const alerts = canAlert ? (state.gatewayAlerts || []).filter((row) => row.status === '待复核') : [];
  const priorityAlerts = alerts.filter((row) => row.priority === '优先现场核实');
  const orders = canOrders ? (state.medications || []) : [];
  const needsReview = orders.filter((row) => row.status === '待复核');
  const withWarnings = orders.filter((row) => ['待复核', '待执行'].includes(row.status) && row.warnings?.length);
  const handovers = (state.handovers || []).filter((row) => row.status === '待签收' && row.assigneeId === state.user.id);
  const desk = document.createElement('care-health-desk');
  desk.className = 'cw-desk';
  const metrics = node('div', 'cw-grid');
  if (canVitals) metrics.append(tile(ctx, '体征异常待复核', 'pulse', pendingVitals.length,
    '打开测量与处理记录', () => ctx.go('care', 'vitals'), Boolean(pendingVitals.length)));
  if (canAlert) metrics.append(tile(ctx, '设备预警待核实', 'bell', alerts.length,
    priorityAlerts.length ? priorityAlerts.length + ' 条需优先现场核实' : '打开设备预警台账',
    () => ctx.go('inbox', 'alerts'), Boolean(priorityAlerts.length)));
  if (canHandover) metrics.append(tile(ctx, '待我签收交班', 'shifts', handovers.length,
    '查看接班对象与交班事项', () => ctx.go('care', 'handover')));
  if (canOrders) {
    const reminder = tile(ctx, '已到时待给药', 'pill', dueMedicationCount(orders),
      '查看已复核的计划时刻', () => ctx.go('medications', 'reminders'));
    desk.refreshDue = () => {
      const count = dueMedicationCount(orders);
      reminder.querySelector('.cw-tile-number').textContent = count;
      reminder.classList.toggle('cw-tile--urgent', count > 0);
    };
    metrics.append(reminder);
  } else desk.refreshDue = () => {};
  desk.append(metrics);
  const panels = node('div', 'cw-panels');
  if (canVitals) {
    const body = node('div', 'cw-panel-body', [
      node('p', 'cw-summary', '今日已记录 ' + todayVitals.length + ' 条体征，共 ' +
        new Set(todayVitals.map((row) => row.residentId)).size + ' 位长辈'),
      queueList(pendingVitals.slice(0, 5), (row) => [
        node('div', 'cw-list-text', [
          residentAnchor(ctx, row.residentId),
          node('span', '', [row.metric, [row.value,row.unit].filter(Boolean).join(' '), row.date].filter(Boolean).join(' · ')),
        ]),
        action(ctx, canResolve ? '记录处置' : '查阅', () => canResolve ? resolveVital(row) : inspectVital(row)),
      ], '目前没有待复核的体征异常'),
      pendingVitals.length > 5 ? action(ctx, '查看全部体征记录', () => ctx.go('care','vitals')) : null,
    ]);
    panels.append(panel(ctx, '体征与异常处理', 'pulse', body, action(ctx, '录入体征', vitalForm)));
  }
  if (canOrders) {
    const body = node('div', 'cw-panel-body', [
      node('p', 'cw-summary', needsReview.length + ' 条医嘱待复核，' + withWarnings.length + ' 条未完成医嘱有筛查提醒'),
      queueList(withWarnings.slice(0, 4), (row) => [
        node('div', 'cw-list-text', [
          residentAnchor(ctx, row.residentId),
          node('span', '', row.name + ' · ' + row.warnings.join(' · ')),
        ]),
        badge(ctx, row.status, 'amber'),
      ], '目前没有带筛查提醒的未完成医嘱'),
      node('div', 'cw-links', [
        action(ctx, '查看筛查提醒', () => ctx.go('medications', 'safety')),
        action(ctx, '机构配伍规则', () => ctx.go('medications', 'rules')),
      ]),
    ]);
    panels.append(panel(ctx, '医嘱与用药安全', 'pill', body, action(ctx, '办理医嘱', () => ctx.go('medications', 'orders'))));
  }
  if (canHandover) {
    const body = node('div', 'cw-panel-body', [
      queueList(handovers.slice(0, 4), (row) => [
        node('div', 'cw-list-text', [
          row.residentId ? residentAnchor(ctx, row.residentId) : node('strong', '', '当班交接'),
          node('span', '', ['交班人 ' + staffLabel(ctx, row.senderName || row.operator, row.senderId), row.date].filter(Boolean).join(' · ')),
        ]),
        badge(ctx, '待签收', 'amber'),
      ], '没有分派给你的待签收交班'),
      node('div', 'cw-links', [
        action(ctx, '已完成服务凭证', () => ctx.go('care','completed')),
        ...(ctx.available('inbox') ? [action(ctx, '巡查提醒', () => ctx.go('inbox','rounds'))] : []),
      ]),
    ]);
    panels.append(panel(ctx, '班次交接与查阅', 'shifts', body, action(ctx, '进入交班台账', () => ctx.go('care','handover'))));
  }
  if (canManageFamily || canViewResidents) {
    const body = node('div', 'cw-panel-body', [
      node('dl', 'cw-share', [
        node('div', '', [node('dt', '', '照护服务'), node('dd', '', '查看绑定长辈的照护安排和获授权的完成记录')]),
        node('div', '', [node('dt', '', '用药凭证'), node('dd', '', '按家属账号单独开通查阅范围')]),
        node('div', '', [node('dt', '', '巡查简报'), node('dd', '', '长辈授权后由家属订阅站内简报')]),
      ]),
      canShareConsent && canViewResidents
        ? action(ctx, '到入住管理核对分享授权', () => ctx.go('residents','all'))
        : null,
    ]);
    panels.append(panel(ctx, '家属查阅范围', 'people', body,
      canManageFamily ? action(ctx, '管理门户权限', () => ctx.go('access')) : null));
  }
  desk.append(panels);
  return desk;
}
