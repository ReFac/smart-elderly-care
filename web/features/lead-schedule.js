import { badge, btn, canAct, choose, field, link, memo, named, node, select, table, today } from './shared.js';

const kinds = { visit: '参观接待', callback: '电话回访' };
const clock = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
const campuses = ctx => ctx.state.leadCampuses || [];
const bookings = ctx => ctx.state.visitBookings || [];
const people = ctx => ctx.state.leadContacts || [];
const allowedCallback = row => !row.callbackExempt && !row.callbackStopped;
const personLabel = row => (row.name || '未留姓名') + ' · ' + row.phone;
const minutes = time => Number(time.slice(0, 2)) * 60 + Number(time.slice(3));
const dayQuery = (campusId, date) => '/api/leads/schedule?' + new URLSearchParams({ campusId, date });
const future = (date, start) => date + ' ' + start + ':00' >= clock.format(new Date());

function options(el, rows, previous = el.value, empty = '暂无可选项') {
  el.replaceChildren();
  for (const [value, label] of rows) el.add(new Option(label, value));
  if (!rows.length) el.add(new Option(empty, ''));
  if ([...el.options].some(o => o.value === String(previous))) el.value = previous;
}

function freeSeats(day, row, kind, start, end) {
  if (!row || !day || !future(day.date, start) || start >= end) return [];
  const covered = day.slots.filter(s => s.start >= start && s.start < end);
  if (!covered.length || covered.at(-1).end !== end) return [];
  const mine = day.bookings.filter(b => b.status === 'confirmed' && b.leadId === row.id);
  if (mine.some(b => b.kind !== kind && b.start < end && b.end > start)) return [];
  const current = mine.find(b => b.kind === kind);
  return Array.from({ length: day.capacity }, (_, i) => i + 1)
    .filter(seat => covered.every(s => !s.seats[seat - 1] || s.seats[seat - 1] === current?.id));
}

function cancelBooking(ctx, row, booking) {
  return ctx.dialog({
    title: '取消已确认的预约',
    description: personLabel(row) + ' · ' + kinds[booking.kind] + ' · ' + booking.date + ' ' + booking.start + '–' + booking.end,
    fields: [memo('feedback', '取消原因', true, { maxLength: 1000 })], submitLabel: '核对取消',
    onSubmit: ({ feedback }) => ctx.command('leads.cancel', { leadId: row.id, kind: booking.kind, feedback }, {
      title: '取消已确认的预约', target: row.name || row.phone, confirmLabel: '确认取消预约',
      fields: [['取消的时段', booking.date + ' ' + booking.start + '–' + booking.end], ['释放席位', String(booking.seat)], ['取消原因', feedback]],
    }),
  });
}

