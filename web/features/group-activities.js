import { badge, btn, canAct, named, node, today } from './shared.js';

const kinds = ['早餐', '午餐', '晚餐', '集体活动'];
let returnScope;
const isMeal = kind => kind !== '集体活动';
const label = (title, control) => node('label', 'field', [node('span', '', title), control]);

function timeControl(name, value) {
  const input = node('input');
  input.type = 'time';
  input.name = name;
  input.required = true;
  input.value = value;
  return input;
}

function attendance(people) {
  const container = node('section', 'group-attendance');
  const count = node('strong');
  const all = node('input');
  all.type = 'checkbox';
  all.checked = true;
  const choices = [];
  const list = node('div', 'group-person-list');
  const heading = node('div', 'group-attendance-heading', [
    node('h3', '', '参加名单'), count,
  ]);
  function sync() {
    const total = choices.filter(r => r.check.checked).length;
    all.checked = total > 0 && total === choices.length;
    all.indeterminate = total > 0 && total < choices.length;
    count.textContent = '已选 ' + total + ' / ' + choices.length + ' 人';
    choices.forEach(r => {
      r.note.disabled = !r.check.checked;
      if (!r.check.checked) r.entry.open = false;
      r.entry.hidden = !r.check.checked || !showMeals;
    });
  }
  let showMeals = true;
  for (const person of people) {
    const check = node('input');
    check.type = 'checkbox';
    check.checked = true;
    const title = person.name + '（' + person.roomNumber + '）';
    const note = node('input');
    note.maxLength = 300;
    note.type = 'text';
    note.placeholder = '例如：吃了半碗粥、一块豆腐';
    note.setAttribute('aria-label', title + '的实际进食');
    const entry = node('details', 'group-intake-note', [node('summary', '', '记实际进食'), note]);
    const personLine = node('div', 'group-person', [
      node('label', 'group-person-check', [check, named(title, person.bedLabel)]), entry,
    ]);
    list.append(personLine);
    choices.push({ check, note, person, entry });
    check.onchange = sync;
  }
  all.onchange = () => { choices.forEach(r => { r.check.checked = all.checked; }); sync(); };
  container.append(heading, node('p', 'fx-muted', '名单默认全选。请取消未参加的人，可逐人补记实际吃了什么。'),
    node('label', 'group-select-all', [all, '全选参加名单']), list);
  sync();
  return {
    element: container,
    meals(visible) {
      showMeals = visible;
      choices.forEach(r => { r.entry.open = false; });
      container.querySelector('p').textContent = visible
        ? '名单默认全选。请取消未参加的人，可逐人补记实际吃了什么。'
        : '名单默认全选。请取消未参加的人。';
      sync();
    },
    selected: () => choices.filter(r => r.check.checked).map(r => r.person.id),
    intake: () => Object.fromEntries(choices.filter(r => showMeals && r.check.checked && r.note.value.trim())
      .map(r => [r.person.id, r.note.value.trim()])),
  };
}

function activityEditor(ctx, roster, mode, pending) {
  const proposing = mode === 'propose';
  const source = pending || roster;
  const campus = roster.campuses.find(c => c.id === source.campusId)?.name || '';
  const room = roster.rooms.find(r => r.id === source.roomId)?.label;
  const area = [campus, room].filter(Boolean).join(' · ');
  const rows = source.residents;
  const requestId = crypto.randomUUID();
  const form = node('form', 'group-editor');
  const kind = node('select');
  kinds.forEach(k => kind.add(new Option(k, k)));
  const day = node('input');
  day.type = 'date';
  day.value = source.day;
  day.required = true;
  day.readOnly = true;
  const start = timeControl('startsAt', pending?.startsAt || '');
  const end = timeControl('endsAt', pending?.endsAt || '');
  const details = node('textarea');
  details.required = true;
  details.maxLength = 500;
  details.rows = 2;
  const detailLabel = label('当餐提供的菜品', details);
  const participants = proposing ? null : attendance(rows);
  const controls = node('div', 'group-form-grid', [
    label('活动类型', kind), label('活动日期', day),
    label('开始时间', start), label('结束时间', end), detailLabel,
  ]);
  const updateKind = () => {
    const meal = isMeal(kind.value);
    detailLabel.firstChild.textContent = meal ? '当餐提供的菜品' : '活动名称和内容';
    details.placeholder = meal ? '例如：小米粥、鸡蛋、蒸南瓜' : '例如：花园散步';
    participants?.meals(meal);
  };
  if (pending) {
    kind.value = pending.kind;
    details.value = pending.details;
    for (const control of [kind, day, start, end, details]) control.disabled = true;
  }
  kind.onchange = updateKind;
  updateKind();
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const submit = node('button', 'btn btn-primary', proposing ? '提交给负责人' : '核对并签认');
  submit.type = 'submit';
  form.append(node('p', 'group-area', [ctx.ui.icon('location', 16), area]), controls);
  if (participants) form.append(participants.element);
  else form.append(node('p', 'fx-muted', '本次登记 ' + rows.length + ' 位候选长者。活动结束后，负责人将收到待确认提醒。'));
  const dialog = ctx.detail(proposing ? '登记集体活动' : '确认活动参加情况', form);
  dialog.classList.add('group-dialog');
  form.append(error, node('footer', 'group-form-actions', [btn(ctx, '返回', () => dialog.close()), submit]));
  form.onsubmit = async event => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    if (start.value >= end.value) { error.textContent = '结束时间须晚于开始时间。'; return; }
    const base = { requestId, campusId: source.campusId, roomId: source.roomId || '', kind: kind.value,
      day: day.value, startsAt: start.value, endsAt: end.value, details: details.value.trim() };
    const ids = participants?.selected() || [];
    const selection = participants ? { residentIds: ids, mealIntake: participants.intake(), confirmed: true } : {};
    const payload = pending ? { eventId: pending.id, ...selection } : { ...base, ...selection };
    const fields = [['时间', day.value + ' ' + start.value + '–' + end.value], [isMeal(kind.value) ? '餐单' : '活动内容', details.value]];
    if (participants) fields.push(['参加', ids.length + ' 人'], ['未参加', (rows.length - ids.length) + ' 人']);
    submit.disabled = true;
    try {
      returnScope = { user: ctx.state.user.id, campus: roster.campusId, room: roster.roomId, day: roster.day };
      const saved = await ctx.command(proposing ? 'care.proposeGroupActivity' : 'care.confirmGroupActivity', payload, {
        title: proposing ? '提交活动登记' : '确认参加名单并写入个人时间线', target: area + ' · ' + kind.value, fields,
        confirmLabel: proposing ? '确认提交' : '确认签认', quiet: true, expectedRevision: roster.revision,
      });
      if (saved) ctx.toast(proposing ? '活动已登记，等待结束后确认。' : '已签认，参加者的生活时间线已更新。');
    } finally { submit.disabled = false; returnScope = null; }
  };
}

