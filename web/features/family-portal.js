import {
  badge, btn, canAct, choose, facts, link, named, node, page, section, table,
} from './shared.js';
import { residentLabel } from './people-labels.js';
import { healthProfile } from './resident-health.js';
import { residentDailyReadOnly } from './resident-insights.js';
import { dailyTimeline } from './daily-timeline.js';
import { renderMedicationReports } from './medication-reports.js';
import { familyInbox, familyRecipients } from './family-rounds.js';

const stamp = value => value?.replace('T', ' ') || '—';

function historyTable(ctx, scope, config) {
  const total = ctx.state.portalTotals?.[scope] || 0;
  if (total <= config.rows.length) return table(ctx, config);
  const root = node('section', 'family-history');
  let request = 0;
  async function load(offset) {
    const ticket = ++request;
    try {
      const params = new URLSearchParams({offset, revision: ctx.state.revision});
      const result = await ctx.get('/api/portal/history/' + scope + '?' + params);
      if (ticket === request) render(result.rows, result.offset);
    } catch (error) {
      if (root.isConnected && ticket === request) ctx.toast(error.message);
    }
  }
  function render(rows, offset) {
    const earlier = offset + rows.length;
    const pager = choose(
      offset ? btn(ctx, '上一组', () => load(Math.max(0, offset - 30))) : null,
      node('span', 'fx-muted', (offset + 1) + '–' + earlier + ' / ' + total),
      earlier < total ? btn(ctx, '更早记录', () => load(earlier)) : null,
    );
    root.replaceChildren(table(ctx, {...config, rows, action: pager}));
  }
  render(config.rows, 0);
  return root;
}

function rateService(ctx, task) {
  ctx.dialog({
    title: '评价本次服务',
    description: task.title,
    fields: [
      {name: 'rating', label: '满意度', type: 'select', required: true,
        options: [{value: '', label: '请选择'}, ...[5, 4, 3, 2, 1].map(value => ({value, label: value + ' 分'}))]},
      {name: 'note', label: '评价意见', type: 'textarea', maxLength: 500},
    ],
    onSubmit: values => ctx.command('portal.feedback', {taskId: task.id, rating: Number(values.rating), note: values.note}),
  });
}

function services(ctx, completed = false) {
  const rows = completed ? ctx.state.familyServiceHistory : ctx.state.portalTasks;
  const title = completed ? '已完成服务' : '照护工单进度';
  function details(row) {
    ctx.detail('照护服务详情', facts([
      ['服务项目', row.title], ['服务状态', completed ? '已完成' : row.status],
      ['计划日期', row.date], ['计划时间', row.time], ['完成日期', stamp(row.completedAt)],
      ...(row.menu?.length ? [['工单菜单', row.menu.join('、')]] : []),
      ...(row.rating ? [['我的评价', row.rating + ' 分']] : []),
    ]));
  }
  const cols = [
    {label: '服务项目', view: row => link(ctx, row.title, () => details(row))},
    {label: '计划时间', view: row => [row.date, row.time].filter(Boolean).join(' ')},
    {label: '完成日期', view: row => stamp(row.completedAt)},
  ];
  if (!completed) {
    cols.push({label: '状态', view: row => badge(ctx, row.status, row.status === '已完成' ? 'green' : 'neutral')});
    cols.push({label: '服务评价', view: row => row.rating ? row.rating + ' 分' :
      row.status === '已完成' && canAct(ctx, 'portal.feedback') ? link(ctx, '评价', () => rateService(ctx, row)) : '—'});
  }
  const config = {title, cols, rows: rows || [], empty: '暂无这类照护服务。',
    search: {placeholder: completed ? '搜索近期服务项目' : '搜索本组服务项目', value: row => row.title}};
  return completed ? table(ctx, config) : historyTable(ctx, 'careSchedule', config);
}

function medications(ctx) {
  return historyTable(ctx, 'medication', {
    title: '医嘱与给药记录', rows: ctx.state.portalMedication || [], empty: '暂无已复核的医嘱。',
    cols: [
      {label: '药品', view: row => link(ctx, row.name, () => ctx.detail('给药记录详情', facts([
        ['药品', row.name], ['已复核医嘱', row.instruction], ['医嘱复核日期', stamp(row.reviewedAt)],
        ['计划时间', stamp(row.scheduledAt)], ['实际执行', stamp(row.executedTime || row.executedAt)], ['状态', row.status],
      ])))},
      {label: '已复核医嘱', view: row => row.instruction}, {label: '计划时间', view: row => stamp(row.scheduledAt)},
      {label: '执行状态', view: row => badge(ctx, row.status, row.status === '已执行' ? 'green' : 'neutral')},
      {label: '实际执行', view: row => stamp(row.executedTime || row.executedAt)},
    ],
  });
}

function billing(ctx) {
  return table(ctx, {
    title: '缴费与续住提醒', rows: ctx.state.billingNotices || [], empty: '暂时没有缴费或续住提醒。',
    filter: {label: '提醒类型', all: '全部提醒', value: r => r.title},
    cols: [
      {label: '提醒事项', view: row => link(ctx, row.title, () => ctx.detail('账单提醒详情', facts([
        ['提醒事项', row.title], ['提醒日期', row.date],
        [row.kind === 'contractExpired' ? '合同到期日' : '账单日', row.billingDate], ['提醒内容', row.message],
      ])))},
      {label: '对应日期', view: row => named(row.billingDate, row.kind === 'contractExpired' ? '合同到期日' : '账单日')},
      {label: '提醒日期', view: row => row.date}, {label: '提醒内容', view: row => row.message},
    ],
  });
}

