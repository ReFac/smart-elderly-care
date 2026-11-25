import { badge, btn, choose, hasGrant, named, node, table, today } from './shared.js';

const types = { patrol: '定期巡查', care: '日常照护', meal: '伙食工单' };
const weekdayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const allWeek = weekdayNames.map((_, i) => i + 1);
const localTime = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

function label(text, control) {
  return node('label', 'field', [node('span', '', text), control]);
}

function choice(values, value = '') {
  const result = node('select');
  for (const [id, name] of values) result.add(new Option(name, id));
  result.value = value;
  return result;
}

function input(type, value, attributes = {}) {
  const result = node('input');
  result.type = type;
  result.value = value || '';
  Object.assign(result, attributes);
  return result;
}

function noteInput(value, placeholder, maxLength = 500) {
  const result = node('textarea');
  result.rows = 2;
  result.maxLength = maxLength;
  result.value = value || '';
  result.placeholder = placeholder;
  return result;
}

function weekdaysPicker(selected) {
  const values = new Set(selected);
  const inputs = allWeek.map(day => input('checkbox', '', { checked: values.has(day) }));
  return {
    element: node('fieldset', 'scheduled-repeat', [
      node('legend', '', '每周执行日'),
      node('div', 'scheduled-days', inputs.map((control, index) =>
        node('label', '', [control, weekdayNames[index]]))),
    ]),
    value: () => allWeek.filter((_, index) => inputs[index].checked),
  };
}

function recurrence(days) {
  return days.length === 7 ? '每日' : days.map(day => weekdayNames[day - 1]).filter(Boolean).join('、');
}

function stamp(value) {
  if (!value) return '—';
  if (/^\d{4}-\d\d-\d\d(?:T\d\d:\d\d(?::\d\d)?)?$/.test(value))
    return value.replace('T', ' ').slice(0, 16);
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : localTime.format(parsed);
}

function audiencePicker(directory, original) {
  const people = directory.roster.map(person => ({
    ...person, label: person.name + '（' + person.roomNumber + '）', description: person.bedLabel,
  }));
  const places = directory.rooms.map(room => ({ ...room, description: room.campusName }));
  const entries = {
    campus: directory.campuses.map(campus => ({ ...campus, label: campus.name })),
    rooms: places,
    residents: people,
  };
  const values = choice([
    ...(directory.allowAll ? [['all', '全部分院在住长辈']] : []),
    ...(directory.campuses.length ? [['campus', '按分院动态派发']] : []),
    ['rooms', '按房间动态派发'],
    ['residents', '指定长辈名单'],
  ], original?.kind || 'residents');
  const campuses = new Map(directory.rooms.map(room => [room.campusId, room.campusName]));
  for (const branch of directory.campuses) campuses.set(branch.id, branch.name);
  const campus = choice([['', '查看全部分院'], ...campuses]);
  const campusFilter = label('按分院筛选', campus);
  const find = input('search', '', { placeholder: '搜索长辈、床号或房间' });
  find.setAttribute('aria-label', '搜索执行范围候选项');
  const list = node('div', 'scheduled-residents');
  const count = node('strong', 'scheduled-selected');
  const missing = node('p', 'scheduled-missing');
  const targetOptions = node('fieldset', 'scheduled-roster', [
    node('legend', '', '勾选执行对象'), campusFilter,
    node('div', 'scheduled-roster-head', [find, count]), list, missing,
  ]);
  const selected = {
    campus: new Set(original?.campusIds || []),
    rooms: new Set(original?.roomIds || []),
    residents: new Set(original?.residentIds || []),
  };
  const chosen = () => (entries[values.value] || []).filter(row => selected[values.value].has(row.id));

  function draw() {
    const kind = values.value;
    targetOptions.hidden = kind === 'all';
    campusFilter.hidden = kind === 'campus';
    if (kind === 'all') return;
    const candidates = entries[kind] || [];
    find.placeholder = { campus: '搜索分院', rooms: '搜索房间', residents: '搜索长辈姓名、床号或房间' }[kind];
    const needle = find.value.trim().toLocaleLowerCase();
    const rows = candidates.filter(row =>
      (kind === 'campus' || !campus.value || row.campusId === campus.value) &&
      [row.label, row.description].some(text => String(text || '').toLocaleLowerCase().includes(needle)),
    );

    function syncCount() {
      const visible = chosen().length;
      count.textContent = '已选 ' + visible + { campus: ' 个分院', rooms: ' 间房', residents: ' 位长辈' }[kind];
      const absent = selected[kind].size - visible;
      missing.hidden = absent === 0;
      missing.textContent = absent ? '有 ' + absent + ' 个原执行对象已离开当前可选范围，请核对后保存。' : '';
    }

    list.replaceChildren(...rows.map(row => {
      const check = input('checkbox', '', { checked: selected[kind].has(row.id) });
      check.addEventListener('change', () => {
        if (check.checked) selected[kind].add(row.id);
        else selected[kind].delete(row.id);
        syncCount();
      });
      return node('label', '', [check, named(row.label, row.description)]);
    }));
    if (!rows.length) list.append(node('p', 'fx-muted', '没有符合条件的执行对象。'));
    syncCount();
  }

  values.addEventListener('change', () => { find.value = ''; draw(); });
  campus.addEventListener('change', draw);
  find.addEventListener('input', draw);
  draw();
  return {
    element: node('section', 'scheduled-audience', [node('h3', '', '执行范围'), label('派发对象', values), targetOptions]),
    value() {
      const kind = values.value;
      const field = { campus: 'campusIds', rooms: 'roomIds', residents: 'residentIds' }[kind];
      const rows = chosen();
      if (kind !== 'all' && !rows.length) throw new Error('请至少选择一个执行对象。');
      return {
        scope: field ? { kind, [field]: rows.map(row => row.id) } : { kind },
        display: field ? rows.map(row => row.label).join('、') : '全部分院在住长辈',
      };
    },
  };
}

