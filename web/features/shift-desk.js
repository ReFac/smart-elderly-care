import {
  badge, btn, canAct, choose, facts, field, hasGrant, link, named, node,
  options, page, records, runForm, select, staffField, table, today,
} from './shared.js';
import { residentAnchor, staffLabel } from './people-labels.js';

const periods = ['早班', '中班', '夜班'];
const weekNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function plusDays(value, offset) {
  const date = new Date(value + 'T12:00:00Z');
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}

function monday(value) {
  const weekday = new Date(value + 'T12:00:00Z').getUTCDay();
  return plusDays(value, -((weekday + 6) % 7));
}

export function shiftForm(ctx, preset = {}) {
  const branches = ctx.state.campusOptions || [];
  return runForm(ctx, {
    title: '安排班次',
    action: 'ops.shift',
    fields: [
      select('campusId', '值班分院', branches.map(c => ({value: c.id, label: c.name})),
        {value: preset.campusId || branches[0]?.id}),
      staffField(ctx, 'staff', '值班人员'),
      field('date', '排班日期', {type: 'date', value: preset.date || today(ctx)}),
      select('period', '班次', options(periods), {value: preset.period || periods[0]}),
    ],
  });
}

export function shifts(ctx) {
  const memory = ctx.workspaceState ||= {};
  const state = memory.staffSchedule ||= {layout: 'week', date: today(ctx), campus: '', period: '', query: ''};
  const branches = new Map((ctx.state.campusOptions || []).map(c => [c.id, c.name]));
  const roster = ctx.state.shifts || [];
  const canAssign = canAct(ctx, 'ops.shift');
  const canReadTasks = hasGrant(ctx, 'care');
  const tasksByPersonDay = new Map();
  if (canReadTasks) {
    for (const task of ctx.state.tasks || []) {
      if (task.status === '已取消') continue;
      const key = JSON.stringify([task.assignee, task.date]);
      if (!tasksByPersonDay.has(key)) tasksByPersonDay.set(key, []);
      tasksByPersonDay.get(key).push(task);
    }
  }
  const work = shift => tasksByPersonDay.get(JSON.stringify([shift.staff, shift.date])) || [];
  const campus = shift => shift.campusId || 'campus-main';
  const branchName = shift => branches.get(campus(shift)) || '分院未登记';
  const labels = new Map();
  function employee(shift) {
    const key = JSON.stringify([shift.staffId, shift.staff]);
    if (!labels.has(key)) labels.set(key, staffLabel(ctx, shift.staff, shift.staffId));
    return labels.get(key);
  }

  function open(shift) {
    ctx.detail('班次详情', node('div', 'fx-profile', [
      facts([
        ['值班人员', employee(shift)], ['日期', shift.date],
        ['班次', shift.period], ['值班分院', branchName(shift)],
      ]),
      canReadTasks ? node('section', 'fx-section', [
        node('h3', '', '当日照护工单'),
        records(work(shift), t => named(t.title, node('span', '', [
          residentAnchor(ctx, t.residentId), ' · ', t.time, ' · ', t.status,
        ])), '当日没有已分配的照护工单。'),
      ]) : null,
    ]));
  }

  function selector(label, values, key) {
    const input = node('select', 'fx-input');
    input.setAttribute('aria-label', label);
    for (const [value, title] of values) input.add(new Option(title, value));
    input.value = state[key];
    state[key] = input.value;
    input.onchange = () => { state[key] = input.value; draw(); };
    return node('label', 'agenda-field', [label, input]);
  }

  const day = node('input', 'fx-input');
  day.type = 'date';
  day.value = state.date;
  day.setAttribute('aria-label', '排班参考日期');
  function setDate(value) {
    state.date = day.value = value;
    draw();
  }
  day.onchange = () => setDate(day.value || today(ctx));
  const query = node('input', 'fx-input');
  query.type = 'search';
  query.placeholder = '姓名或岗位';
  query.value = state.query;
  query.oninput = () => { state.query = query.value; draw(); };
  const modes = choose();
  modes.classList.add('desk-view-switch');
  for (const [id, title] of [['week', '周排班'], ['ledger', '全部排班台账']]) {
    const button = btn(ctx, title, () => { state.layout = id; draw(); }, 'ghost');
    button.dataset.layout = id;
    modes.append(button);
  }
  const filters = node('section', 'agenda-filter', [
    selector('值班分院', [['', '全部分院'], ...branches], 'campus'),
    selector('班次', [['', '全部班次'], ...periods.map(value => [value, value])], 'period'),
    node('label', 'agenda-field', ['值班人员', query]), modes,
  ]);
  const pickDate = node('div', 'agenda-date', [
    btn(ctx, '上一周', () => setDate(plusDays(state.date, -7))), day,
    btn(ctx, '下一周', () => setDate(plusDays(state.date, 7))),
    link(ctx, '本周', () => setDate(today(ctx))),
  ]);
  const list = node('div', 'agenda-results');

  function ledger(shifts) {
    const cols = [
      {label: '值班日期', view: s => s.date}, {label: '值班人员', view: employee},
      {label: '班次', view: s => badge(ctx, s.period, 'blue')}, {label: '值班分院', view: branchName},
    ];
    if (canReadTasks) cols.push({label: '当日照护工单', view: s => work(s).length + ' 项'});
    cols.push({label: '操作', view: s => link(ctx, '班次详情', () => open(s))});
    return table(ctx, {
      title: '人员排班台账', rows: shifts.sort((a, b) => b.date.localeCompare(a.date)),
      cols, empty: '当前筛选没有排班记录。',
    });
  }

  function cell(date, period, assignments) {
    const items = assignments.map(s => btn(ctx, employee(s), () => open(s), 'ghost'));
    if (canAssign) {
      const add = link(ctx, '安排班次', () => shiftForm(ctx, {date, period, campusId: state.campus}));
      add.classList.add('shift-add');
      add.setAttribute('aria-label', date + ' ' + period + '安排班次');
      items.push(add);
    } else if (!assignments.length) {
      items.push(node('small', 'fx-muted', '未排班'));
    }
    return node('td', '', items);
  }

  function calendar(shifts) {
    const start = monday(state.date);
    const days = weekNames.map((_, index) => plusDays(start, index));
    const weekly = shifts.filter(s => s.date >= start && s.date <= days[6]);
    const slots = new Map();
    for (const item of weekly) {
      const key = item.date + item.period;
      if (!slots.has(key)) slots.set(key, []);
      slots.get(key).push(item);
    }
    const headers = days.map((date, i) => node('th', date === today(ctx) ? 'agenda-today' : '',
      named(weekNames[i], date.slice(5))));
    const head = node('thead', '', node('tr', '', [node('th', '', '班次'), ...headers]));
    const body = node('tbody');
    for (const period of periods.filter(p => !state.period || p === state.period)) {
      body.append(node('tr', '', [node('th', '', period),
        ...days.map(date => cell(date, period, slots.get(date + period) || []))]));
    }
    return node('section', 'fx-panel', [
      node('div', 'agenda-toolbar', [named(start + ' 至 ' + days[6], weekly.length + ' 个班次'), pickDate]),
      node('div', 'fx-table-wrap', node('table', 'shift-calendar', [head, body])),
    ]);
  }

  function draw() {
    for (const button of modes.children) {
      button.setAttribute('aria-pressed', String(button.dataset.layout === state.layout));
    }
    const term = state.query.trim().normalize('NFKC').toLowerCase();
    const matches = roster.filter(s =>
      (!state.campus || campus(s) === state.campus) && (!state.period || s.period === state.period) &&
      (!term || employee(s).normalize('NFKC').toLowerCase().includes(term)));
    list.replaceChildren(state.layout === 'ledger' ? ledger(matches) : calendar(matches));
  }

  const add = canAssign ? btn(ctx, '安排班次', () => shiftForm(ctx, {date: state.date, campusId: state.campus}), 'primary') : null;
  const root = page(ctx, '人员排班', '', add, filters, list);
  draw();
  return root;
}