export function familyPortal(ctx, relativeFields, editRelative) {
  const user = ctx.state.user;
  const person = ctx.state.residents?.find(row => row.id === user.residentId);
  if (!person) return ctx.ui.empty('此账号尚未绑定有效长辈，请联系机构。');
  const scopes = new Set(user.portalScopes || []);
  const relative = ctx.state.relativeProfiles?.find(row => row.accountId === user.id) || {};
  const inbox = ctx.state.familyRoundInbox;
  const unread = inbox?.messages.filter(row => !row.readAt).length || 0;
  const hasProgress = scopes.has('careSchedule') && Array.isArray(ctx.state.portalTasks);
  const hasMedication = scopes.has('medication') && Array.isArray(ctx.state.portalMedication);
  const sections = [];
  function group(label, views) {
    const enabled = views.filter(Boolean);
    if (enabled.length) sections.push({label, views: enabled});
  }
  group(unread ? '收件箱（' + unread + '）' : '收件箱', [inbox && ['briefs', '巡查简报', () => familyInbox(ctx, person)]]);
  group('照护服务', [
    hasProgress && ['tasks', '工单进度', () => services(ctx)],
    user.familyServices && ['completed', '已完成服务', () => services(ctx, true)],
  ]);
  group('账单与提醒', [scopes.has('billingNotices') && ['billingNotices', '缴费提醒', () => billing(ctx)]]);
  group('用药记录', [
    hasMedication && ['medication', '医嘱与给药记录', () => medications(ctx)],
    user.portalSelf && scopes.has('medicationReport') && ['medicationReport', '我的用药自报', () => renderMedicationReports(ctx, person.id)],
  ]);
  group('生活与健康', [user.portalSelf && scopes.has('personalHealth') && ['personalHealth', '我的生活与健康',
    () => node('div', 'personal-life', [residentDailyReadOnly(ctx, person.id), healthProfile(ctx, person), dailyTimeline(ctx, person)])]]);
  group('分享授权', [user.portalSelf && ctx.state.familyRoundRecipients && ['sharing', '简报分享授权', () => familyRecipients(ctx, person)]]);
  const profileSection = (label, fields) => section(label, facts(fields.map(([key, title]) => [title, relative[key]])));
  const edit = () => editRelative(ctx, person, user.id, relative);
  group('我的亲属资料', [!user.portalSelf && ['relative', '身份与联系', () => node('section', 'fx-panel family-profile-details', [
    node('header', 'fx-toolbar', [node('h2', '', '我的亲属资料'), canAct(ctx, 'dossier.relative') ? btn(ctx, '编辑本人资料', edit) : null]),
    node('div', 'fx-family-details', [
      profileSection('身份与联系', relativeFields.slice(0, 4)), profileSection('其他联系方式', relativeFields.slice(4)),
    ]),
  ])]]);

  const memory = ctx.workspaceState ||= {};
  const prefs = memory.familyViews ||= {};
  const requested = new URLSearchParams(location.hash.split('?')[1]).get('tab');
  const all = sections.flatMap(s => s.views);
  if (requested !== prefs.lastRoute) {
    prefs.lastRoute = requested;
    if (requested) prefs.current = requested;
  }
  const selected = all.find(([id]) => id === prefs.current)?.[0] || all[0]?.[0];
  const bar = node('nav', 'family-views');
  bar.setAttribute('aria-label', '服务分类');
  const body = node('div', 'family-view-body');
  const sub = node('div', 'family-subviews');
  function show(id) {
    prefs.current = id;
    const active = sections.find(s => s.views.some(v => v[0] === id));
    if (!active) return;
    prefs[active.views[0][0]] = id;
    for (const button of bar.children) {
      const on = button.dataset.group === active.views[0][0];
      button.setAttribute('aria-pressed', String(on));
    }
    sub.hidden = active.views.length < 2;
    sub.replaceChildren(...active.views.map(([key, label]) => {
      const button = btn(ctx, label, () => show(key), 'ghost');
      button.setAttribute('aria-pressed', String(key === id));
      return button;
    }));
    body.replaceChildren(active.views.find(v => v[0] === id)[2]());
  }
  for (const item of sections) {
    const key = item.views[0][0];
    const button = btn(ctx, item.label, () => show(item.views.find(v => v[0] === prefs[key])?.[0] || key), 'ghost');
    button.dataset.group = key;
    bar.append(button);
  }
  const identity = node('section', 'family-resident-summary', [
    node('div', 'family-resident-heading', [node('span', 'family-mark', ctx.ui.icon('people', 24)),
      named(residentLabel(ctx, person), user.portalSelf ? '我的入住档案' : '本账号绑定的长辈')]),
    ctx.state.uiSettings.institutionName ? node('div', 'family-place', [ctx.ui.icon('building', 16), ctx.state.uiSettings.institutionName]) : null,
  ]);
  const home = page(ctx, user.portalSelf ? '长辈服务' : '家属服务', '', null, identity, bar, sub, body);
  home.classList.add('family-service-desk');
  if (selected) show(selected);
  else body.append(ctx.ui.empty('当前账号尚未开通服务记录查阅。'));
  return home;
}