function assigneePicker(directory, original) {
  const mode = choice([
    ['', '当班照护组'],
    ['person', '指定员工'],
    ['role', '指定岗位'],
  ], original.assigneeId ? 'person' : original.assigneeRole ? 'role' : '');
  const person = choice([
    ['', '请选择员工'], ...(directory.staff || []).map(row => [row.id, row.role ? row.label + ' · ' + row.role : row.label]),
  ], original.assigneeId || '');
  const role = choice([
    ['', '请选择岗位'], ...(directory.roles || []).map(value => [value, value]),
  ], original.assigneeRole || '');
  const namedPerson = label('执行员工', person);
  const namedRole = label('执行岗位', role);
  function sync() {
    namedPerson.hidden = mode.value !== 'person';
    namedRole.hidden = mode.value !== 'role';
    person.required = mode.value === 'person';
    role.required = mode.value === 'role';
  }
  mode.addEventListener('change', sync);
  sync();
  return {
    element: node('div', 'scheduled-form-grid', [label('分配方式', mode), namedPerson, namedRole]),
    value() {
      if (mode.value === 'person' && person.value) return { assigneeId: person.value };
      if (mode.value === 'role' && role.value) return { assigneeRole: role.value };
      return {};
    },
    label() {
      return mode.value === 'person' ? person.selectedOptions[0]?.text :
        mode.value === 'role' ? role.value : '当班照护组';
    },
  };
}

function menuItems(value) {
  const items = value.split(/[\r\n、，,]+/).map(item => item.trim()).filter(Boolean);
  if (!items.length || items.length > 20 || items.some(item => Array.from(item).length > 80))
    throw new Error('请填写 1 至 20 道菜品，每道不超过 80 字。');
  if (new Set(items).size !== items.length) throw new Error('请合并重复菜品后再保存。');
  return items;
}