export function bookingForm(ctx, person, preset = {}) {
  if (!canAct(ctx, 'leads.book')) return ctx.toast('当前账号没有排期权限');
  const campusId = person?.campusId || preset.campusId;
  const available = people(ctx).filter(r => r.campusId === campusId && r.status !== '已归档');
  if (!available.length) return ctx.toast('请先登记这位客户，再电话确认预约时段。');
  const title = preset.existing ? '电话确认改期' : '电话确认排期';
  const dialog = ctx.dialog({
    title,
    fields: [
      select('leadId', '客户', [{ value: '', label: '选择要安排的客户' }, ...available.map(r => ({ value: r.id, label: personLabel(r) }))], { value: person?.id || '' }),
      select('kind', '安排事项', []),
      field('date', '日期（北京时间）', { type: 'date', value: preset.date || today(ctx), min: today(ctx) }),
      select('start', '开始时间', []),
      select('end', '结束时间', []),
      select('seat', '接待席位', [], { required: false }),
      memo('feedback', '电话确认备注', false, { maxLength: 1000 }),
    ],
    submitLabel: '核对预约',
    onSubmit: values => {
      const chosen = available.find(r => r.id === values.leadId);
      if (!chosen || !day || day.date !== values.date || !checked.checked) throw new Error('请先电话确认日期和时段。');
      const seats = freeSeats(day, chosen, values.kind, values.start, values.end);
      if (!seats.length || (values.seat && !seats.includes(Number(values.seat)))) throw new Error('所选时段没有连续可用的席位。');
      const payload = { ...values, phoneConfirmed: true };
      if (values.seat) payload.seat = Number(values.seat);
      else delete payload.seat;
      return ctx.command('leads.book', payload, {
        title, target: personLabel(chosen), confirmLabel: '确认占用时段',
        fields: [['事项', kinds[values.kind]], ['已电话确认', values.date + ' ' + values.start + '–' + values.end],
          ['接待席位', values.seat ? '席位 ' + values.seat : '自动分配连续可用席位']],
      });
    },
  });
  const form = dialog.querySelector('form');
  const controls = form.elements;
  const checked = node('input');
  checked.type = 'checkbox';
  checked.required = true;
  const hint = node('p', 'lead-book-hint');
  hint.setAttribute('aria-live', 'polite');
  const confirmPhone = node('label', 'lead-confirm-phone', [checked, '我已通过电话与客户确认以上日期、时段和事项']);
  form.querySelector('.form-error').before(hint, confirmPhone);
  let day, requestId = 0, initial = true;
  const chosen = () => available.find(r => r.id === controls.leadId.value);
  function update() {
    const row = chosen();
    const choices = Object.entries(kinds).filter(([key]) => key !== 'callback' || (row && allowedCallback(row)));
    options(controls.kind, choices, initial ? preset.kind || 'visit' : controls.kind.value);
    const kind = controls.kind.value;
    const starts = day?.slots.filter(s => freeSeats(day, row, kind, s.start, s.end).length) || [];
    options(controls.start, starts.map(s => [s.start, s.start]), initial ? preset.start : controls.start.value,
      row ? '当天无可用时段' : '请先选择客户');
    const start = controls.start.value;
    const ends = start ? day.slots.filter(s => s.end > start && freeSeats(day, row, kind, start, s.end).length) : [];
    options(controls.end, ends.map(s => [s.end, s.end + '（' + (minutes(s.end) - minutes(start)) + ' 分钟）']),
      initial ? preset.end : controls.end.value);
    const seats = start ? freeSeats(day, row, kind, start, controls.end.value) : [];
    options(controls.seat, seats.length ? [['', '自动分配'], ...seats.map(s => [s, '席位 ' + s])] : [],
      initial ? preset.seat : controls.seat.value);
    const current = row && bookings(ctx).find(b => b.leadId === row.id && b.kind === kind && b.status === 'confirmed');
    hint.textContent = current
      ? '该客户已有' + kinds[kind] + '预约：' + current.date + ' ' + current.start + '–' + current.end + '。新排期生效时会释放原时段。'
      : '每天按半小时排班，一次预约全程使用同一个席位。';
    form.querySelector('[type=submit]').disabled = !seats.length;
    checked.checked = false;
    if (row && day) initial = false;
  }
  async function load() {
    const id = ++requestId;
    day = null;
    update();
    if (!controls.date.value) return;
    hint.textContent = '正在读取当天的可用席位…';
    try {
      const data = await ctx.get(dayQuery(campusId, controls.date.value));
      if (requestId !== id || !dialog.open) return;
      day = data;
      update();
    } catch (e) {
      if (id === requestId) hint.textContent = e.message || '读取排班失败，请重新选择日期。';
    }
  }
  for (const control of [controls.leadId, controls.kind, controls.start, controls.end, controls.seat]) control.addEventListener('change', update);
  controls.date.addEventListener('change', load);
  load();
  return dialog;
}

function configure(ctx, data) {
  return ctx.dialog({
    title: '设置接待并行席位',
    description: '每个席位同时接待一位客户。设置对该分院的排班生效。',
    fields: [select('capacity', '同时可用的席位数', Array.from({ length: 32 }, (_, i) => ({ value: i + 1, label: (i + 1) + ' 个席位' })), { value: data.capacity })],
    onSubmit: ({ capacity }) => ctx.command('leads.capacity', { campusId: data.campusId, capacity: Number(capacity) }, {
      title: '调整并行席位', target: campuses(ctx).find(c => c.id === data.campusId)?.name,
      fields: [['当前席位数', String(data.capacity)], ['调整后席位数', capacity]],
    }),
  });
}

