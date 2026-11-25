import { staffLabel } from './people-labels.js';
import {
  badge, btn, canAct, choose, facts, field, link, memo, named, node, page, section, select, table, tabs, today,
} from './shared.js';
import { bookingForm, schedulePage } from './lead-schedule.js';

const sources = { consent: '宣传页授权留号', visit: '网页申请参观', manual: '员工登记' };
const outcomes = ['有参观意向', '继续联系', '未接通', '暂无意向'];
const chinaClock = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});

function stamp(value) {
  if (!value) return '';
  if (typeof value === 'string' && !/[zZ]|[+-]\d\d:\d\d$/.test(value)) return value.replace('T', ' ');
  return chinaClock.format(new Date(value));
}

function occurrenceField(label) {
  const now = stamp(new Date()).replace(' ', 'T');
  return field('occurredAt', label, { type: 'datetime-local', step: 1, value: now });
}

const leadName = r => (r.name || r.directoryLinks?.find(x => x.contact)?.contact || '未留姓名') +
  (r.directoryLinks?.length ? '' : '（新客）');
const relationships = row => (row.directoryLinks || []).map(x => x.residentId
  ? [x.bed && x.bed + '床', x.residentName + '的' + x.relation, x.contact].filter(Boolean).join(' ')
  : [x.contact, x.relation].filter(Boolean).join('（') + (x.contact && x.relation ? '）' : '')).join('、');
const exempt = r => r.callbackExempt || r.callbackStopped;
export function pendingLeadCalls(state) {
  return (state.leadContacts || []).filter(r => r.status === '待回访' && !exempt(r)).length;
}
function callbackNote(row) {
  if (row.callbackExemptReason === 'admitted') return '已入住 · 免回访';
  if (row.callbackExemptReason === 'directory') return '已有联系档案 · 免回访';
  return row.callbackExempt ? '免回访' : row.callbackStopped ? '已停止回访' : '';
}
const campusName = (ctx, id) => ctx.state.leadCampuses?.find(c => c.id === id)?.name || '—';
const contacts = ctx => ctx.state.leadContacts || [];
const events = ctx => ctx.state.leadEvents || [];
const recentFirst = (rows, key) => [...rows].sort((a, b) => String(b[key]).localeCompare(String(a[key])));

function branchField(ctx) {
  return select('campusId', '所属分院', (ctx.state.leadCampuses || []).map(c => ({ value: c.id, label: c.name })));
}

export function registerLead(ctx) {
  const dialog = ctx.dialog({
    title: '手工登记客户',
    fields: [
      select('channel', '登记方式', [{ value: 'incoming', label: '电话来电' }, { value: 'walkin', label: '直接到访' }]),
      branchField(ctx),
      field('phone', '联系电话', { type: 'tel', maxLength: 24 }),
      field('name', '客户称呼', { required: false, maxLength: 60 }),
      occurrenceField('来电时间'),
      memo('note', '咨询或来访事项', false, { maxLength: 1000 }),
    ],
    submitLabel: '核对登记',
    onSubmit: values => ctx.command('leads.register', values, {
      title: '确认客户登记', target: values.name || values.phone,
      fields: [
        ['登记方式', values.channel === 'incoming' ? '电话来电' : '直接到访'],
        ['联系电话', values.phone], ['发生时间', stamp(values.occurredAt)],
        ['所属分院', campusName(ctx, values.campusId)], ['咨询或来访事项', values.note || '—'],
      ],
    }),
  });
  const form = dialog.querySelector('form');
  form.elements.channel.onchange = () => {
    form.elements.occurredAt.labels[0].firstElementChild.firstChild.textContent =
      form.elements.channel.value === 'walkin' ? '到访时间' : '来电时间';
  };
}

function callForm(ctx, row, direction) {
  const outgoing = direction === 'outgoing';
  const title = outgoing ? '记录电话回访' : '登记再次来电';
  const fields = [occurrenceField(outgoing ? '回访时间' : '来电时间')];
  if (outgoing) fields.push(select('outcome', '客户意向', [
    { value: '', label: '请选择回访结果' }, ...outcomes,
  ]));
  fields.push(select('callbackStopped', '后续电话联系', [
    { value: 'false', label: '保留当前联系意愿' }, { value: 'true', label: '客户要求停止回访' },
  ]));
  fields.push(memo('feedback', '沟通反馈', true, { maxLength: 1000 }));
  return ctx.dialog({
    title, description: leadName(row) + ' · ' + row.phone, fields, submitLabel: '核对记录',
    onSubmit: values => ctx.command('leads.call', { leadId: row.id, direction, ...values, callbackStopped: values.callbackStopped === 'true' }, {
      title, target: row.name || row.phone,
      fields: [
        ['发生时间', stamp(values.occurredAt)], ...(outgoing ? [['客户意向', values.outcome]] : []),
        ['沟通反馈', values.feedback],
        ...((values.callbackStopped === 'true' || values.outcome === '暂无意向') ? [['后续联系', '停止电话回访']] : []),
      ],
    }),
  });
}