function mealPicker(preset) {
  const course = choice([['早餐', '早餐'], ['午餐', '午餐'], ['晚餐', '晚餐']], preset.mealKind || '午餐');
  const fallback = noteInput(preset.menu?.join('\n'), '例如 米饭、番茄炒蛋、白菜汤', 1800);
  const summary = node('summary', '');
  const schedule = allWeek.map(day => {
    const control = noteInput(preset.weeklyMenus?.[day]?.join('\n'), '此日可留空，沿用默认菜单', 1800);
    control.name = 'weeklyMenu' + day;
    const activity = node('small', 'scheduled-day-status', '当天不派发');
    const caption = node('span', '', [weekdayNames[day - 1], activity]);
    return { day, control, activity, element: node('label', 'scheduled-week-menu field', [caption, control]) };
  });
  const week = node('details', 'scheduled-week-menus', [
    summary, node('div', 'scheduled-week-grid', schedule.map(item => item.element)),
  ]);
  week.open = schedule.some(item => item.control.value.trim());
  function title() {
    const count = schedule.filter(item => item.control.value.trim()).length;
    summary.textContent = '按星期安排菜单' + (count ? ' · 已填写 ' + count + ' 天' : '');
  }
  for (const {control} of schedule) control.addEventListener('input', title);
  title();
  const element = node('fieldset', 'scheduled-meal-info', [
    node('legend', '', '伙食菜单'),
    node('div', 'scheduled-meal-top', [label('餐次', course), label('默认菜品', fallback)]),
    node('p', 'fx-muted', '每行一道菜，也可用顿号分隔。指定日期的餐单优先生效。其余日期使用对应星期的菜品，留空时沿用默认菜品。'),
    week,
  ]);
  return {
    element,
    update(isMeal, activeDays) {
      element.hidden = !isMeal;
      fallback.required = isMeal;
      for (const {day, activity} of schedule) activity.hidden = activeDays.includes(day);
    },
    value() {
      const menu = menuItems(fallback.value);
      const weeklyMenus = {};
      for (const {day, control} of schedule) {
        if (!control.value.trim()) continue;
        try {
          weeklyMenus[day] = menuItems(control.value);
        } catch (error) {
          week.open = true;
          control.focus();
          throw new Error('请核对' + weekdayNames[day - 1] + '菜单。' + error.message);
        }
      }
      return { mealKind: course.value, menu, weeklyMenus };
    },
  };
}

function planMenu(day, row) {
  if (!day) return null;
  const weekday = new Date(day + 'T12:00:00Z').getUTCDay() || 7;
  const menu = row.weeklyMenus?.[weekday];
  return menu?.length ? { menu, source: weekdayNames[weekday - 1] + '菜单' } :
    { menu: row.menu || [], source: '默认菜单' };
}

function modalForm(ctx, title, buttonLabel, elements, submit) {
  const form = node('form', 'scheduled-editor');
  const status = node('p', 'form-error');
  status.setAttribute('role', 'alert');
  const save = node('button', 'btn btn-primary', buttonLabel);
  save.type = 'submit';
  form.append(...elements, status);
  const dialog = ctx.detail(title, form);
  dialog.classList.add('scheduled-dialog');
  form.append(node('footer', 'scheduled-form-actions', [btn(ctx, '返回', () => dialog.close()), save]));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (save.disabled || !form.reportValidity()) return;
    save.disabled = true;
    status.textContent = '';
    try {
      if (await submit()) dialog.close();
    } catch (error) {
      status.textContent = error.message || '未能保存定时工单。';
    } finally {
      save.disabled = false;
    }
  });
  return dialog;
}