function dayGrid(ctx, data, fullDay, openPerson) {
  const grid = node('table', 'lead-grid');
  grid.setAttribute('aria-label', data.date + ' 接待席位');
  const leads = new Map(people(ctx).map(r => [r.id, r]));
  const indexed = new Map(data.bookings.map(b => [b.id, b]));
  const count = data.displayCapacity || data.capacity;
  const head = node('tr', '', [node('th', 'lead-clock-col', '时段')]);
  for (let i = 1; i <= count; i++) head.append(node('th', '', '席位 ' + i));
  grid.append(node('thead', '', head));
  const body = node('tbody');
  const slots = data.slots.filter(s => fullDay || (s.start >= '08:00' && s.start < '18:00') || s.seats.some(Boolean));
  for (const [slotIndex, s] of slots.entries()) {
    const time = node('th', 'lead-clock-col', s.start + '–' + s.end);
    time.scope = 'row';
    const tr = node('tr', '', time);
    for (let i = 0; i < count; i++) {
      const b = indexed.get(s.seats[i]);
      const row = b && leads.get(b.leadId);
      const cell = node('td');
      if (b) {
        if (slots[slotIndex - 1]?.seats[i] === b.id) continue;
        let span = 1;
        while (slots[slotIndex + span]?.seats[i] === b.id) span++;
        cell.rowSpan = span;
        cell.className = 'lead-occupied';
        const content = node('button', 'lead-booking lead-booking-' + b.kind, [
          node('strong', '', row?.name || row?.phone || '已预约'),
          node('span', '', kinds[b.kind] + ' · ' + b.start + '–' + b.end),
        ]);
        content.type = 'button';
        content.addEventListener('click', () => {
          if (!row) return;
          const panel = node('div', 'lead-booking-detail', [
            node('p', '', personLabel(row)),
            node('p', '', b.date + '　' + b.start + '–' + b.end + '　席位 ' + b.seat),
            badge(ctx, { completed: '已完成', rescheduled: '已改期', cancelled: '已取消', confirmed: '已电话确认' }[b.status], b.status === 'completed' ? 'green' : 'blue'),
            choose(link(ctx, '查看客户记录', () => openPerson(row)),
              b.status === 'confirmed' && canAct(ctx, 'leads.book') ? link(ctx, '改期', () => bookingForm(ctx, row, { ...b, existing: true })) : null,
              b.status === 'confirmed' && canAct(ctx, 'leads.cancel') ? link(ctx, '取消预约', () => cancelBooking(ctx, row, b)) : null),
          ]);
          ctx.detail(kinds[b.kind] + '安排', panel);
        });
        cell.append(content);
      } else if (s.bookable && i < data.capacity && canAct(ctx, 'leads.book')) {
        const book = node('button', 'lead-slot', '可预约');
        book.type = 'button';
        book.setAttribute('aria-label', s.start + '–' + s.end + ' 席位 ' + (i + 1) + ' 可预约');
        book.onclick = () => bookingForm(ctx, null, { campusId: data.campusId, date: data.date, start: s.start, end: s.end, seat: i + 1 });
        cell.append(book);
      } else cell.append(node('span', 'fx-muted', i >= data.capacity ? '已停用' : future(data.date, s.start) ? '空闲' : '—'));
      tr.append(cell);
    }
    body.append(tr);
  }
  grid.append(body);
  const scroll = node('div', 'lead-grid-scroll', grid);
  const first = body.querySelector('.lead-occupied');
  if (first) requestAnimationFrame(() => {
    const top = first.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    scroll.scrollTop = Math.max(0, top - scroll.clientHeight / 3);
  });
  return scroll;
}