function receptionForm(ctx, row, archive) {
  const title = archive ? '归档意向客户' : '记录接待反馈';
  return ctx.dialog({
    title, description: archive
      ? leadName(row) + ' · 客户将进入归档记录，尚未执行的预约会一并取消。'
      : leadName(row) + ' · ' + row.phone,
    fields: [
      ...(archive ? [] : [occurrenceField('实际接待时间')]),
      memo('feedback', archive ? '归档说明与最终反馈' : '来访情况与反馈', true, { maxLength: 1000 }),
    ],
    submitLabel: archive ? '核对归档' : '核对反馈',
    onSubmit: values => ctx.command(archive ? 'leads.archive' : 'leads.feedback', { leadId: row.id, ...values }, {
      title, target: row.name || row.phone, fields: [['反馈', values.feedback]], confirmLabel: archive ? '确认归档' : '保存反馈',
    }),
  });
}

function detail(ctx, row) {
  const closed = row.status === '已归档';
  const dial = node('a', 'lead-phone', row.phone);
  dial.href = 'tel:' + row.phone;
  const header = node('header', 'lead-detail-head', [
    named(leadName(row), campusName(ctx, row.campusId)), dial, badge(ctx, row.status),
  ]);
  const bookings = (ctx.state.visitBookings || []).filter(b => b.leadId === row.id && b.status === 'confirmed');
  const history = recentFirst(events(ctx).filter(e => e.leadId === row.id), 'occurredAt');
  const entries = history.map(e => node('li', '', [
    node('time', '', stamp(e.occurredAt)),
    node('div', '', [
      node('strong', '', e.kind), e.actorName ? node('small', 'fx-muted', ' · ' + staffLabel(ctx, e.actorName, e.actorId)) : null,
      e.preferredAt ? node('p', '', '期望到访 ' + stamp(e.preferredAt)) : null,
      e.date && e.start && e.end ? node('p', '', (e.bookingKind === 'callback' ? '电话回访' : '参观接待') + ' · ' + e.date + ' ' + e.start + '–' + e.end + ' · 席位 ' + e.seat) : null,
      e.outcome ? node('div', 'lead-event-outcome', e.outcome) : null,
      e.feedback ? node('p', '', e.feedback) : null,
    ]),
  ]));
  return ctx.detail('客户联系记录', node('div', 'fx-profile', [
    header,
    facts([
      ['号码关联', relationships(row) || '新客，尚无关联档案'], ['来源', sources[row.source]], ['首次登记', stamp(row.createdAt)],
      ['客户意向', row.note], ['期望到访', stamp(row.preferredAt) || '待商定'],
      ...(exempt(row) ? [['电话回访', callbackNote(row)]] : []),
      ...(row.archiveFeedback ? [['归档反馈', row.archiveFeedback]] : []),
    ]),
    bookings.length ? section('已确认的安排', node('div', 'lead-arrangements', bookings.map(b =>
      link(ctx, (b.kind === 'callback' ? '电话回访' : '参观接待') + ' · ' + b.date + ' ' + b.start + '–' + b.end + ' · 席位 ' + b.seat,
        () => bookingForm(ctx, row, { ...b, existing: true })),
    ))) : null,
    closed ? null : choose(
      canAct(ctx, 'leads.call') && !exempt(row) ? btn(ctx, '记录电话回访', () => callForm(ctx, row, 'outgoing'), 'primary') : null,
      canAct(ctx, 'leads.call') ? btn(ctx, '登记再次来电', () => callForm(ctx, row, 'incoming')) : null,
      canAct(ctx, 'leads.book') ? btn(ctx, '电话确认排期', () => bookingForm(ctx, row)) : null,
      canAct(ctx, 'leads.feedback') ? btn(ctx, '接待反馈', () => receptionForm(ctx, row, false)) : null,
      canAct(ctx, 'leads.archive') ? btn(ctx, '归档', () => receptionForm(ctx, row, true)) : null,
    ),
    section('联系与接待经过', entries.length ? node('ol', 'lead-events', entries) : node('p', 'fx-muted', '尚无沟通记录')),
  ]));
}