function editor(ctx, data, preset = {}) {
  const isExisting = Boolean(preset.id);
  const title = input('text', preset.title, { required: true, maxLength: 100, placeholder: '例如 每日午餐' });
  const kind = choice(Object.entries(types), preset.kind || 'care');
  const frequency = choice([['daily', '每日'], ['weekly', '每周指定日期']], preset.weekdays?.length < 7 ? 'weekly' : 'daily');
  const weekdays = weekdaysPicker(preset.weekdays || allWeek);
  const time = input('time', preset.time || '08:00', { required: true });
  const start = input('date', preset.startDate || data.today, { required: true });
  const end = input('date', preset.endDate, { min: start.value });
  const meals = mealPicker(preset);
  const assignment = assigneePicker(data, preset);
  const audience = audiencePicker(data, preset.scope);
  const note = noteInput(preset.note, '填写护工需要核对的执行要求', 600);
  const days = () => frequency.value === 'daily' ? allWeek : weekdays.value();
  frequency.addEventListener('change', update);
  weekdays.element.addEventListener('change', update);
  kind.addEventListener('change', update);
  start.addEventListener('change', () => { end.min = start.value; });
  function update() {
    weekdays.element.hidden = frequency.value === 'daily';
    meals.update(kind.value === 'meal', days());
  }
  update();
  return modalForm(ctx, isExisting ? '编辑定时计划' : '新建定时计划', '核对计划', [
    node('div', 'scheduled-form-grid', [label('计划名称', title), label('工单类型', kind)]),
    node('section', 'scheduled-editor-section', [
      node('h3', '', '执行时间 · 上海时间'),
      node('div', 'scheduled-form-grid', [label('重复方式', frequency), label('每日派发时间', time),
        label('开始日期', start), label('结束日期（选填）', end)]),
      weekdays.element,
    ]),
    meals.element,
    audience.element,
    node('section', 'scheduled-editor-section', [node('h3', '', '执行分配'), assignment.element]),
    label('执行说明（选填）', note),
  ], () => {
    const activeDays = days();
    if (!activeDays.length) throw new Error('请至少选择一个执行日。');
    if (end.value && end.value < start.value) throw new Error('结束日期应在开始日期当日或之后。');
    const target = audience.value();
    const mealsConfig = kind.value === 'meal' ? meals.value() : { mealKind: '', menu: [], weeklyMenus: {} };
    const payload = {
      ...(isExisting ? { id: preset.id } : {}),
      title: title.value.trim(), kind: kind.value, time: time.value, weekdays: activeDays,
      startDate: start.value, endDate: end.value, scope: target.scope,
      ...assignment.value(), ...mealsConfig, note: note.value.trim(),
    };
    if (!payload.title) throw new Error('请填写计划名称。');
    return ctx.command('care.saveSchedule', payload, {
      title: '核对定时工单计划',
      target: payload.title,
      fields: [
        ['工单类型', types[payload.kind]], ['执行时间', recurrence(activeDays) + ' ' + payload.time],
        ['生效日期', payload.startDate + (payload.endDate ? ' 至 ' + payload.endDate : ' 起')],
        ['执行范围', target.display], ['分配给', assignment.label()],
        ...(payload.menu.length ? [['默认' + payload.mealKind + '菜单', payload.menu.join('、')]] : []),
        ...Object.entries(payload.weeklyMenus).map(([day, menu]) => [weekdayNames[day - 1] + '菜单', menu.join('、')]),
      ],
    });
  });
}

function editMenu(ctx, data, row) {
  const day = input('date', data.today, { required: true, min: data.today, max: row.endDate || '9999-12-31' });
  if (row.startDate > day.min) day.min = day.value = row.startDate;
  const control = noteInput('', '每行一道菜品，也可用顿号分隔', 1800);
  control.required = true;
  const source = node('p', 'fx-muted');
  source.setAttribute('role', 'status');
  function update() {
    const existing = data.menus.find(entry => entry.scheduleId === row.id && entry.day === day.value);
    const planned = existing ? { menu: existing.menu, source: '已保存的指定日期餐单' } : planMenu(day.value, row);
    control.value = (planned?.menu || []).join('\n');
    source.textContent = planned ? '当前取自' + planned.source + '。保存后仅在所选日期生效。' : '';
  }
  day.addEventListener('change', update);
  update();
  return modalForm(ctx, '设置指定日期餐单', '核对当天餐单', [
    node('p', 'fx-muted', row.title + ' · ' + row.mealKind),
    label('指定日期', day), source, label('当餐菜品', control),
  ], () => {
    const menu = menuItems(control.value);
    return ctx.command('care.scheduleMenu', { id: row.id, day: day.value, menu }, {
      title: '核对指定日期的餐单',
      target: row.title,
      fields: [['日期和餐次', day.value + ' · ' + row.mealKind], ['菜品', menu.join('、')]],
    });
  });
}

