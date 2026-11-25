import { residentAnchor, staffLabel } from './people-labels.js';
import { badge, btn, canAct, hasGrant, link, named, node, residentName, table } from './shared.js';
import { dueMedicationCount, medicationDue } from './medication-rules.js';

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

export function ledgerDigest(items) {
  return node('dl', 'care-digest', items.map(([label, count]) =>
    node('div', '', [node('dt', '', label), node('dd', '', count)])));
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

export function healthDesk(ctx, actions) {
  const state = ctx.state;
  const vitals = canAct(ctx, 'care.vital') ? state.vitals || [] : [];
  const canAlerts = hasGrant(ctx, 'alerts') && ctx.available('inbox');
  const alerts = canAlerts ? (state.gatewayAlerts || []).filter(r => r.status === '待复核') : [];
  const orders = ctx.available('medications') ? state.medications || [] : [];
  const tasks = canAct(ctx, 'care.completeTask') ? (state.tasks || []).filter(r =>
    r.status === '待执行' && r.date <= state.today) : [];
  const handovers = canAct(ctx, 'care.handover') ? (state.handovers || []).filter(r =>
    r.status === '待签收' && r.assigneeId === state.user.id) : [];
  const people = new Map((state.residents || []).map(r => [r.id, r]));
  const peopleLabel = r => r.residentId ? residentName(ctx, people.get(r.residentId)) : r.subject || '全院交班';
  const desk = document.createElement('care-health-desk');
  const toolbar = node('div', 'fx-actions', [
    canAct(ctx,'care.vital') ? btn(ctx, '录入体征', actions.vitalForm) : null,
    canAct(ctx,'care.handover') ? btn(ctx, '登记交班', e => actions.createHandover(e.currentTarget)) : null,
  ]);
  let previousDue = -1;
  desk.refreshDue = () => {
    const now = Date.now();
    const due = dueMedicationCount(orders, now);
    if (due === previousDue) return;
    previousDue = due;
    const rows = [];
    for (const v of vitals.filter(v => v.status === '待复核' || v.date === state.today)) {
      const pending = v.status === '待复核';
      const resolve = pending && canAct(ctx, 'care.resolveVital');
      rows.push({id:v.id, kind:'健康体征', title:v.metric, note:[v.value,v.unit].join(' '),
        date:v.date, residentId:v.residentId, person:staffLabel(ctx,v.operator,v.operatorId),
        status:v.status, tier:pending ? 0 : 3, label:resolve ? '记录处置' : '查看体征',
        open:() => resolve ? actions.resolveVital(v) : actions.inspectVital(v)});
    }
    for (const a of alerts) {
      rows.push({id:a.id, kind:'设备预警', title:a.signal === 'possible_fall' ? '疑似跌倒' :
        a.signal === 'prolonged_bedrest' ? '持续卧床提示' : a.signal,
        note:a.priority, date:(a.observedAt || '').replace('T',' ').slice(0,16), subject:a.room,
        status:a.status, tier:a.priority === '优先现场核实' ? 0 : 1, label:'查看预警',
        open:() => import('./gateways.js').then(m => m.inspectAlert(ctx,a)).catch(() => ctx.toast('预警详情暂时无法载入，请重试'))});
    }
    for (const m of orders) {
      const ready = medicationDue(m, now);
      if (!ready && m.status !== '待复核' && !(m.status === '待执行' && m.warnings?.length)) continue;
      rows.push({id:m.id, kind:'医嘱给药', title:m.name, note:m.warnings?.join('、') || m.instruction,
        date:(m.scheduledAt || m.date || '').replace('T',' '), residentId:m.residentId,
        person:staffLabel(ctx,m.assignee,m.assigneeId), status:ready ? '已到给药时刻' : m.status,
        tier:1, label:'查看医嘱', open:() => actions.openOrder(m)});
    }
    for (const h of handovers) {
      rows.push({id:h.id, kind:'班次交接', title:'班次交接', note:h.note, date:(h.createdAt || h.date || '').replace('T',' ').slice(0,16),
        residentId:h.residentId, subject:h.draftScope === 'personal' ? '交班人当班工单' : '全院交班',
        person:staffLabel(ctx,h.senderName,h.senderId), status:'待我签收', tier:1, label:'核对并签收',
        open:() => actions.showHandover(h)});
    }
    for (const t of tasks) {
      rows.push({id:t.id, kind:'照护工单', title:t.title, note:t.kind, date:[t.date,t.time].filter(Boolean).join(' '),
        residentId:t.residentId, person:staffLabel(ctx,t.assignee,t.assigneeId),
        status:t.date < state.today ? '逾期待执行' : t.status, tier:t.date < state.today ? 1 : 2,
        label:'查看工单', open:() => actions.inspectTask(t)});
    }
    rows.sort((a,b) => a.tier-b.tier || (a.date || '').localeCompare(b.date || '') || a.id.localeCompare(b.id));
    const groups = [['待处理',rows.filter(r=>r.tier<3).length]];
    if (canAct(ctx,'care.vital')) groups.push(['今日体征',vitals.filter(r=>r.date===state.today).length]);
    if (ctx.available('medications')) groups.push(['到时给药',due]);
    if (canAct(ctx,'care.handover')) groups.push(['待我签收',handovers.length]);
    desk.replaceChildren(ledgerDigest(groups), table(ctx,{
      title:'当班照护台账', rows, action:toolbar,
      search:{placeholder:'搜索长辈、房间、事项或人员',value:r=>[peopleLabel(r),r.note,r.title,r.status,r.person].join(' ')},
      filter:{label:'查看范围',all:'全部记录',options:['待处理','已登记体征',...new Set(rows.map(r=>r.kind))],
        matches:(r,s)=>s==='待处理' ? r.tier<3 : s==='已登记体征' ? r.kind==='健康体征'&&r.tier===3 : r.kind===s},
      cols:[{label:'事项类型',view:r=>r.kind},{label:'照护事项',view:r=>named(r.title,r.note)},
        {label:'长辈 / 房间',view:r=>r.residentId ? residentAnchor(ctx,people.get(r.residentId)) : peopleLabel(r)},
        {label:'业务时间',view:r=>r.date || '—'}, {label:'相关人员',view:r=>r.person || '—'},
        {label:'进度',view:r=>badge(ctx,r.status,r.tier===0?'red':r.tier===3?'green':'amber')},
        {label:'办理',align:'end',view:r=>link(ctx,r.label,r.open)}],
      empty:'授权范围内暂无当班照护记录',
    }));
  };
  return desk;
}