function registry(ctx, archive) {
  const rows = recentFirst(contacts(ctx).filter(r => archive === (r.status === '已归档')), 'updatedAt');
  const filters = [{ text: '待电话回访', match: r => !exempt(r) && r.status === '待回访' },
    { text: '待接待', match: r => r.status === '待接待' }, { text: '跟进中', match: r => r.status === '跟进中' },
    { text: '免回访', match: exempt }];
  const sourceFilters = Object.entries(sources).map(([id, text]) => ({ text, match: r => r.source === id }));
  const choices = archive ? sourceFilters : [...filters, ...sourceFilters];
  return table(ctx, {
    title: archive ? '近 365 天归档客户' : '跟进中的客户',
    rows, empty: archive ? '尚无归档客户' : '暂无待跟进客户，可手工登记来电或来访。',
    search: { placeholder: '搜索客户、电话、床号或关联长辈', value: r => [leadName(r), r.phone, relationships(r), campusName(ctx, r.campusId)].join(' ') },
    filter: { label: '筛选客户', all: '全部客户', options: choices.map(c => c.text), matches: (r, text) => choices.find(c => c.text === text)?.match(r) },
    cols: [
      { label: '客户', view: r => named(leadName(r), r.phone) },
      { label: '号码关联', view: r => relationships(r) || '—' },
      { label: '来源 / 分院', view: r => named(sources[r.source], campusName(ctx, r.campusId)) },
      { label: archive ? '归档时间' : '最近跟进', view: r => stamp(archive ? r.archivedAt : r.updatedAt) },
      { label: archive ? '归档说明' : '跟进状态', view: r => archive ? node('span', 'lead-summary', r.archiveFeedback || '—')
        : node('div', 'lead-status', [badge(ctx, exempt(r) && r.status === '待回访' ? callbackNote(r) : r.status, r.status === '待回访' && !exempt(r) ? 'amber' : 'blue'), exempt(r) && r.status !== '待回访' ? node('small', 'fx-muted', callbackNote(r)) : null]) },
      { label: '操作', view: r => choose(
        !archive && !exempt(r) && canAct(ctx, 'leads.call') ? link(ctx, '记录回访', () => callForm(ctx, r, 'outgoing')) : null,
        !archive && canAct(ctx, 'leads.book') ? link(ctx, '排期', () => bookingForm(ctx, r)) : null,
        link(ctx, '查看记录', () => detail(ctx, r)),
      ) },
    ],
  });
}

function incomingList(ctx, campusId, date) {
  const inBranch = new Map(contacts(ctx).filter(r => r.campusId === campusId).map(r => [r.id, r]));
  const rows = recentFirst(events(ctx).filter(e => e.kind === '来电' && inBranch.has(e.leadId) && stamp(e.occurredAt).slice(0, 10) === date), 'occurredAt');
  return table(ctx, {
    title: '当日客户来电', rows, empty: '当天没有登记来电。',
    cols: [
      { label: '来电时间', view: e => stamp(e.occurredAt).slice(11) },
      { label: '客户', view: e => named(leadName(inBranch.get(e.leadId)), inBranch.get(e.leadId).phone) },
      { label: '沟通反馈', view: e => e.feedback || '—' }, { label: '记录人员', view: e => staffLabel(ctx, e.actorName, e.actorId) },
      { label: '操作', view: e => link(ctx, '查看记录', () => detail(ctx, inBranch.get(e.leadId))) },
    ],
  });
}

export function leadsPage(ctx) {
  const day = today(ctx);
  const pending = pendingLeadCalls(ctx.state);
  const coming = (ctx.state.visitBookings || []).filter(b => b.kind === 'visit' && b.status === 'confirmed' && b.date === day).length;
  const calls = events(ctx).filter(e => e.kind === '来电' && stamp(e.occurredAt).slice(0, 10) === day).length;
  const counts = node('dl', 'lead-counts', [
    ['待电话回访', pending, 'clock'], ['今日待接待', coming, 'calendar'], ['今日来电', calls, 'list'],
  ].map(([label, number, icon]) => node('div', '', [node('dt', '', [ctx.ui.icon(icon, 16), label]), node('dd', '', number)])));
  return page(ctx, '意向客户', '', canAct(ctx, 'leads.register')
    ? ctx.ui.button('手工登记', () => registerLead(ctx), 'primary', 'plus') : null,
    counts,
    tabs('leads', [
      ['contacts', '客户跟进', () => registry(ctx, false)],
      ['schedule', '接待时间表', () => schedulePage(ctx, incomingList, r => detail(ctx, r))],
      ['archive', '归档记录', () => registry(ctx, true)],
    ]),
  );
}