function scopeLabel(data, scope) {
  const byKind = {
    campus: [scope.campusIds, data.campuses, item => item.name],
    rooms: [scope.roomIds, data.rooms, item => item.label],
    residents: [scope.residentIds, data.roster, item => item.name + '（' + item.roomNumber + '）'],
  };
  if (scope.kind === 'all') return '全部分院';
  if (!(scope.kind in byKind)) return '待核对范围';
  const [ids, available, title] = byKind[scope.kind];
  const names = (ids || []).map(id => {
    const item = available.find(row => row.id === id);
    return item ? title(item) : '待核对';
  });
  return names.join('、') || '未设置范围';
}

function rulesTable(ctx, data) {
  return table(ctx, {
    title: '定时计划', rows: data.rules, empty: '当前还没有定时计划。',
    search: { placeholder: '搜索计划或执行对象', value: row => [row.title, scopeLabel(data, row.scope)] },
    filter: { label: '筛选工单类型', all: '全部类型', options: Object.values(types), value: row => types[row.kind] },
    cols: [
      { label: '计划', view: row => {
        const weeklyDays = Object.keys(row.weeklyMenus || {}).length;
        const subtitle = [types[row.kind], row.mealKind, weeklyDays ? '按星期安排' : '']
          .filter(Boolean).join(' · ');
        return named(row.title, subtitle);
      } },
      { label: '派发时间', view: row => named(recurrence(row.weekdays) + ' · ' + row.time,
        row.startDate + (row.endDate ? ' 至 ' + row.endDate : ' 起')) },
      { label: '执行范围 / 经办', view: row => node('div', 'scheduled-scope', named(scopeLabel(data, row.scope), row.assignee)) },
      { label: '状态', view: row => badge(ctx, row.enabled ? '已启用' : '已暂停', row.enabled ? 'green' : 'neutral') },
      { label: '操作', align: 'end', view: row => row.planId ? '在照护计划中调整' : data.canManage ? choose(
        btn(ctx, '编辑', () => editor(ctx, data, row)),
        row.kind === 'meal' ? btn(ctx, '当天餐单', () => editMenu(ctx, data, row)) : null,
        btn(ctx, row.enabled ? '暂停' : '启用', () => ctx.command('care.setScheduleEnabled',
          {id: row.id, enabled: !row.enabled}, {
            title: row.enabled ? '暂停定时派发' : '启用定时派发',
            target: row.title, fields: [['派发时间', recurrence(row.weekdays) + ' · ' + row.time]],
          })),
      ) : '—' },
    ],
  });
}

function runsTable(ctx, data) {
  const rules = new Map(data.rules.map(row => [row.id, row]));
  return table(ctx, {
    title: '今日派发', rows: data.runs.filter(run => run.day === data.today), empty: '今天还没有已派发的工单。',
    cols: [
      {label: '派发批次', view: row => named(row.title, types[rules.get(row.scheduleId)?.kind])},
      {label: '设定时间', view: row => row.time},
      {label: '实际派发', view: row => stamp(row.releasedAt)},
      {label: '范围人数', view: row => row.count + ' 人'},
      {label: '状态', view: row => badge(ctx, row.status === 'empty' ? '无待派对象' : '已派发',
        row.status === 'empty' ? 'neutral' : 'green')},
      { label: '操作', align: 'end', view: row => {
        if (row.status === 'empty') return '—';
        if (rules.get(row.scheduleId)?.kind === 'meal') {
          if (!hasGrant(ctx, 'care', 'clinical', 'residents', 'medical', 'care.groupConfirm')) return '—';
          return btn(ctx, '查看伙食批次', async () => {
            try {
              const { openScheduledMeal } = await import('./scheduled-meals.js');
              openScheduledMeal(ctx, { occurrenceId: row.id });
            } catch (error) {
              ctx.toast(error.message || '暂时无法打开伙食批次。');
            }
          });
        }
        return btn(ctx, '查看照护工单', () => ctx.go('care', 'tasks'));
      } },
    ],
  });
}