export function groupActivities(ctx) {
  const box = node('section', 'fx-panel group-desk');
  const campus = node('select'), room = node('select'), day = node('input');
  day.type = 'date';
  const initial = returnScope?.user === ctx.state.user.id ? returnScope : {};
  day.max = today(ctx);
  day.value = initial.day || day.max;
  const actions = node('div', 'fx-actions');
  const content = node('div', 'group-sections');
  box.append(node('header', 'group-heading', [node('h2', '', '用餐与集体活动'), actions]),
    node('div', 'group-scope', [label('分院', campus), label('房间', room), label('查看日期', day)]), content);
  let serial = 0;
  const sign = canAct(ctx, 'care.confirmGroupActivity');
  async function load(campusId = '', roomId = '') {
    const current = ++serial;
    actions.replaceChildren();
    content.replaceChildren(node('p', 'fx-muted', '正在加载活动…'));
    try {
      const query = new URLSearchParams({ campusId, roomId, day: day.value || today(ctx) });
      const roster = await ctx.get('/api/daily-life/roster?' + query);
      if (current !== serial) return;
      campus.replaceChildren(...roster.campuses.map(c => new Option(c.name, c.id)));
      room.replaceChildren(new Option('全部获授权房间', ''), ...roster.rooms.map(r => new Option(r.label, r.id)));
      campus.value = roster.campusId;
      room.value = roster.roomId;
      if (canAct(ctx, 'care.proposeGroupActivity')) actions.append(btn(ctx, '登记活动', () => activityEditor(ctx, roster, 'propose'), 'primary'));
      if (sign) actions.append(btn(ctx, '直接确认已结束活动', () => activityEditor(ctx, roster, 'confirm')));
      for (const b of actions.children) b.disabled = !roster.residents.length;
      const pending = roster.pending.map(item => node('div', 'group-event', [
        named(item.kind + ' · ' + item.details, item.day + '　' + item.startsAt + '–' + item.endsAt + '　·　' + item.residents.length + ' 人待核对'),
        badge(ctx, item.ready ? '待确认' : '尚未结束', item.ready ? 'gold' : 'blue'),
        sign && item.ready ? btn(ctx, '核对名单', () => activityEditor(ctx, roster, 'confirm', item)) : null,
      ]));
      const completed = roster.receipts.map(item => node('div', 'group-event', [
        named(item.kind + ' · ' + item.details, item.startsAt + '–' + item.endsAt),
        node('span', 'group-count', item.attendedCount + ' 人参加 · ' + item.excludedCount + ' 人未参加'),
      ]));
      content.replaceChildren(node('section', '', [node('h3', '', '待确认的活动'),
        ...(pending.length ? pending : [node('p', 'fx-muted', '当前范围没有待确认的活动。')])]),
      node('section', '', [node('h3', '', '当日已确认'),
        ...(completed.length ? completed : [node('p', 'fx-muted', '所选日期还没有已确认的活动。')])]));
    } catch (e) {
      if (current === serial) content.replaceChildren(node('p', 'form-error', e.message), btn(ctx, '重试', () => load(campusId, roomId)));
    }
  }
  campus.onchange = () => load(campus.value);
  room.onchange = day.onchange = () => load(campus.value, room.value);
  load(initial.campus, initial.room);
  return box;
}