function shiftDay(date, delta) {
  const d = new Date(date + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

export function schedulePage(ctx, incomingList, openPerson) {
  const branches = campuses(ctx);
  if (!branches.length) return ctx.ui.empty('当前账号没有可查看的分院接待时间表。');
  const memory=ctx.workspaceState || {};
  const saved = memory.receptionDay ||= {layout:'grid'};
  const date = node('input', 'fx-input');
  date.type = 'date';
  date.setAttribute('aria-label', '排班日期');
  date.value = saved.date || today(ctx);
  const branch = node('select', 'fx-input');
  branch.setAttribute('aria-label', '查看分院');
  options(branch, branches.map(c => [c.id, c.name]), saved.campusId);
  const all = node('input');
  all.type = 'checkbox';
  all.checked = Boolean(saved.fullDay);
  const allHours = node('label', 'lead-hours', [all, '显示全天']);
  const info = node('div', 'lead-day-info');
  const sheet = node('div');
  const calls = node('div');
  const modes = choose(); modes.classList.add('desk-view-switch');
  for(const [id,title] of [['grid','按席位排班'],['ledger','预约台账']]){
    const button=btn(ctx,title,()=>{saved.layout=id;draw();},'ghost');button.dataset.layout=id;modes.append(button);
  }
  const book = canAct(ctx,'leads.book') ? btn(ctx,'电话确认排期',()=>bookingForm(ctx,null,{campusId:branch.value,date:date.value}),'primary') : null;
  const panel = node('section', 'fx-panel lead-day', [
    node('header', 'fx-toolbar', [
      node('h2', '', '分院接待排班'),choose(book,modes),
    ]),
    node('div','agenda-filter',[node('label','agenda-field',['接待分院',branch]),
      node('label','agenda-field',['接待日期',date]),choose(btn(ctx,'前一天',()=>move(-1)),btn(ctx,'后一天',()=>move(1)),
      btn(ctx,'今天',()=>{date.value=today(ctx);load();}))]),
    info, sheet,
  ]);
  const wrap = node('div', 'lead-schedule', [panel, calls]);
  let request = 0, data;
  function move(delta) {
    date.value = shiftDay(date.value || today(ctx), delta);
    load();
  }
  function draw() {
    Object.assign(saved,{date:date.value,campusId:branch.value,fullDay:all.checked});
    if (!data) return;
    const live = data.bookings.filter(b => b.status === 'confirmed').length;
    info.replaceChildren(
      node('span', '', data.capacity + ' 个并行席位 · 当天 ' + live + ' 项已确认安排'),
      link(ctx, '查看当日来电', () => calls.scrollIntoView({ block: 'start' })), ...(saved.layout==='grid'?[allHours]:[]),
    );
    if (canAct(ctx, 'leads.capacity')) info.append(link(ctx, '设置并行席位', () => configure(ctx, data)));
    for(const button of modes.children)button.setAttribute('aria-pressed',String(button.dataset.layout===saved.layout));
    if (saved.layout !== 'ledger') {sheet.replaceChildren(dayGrid(ctx, data, all.checked, openPerson));return;}
    const byId=new Map(people(ctx).map(r=>[r.id,r]));
    const rows=[...data.bookings].sort((a,b)=>a.start.localeCompare(b.start)||a.seat-b.seat);
    const statuses={confirmed:'已电话确认',completed:'已完成',cancelled:'已取消',rescheduled:'已改期'};
    sheet.replaceChildren(table(ctx,{title:'当日预约台账',rows,empty:'本日尚无预约记录。',
      cols:[
        {label:'预约时段',view:r=>r.start+'–'+r.end},{label:'接待席位',view:r=>'席位 '+r.seat},
        {label:'客户',view:r=>{const person=byId.get(r.leadId);return person?named(person.name||'未留姓名',person.phone):'资料归档';}},
        {label:'事项',view:r=>kinds[r.kind]}, {label:'状态',view:r=>badge(ctx,statuses[r.status] || r.status)},
        {label:'操作',view:r=>{const p=byId.get(r.leadId);return p?choose(link(ctx,'联系记录',()=>openPerson(p)),
          r.status==='confirmed' && canAct(ctx,'leads.book') ? link(ctx,'改期',()=>bookingForm(ctx,p,{...r,existing:true})) : null,
          r.status==='confirmed' && canAct(ctx,'leads.cancel') ? link(ctx,'取消预约',()=>cancelBooking(ctx,p,r)) : null):'—';}},
      ]}));
  }
  async function load() {
    const version = ++request;
    data = null;
    info.replaceChildren();
    calls.replaceChildren();
    if (!date.value) { sheet.replaceChildren(node('p', 'lead-day-message', '选择日期后查看排班。')); return; }
    sheet.replaceChildren(node('p', 'lead-day-message', '正在读取排班…'));
    calls.replaceChildren(incomingList(ctx, branch.value, date.value));
    try {
      const day = await ctx.get(dayQuery(branch.value, date.value));
      if (request !== version) return;
      data = day;
      draw();
    } catch (e) {
      if (version === request) sheet.replaceChildren(node('p', 'lead-day-message', [e.message, ' ', link(ctx, '重新读取', load)]));
    }
  }
  for (const control of [branch, date]) control.addEventListener('change', load);
  all.addEventListener('change', draw);
  load();
  return wrap;
}