function builtinsTable(ctx, rows, related = false) {
  return table(ctx, {
    title: related ? '其他自动维护' : '系统内置周期任务',
    rows,
    empty: '当前权限范围内没有内置周期任务。',
    cols: [
      { label: '内置任务', view: row => named(row.title, row.description) },
      { label: '当前状态', view: row => row.status || '—' },
      { label: '下次运行', view: row => stamp(row.nextAt) },
      { label: '待办 / 生成量', view: row => row.count == null ? '—' : row.count + ' 项' },
      { label: '操作', align: 'end', view: row => row.route && ctx.available(row.route)
        ? btn(ctx, '进入相关页面', () => ctx.go(row.route, row.tab)) : '—' },
    ],
  });
}

const templates = [
  { kind: 'patrol', title: '早班查房', time: '08:00', note: '逐位观察长辈状态并记录变化。' },
  { kind: 'care', title: '下午饮水照护', time: '15:00', note: '根据长辈的照护安排提供饮水并记录。' },
  { kind: 'meal', title: '每日午餐', time: '12:30', mealKind: '午餐' },
];

function report(ctx, data) {
  const todayRuns = data.runs.filter(run => run.day === data.today);
  const active = data.rules.filter(rule => rule.enabled && rule.startDate <= data.today &&
    (!rule.endDate || rule.endDate >= data.today)).length;
  const builtins = data.builtins || [];
  const extra = data.maintenance || builtins.filter(row => row.kind === 'maintenance');
  const business = builtins.filter(row => row.kind !== 'maintenance');
  const summary = node('div', 'scheduled-summary', [
    ['生效计划', active], ['今日派发批次', todayRuns.filter(run => run.status === 'released').length],
    ['系统内置周期任务', business.length],
  ].map(([title, count]) => node('div', '', [node('small', '', title), node('strong', '', count)])));
  return [
    summary,
    data.canManage ? node('div', 'scheduled-templates', [
      node('span', '', '从模板新建'),
      ...templates.map(preset => btn(ctx, preset.title, () => editor(ctx, data, preset))),
    ]) : null,
    rulesTable(ctx, data),
    runsTable(ctx, data),
    builtinsTable(ctx, business),
    extra.length ? builtinsTable(ctx, extra, true) : null,
  ];
}

export async function openScheduledPlan(ctx) {
  const data = await ctx.get('/api/scheduled-work');
  if (!data.canManage) return ctx.toast('当前账号没有管理定时计划的权限');
  return editor(ctx, data);
}

export function scheduledWork(ctx) {
  const content = node('div', 'scheduled-content');
  const actions = node('div', 'scheduled-toolbar');
  const root = node('section', 'scheduled-work', [
    node('header', 'scheduled-heading', [
      node('div', '', [node('h2', '', '定时工单与批量派发'), node('p', 'fx-muted', '按上海时间管理自动派发及今日执行批次。')]),
      actions,
    ]),
    content,
  ]);
  let generation = 0;
  async function load() {
    const current = ++generation;
    content.replaceChildren(node('p', 'fx-muted', '正在读取定时工单…'));
    actions.replaceChildren();
    try {
      const data = await ctx.get('/api/scheduled-work');
      if (!root.isConnected || current !== generation) return;
      data.today ||= today(ctx);
      actions.replaceChildren(btn(ctx, '刷新', async () => {
        if (ctx.refreshWorkspace) await ctx.refreshWorkspace();
        else await load();
      }));
      if (ctx.available('reports')) actions.append(btn(ctx, '统计报送', () => ctx.go('reports')));
      if (data.canManage) actions.append(btn(ctx, '新建定时计划', () => editor(ctx, data), 'primary'));
      content.replaceChildren(...report(ctx, data).filter(Boolean));
    } catch (error) {
      if (root.isConnected && current === generation)
        content.replaceChildren(node('p', 'form-error', error.message || '无法读取定时工单。'), btn(ctx, '重试', load));
    }
  }
  load();
  return root;
}
