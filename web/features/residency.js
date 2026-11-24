import {
  hasGrant,
  canAct,
  node,
  add,
  page,
  table,
  kpis,
  field,
  select,
  options,
  memo,
  bedName,
  active,
  byRecent,
  choose,
  btn,
  link,
  named,
  badge,
  runForm,
  facts,
  recordIdentity,
  disclosure,
  section,
  records,
  today,
  nextDay,
  money
} from './shared.js';
import { openDossier } from './dossier.js';

import { bedCard, familyPreview, bedside } from './bedcard.js';

export const levels = ['自理', '半失能', '失能'];

const bedOptions = (ctx) =>
  ctx.state.beds
    .filter((row) => row.status === '空闲')
    .map((row) => ({
      value: row.id,
      label: row.ward + ' · ' + row.label
    }));

export function admit(ctx, defaults = {}) {
  runForm(ctx, {
    title: '办理入住',
    action: 'care.admit',
    submitLabel: '确认入住',
    defaults,
    fields: [
      field('name', '长者姓名'),
      select('bedId', '分配床位', bedOptions(ctx)),
      select('level', '照护等级', options(levels)),
      field('age', '年龄', {
        type: 'number',
        min: 0,
        max: 125,
        required: false
      }),
      select('gender', '性别', options(['未登记', '女', '男'])),
      field('endDate', '合同到期日', {
        type: 'date',
        min: today(ctx),
        required: false
      }),
      field('contact', '联系人或电话', {
        required: false
      }),
      field('allergies', '过敏信息', {
        required: false
      }),
      field('risk', '重点关注事项', {
        required: false
      })
    ],
    map: (values) =>
      defaults.inquiryId
        ? {
            ...values,
            inquiryId: defaults.inquiryId
          }
        : values
  });
}

function transfer(ctx, row) {
  runForm(ctx, {
    title: '办理转床',
    action: 'care.transfer',
    description: row.name + ' · 当前床位 ' + bedName(ctx, row.bedId),
    fields: [select('bedId', '转入床位', bedOptions(ctx))],
    map: (v) => ({
      ...v,
      residentId: row.id
    }),
    submitLabel: '确认转床'
  });
}

function discharge(ctx, row) {
  runForm(ctx, {
    title: '办理退住',
    action: 'care.discharge',
    description: '确认后将释放 ' + row.name + ' 的床位，保留历史档案。',
    fields: [memo('note', '退住小结', true)],
    map: (v) => ({
      ...v,
      residentId: row.id
    }),
    submitLabel: '确认退住'
  });
}

function archive(ctx, row) {
  runForm(ctx, {
    title: '复核档案摘要',
    action: 'care.archive',
    defaults: row,
    fields: [
      memo('summary', '档案摘要', true),
      field('allergies', '过敏信息', {
        required: false
      }),
      field('risk', '重点关注事项', {
        required: false
      })
    ],
    map: (v) => ({
      allergies: '',
      risk: '',
      ...v,
      residentId: row.id
    })
  });
}

function leave(ctx, row) {
  runForm(ctx, {
    title: '登记请假',
    action: 'care.leave',
    fields: [
      field('startDate', '开始日期', {
        type: 'date',
        value: today(ctx)
      }),
      field('endDate', '结束日期', {
        type: 'date',
        value: today(ctx)
      }),
      memo('reason', '请假事由')
    ],
    map: (v) => ({
      ...v,
      residentId: row.id
    })
  });
}

function renew(ctx, row) {
  runForm(ctx, {
    title: '续住登记',
    action: 'care.renew',
    fields: [
      field('endDate', '新的合同到期日', {
        type: 'date',
        min: nextDay(row.endDate > today(ctx) ? row.endDate : today(ctx)),
        value: nextDay(row.endDate > today(ctx) ? row.endDate : today(ctx))
      })
    ],
    map: (v) => ({
      ...v,
      residentId: row.id
    })
  });
}

export function profile(ctx, row) {
  const { state } = ctx;
  const own = (name) => {
    const entries = (state[name] || []).filter((item) => item.residentId === row.id);
    return name === 'bills' ? entries : byRecent(entries);
  };
  const summary = node('div', 'fx-profile fx-admission-profile');
  summary.append(recordIdentity(ctx, row, row.level));
  add(
    summary,
    facts([
      [
        '年龄 / 性别',
        [row.age == null ? '' : row.age + ' 岁', row.gender].filter(Boolean).join(' · ')
      ],
      ['入住日期', row.admittedAt],
      ['床位', bedName(ctx, row.bedId)],
      ['合同到期', row.endDate],
      ...('contact' in row ? [['联系方式', row.contact]] : [])
    ])
  );
  if (row.allergies || row.risk)
    add(
      summary,
      node('div', 'fx-attention', [
        row.allergies ? named('过敏提醒', row.allergies) : null,
        row.risk ? named('重点关注', row.risk) : null
      ])
    );
  if (row.summary) add(summary, section('档案摘要', node('p', '', row.summary)));
  const shortcuts = choose();
  if (state.user.routes.includes('dossier'))
    shortcuts.append(btn(ctx, '打开详细档案', () => openDossier(ctx, row), 'primary'));
  if (hasGrant(ctx, 'care', 'clinical'))
    shortcuts.append(btn(ctx, '服务记录预览', () => familyPreview(ctx, row)));
  if (shortcuts.childElementCount) summary.append(shortcuts);
  if (row.status === '在住') {
    const actions = choose();
    if (hasGrant(ctx, 'intake', 'care'))
      actions.append(btn(ctx, '床头卡', () => bedCard(ctx, row)));
    if (canAct(ctx, 'care.archive')) actions.append(btn(ctx, '复核摘要', () => archive(ctx, row)));
    if (canAct(ctx, 'care.leave')) actions.append(btn(ctx, '登记请假', () => leave(ctx, row)));
    if (canAct(ctx, 'care.renew')) actions.append(btn(ctx, '续住', () => renew(ctx, row)));
    if (canAct(ctx, 'care.transfer')) actions.append(btn(ctx, '转床', () => transfer(ctx, row)));
    if (canAct(ctx, 'care.discharge')) actions.append(btn(ctx, '退住', () => discharge(ctx, row)));
    if (actions.childElementCount) summary.append(section('档案操作', actions));
  }
  const block = (title, key, grants, describe) => {
    if (!hasGrant(ctx, ...grants)) return null;
    const entries = own(key);
    return disclosure(title, records(entries, describe), entries.length);
  };
  const history = node('div', 'fx-history-grid');
  add(
    history,
    block('床位变动', 'bedMoves', ['intake', 'care'], (m) =>
      named(
        m.kind + ' · ' + (m.bedId ? bedName(ctx, m.bedId) : bedName(ctx, m.beforeBedId)),
        m.date
      )
    ),
    block('评估与复评', 'assessments', ['care'], (a) =>
      named(a.level + ' · ' + a.note, a.date + ' 评估 · ' + a.reviewDate + ' 复评')
    ),
    block('照护服务', 'tasks', ['care'], (t) =>
      named(t.title + ' · ' + t.status, t.date + ' ' + t.time + ' · ' + t.assignee)
    ),
    block('用药记录', 'medications', ['clinical'], (m) =>
      named(m.name + ' · ' + m.status, m.instruction)
    ),
    block('健康体征', 'vitals', ['clinical'], (v) =>
      named(v.metric + ' ' + v.value + ' ' + (v.unit || ''), v.date + ' · ' + v.status)
    ),
    block('费用明细', 'bills', ['finance'], (b) =>
      named(b.month + ' · ' + money(b.amount), b.status + ' · 待缴 ' + money(b.balance))
    ),
    block('请假记录', 'leaves', ['finance', 'intake'], (l) =>
      named(l.startDate + ' 至 ' + l.endDate, l.reason)
    ),
    block('历史档案', 'archives', ['clinical', 'medical'], (a) =>
      named(a.summary || a.note || '档案更新', a.date)
    )
  );
  if (history.childElementCount) summary.append(history);
  ctx.detail('长者档案', summary);
}

export function inquiryForm(ctx) {
  runForm(ctx, {
    title: '登记入住意向',
    action: 'care.inquire',
    fields: [
      field('name', '长者姓名'),
      field('contact', '联系人或电话', {
        required: false
      }),
      memo('note', '入住需求')
    ]
  });
}

export function intake(ctx) {
  const list = byRecent(ctx.state.inquiries);
  return page(
    ctx,
    '接待入住',
    '登记来访意向，跟进入住需求并分配床位。',
    choose(
      btn(ctx, '直接办理入住', () => admit(ctx)),
      btn(ctx, '登记入住意向', () => inquiryForm(ctx), 'primary')
    ),
    kpis([
      ['待跟进', list.filter((r) => r.status === '待跟进').length],
      ['已转入住', list.filter((r) => r.status === '已入住').length],
      ['可分配床位', bedOptions(ctx).length]
    ]),
    table(ctx, {
      title: '接待记录',
      rows: list,
      search: {
        placeholder: '搜索姓名或联系人',
        value: (r) => r.name + ' ' + r.contact
      },
      filter: {
        value: (r) => r.status
      },
      cols: [
        {
          label: '来访长者',
          view: (r) => named(r.name, r.contact)
        },
        {
          label: '登记日期',
          view: (r) => r.date
        },
        {
          label: '入住需求',
          view: (r) => r.note || '—'
        },
        {
          label: '跟进状态',
          view: (r) => badge(ctx, r.status)
        },
        {
          label: '操作',
          align: 'end',
          view: (r) =>
            r.status === '待跟进'
              ? link(ctx, '办理入住', () =>
                  admit(ctx, {
                    inquiryId: r.id,
                    name: r.name,
                    contact: r.contact
                  })
                )
              : '—'
        }
      ]
    })
  );
}

export function residents(ctx) {
  return page(
    ctx,
    '长者档案',
    '按档案号或姓名查找长者。',
    canAct(ctx, 'care.admit') ? btn(ctx, '办理入住', () => admit(ctx), 'primary') : null,
    table(ctx, {
      title: '长者名册',
      rows: byRecent(ctx.state.residents),
      search: {
        placeholder: '搜索姓名或档案号',
        value: (r) => r.name + ' ' + r.id
      },
      filter: {
        value: (r) => r.status
      },
      cols: [
        {
          label: '长者',
          view: (r) =>
            node('div', 'fx-person-cell', [
              node('span', 'fx-person-mark', ctx.ui.icon('people', 16)),
              named(r.name, r.id)
            ])
        },
        {
          label: '床位',
          view: (r) => bedName(ctx, r.bedId)
        },
        {
          label: '照护等级',
          view: (r) => r.level
        },
        {
          label: '入住日期',
          view: (r) => r.admittedAt
        },
        {
          label: '状态',
          view: (r) => badge(ctx, r.status)
        },
        {
          label: '操作',
          align: 'end',
          view: (r) => link(ctx, '查看档案', () => profile(ctx, r))
        }
      ]
    })
  );
}

export function beds(ctx) {
  const all = ctx.state.beds;
  const free = bedOptions(ctx);
  const wards = [...new Set(all.map((b) => b.ward))];
  const filter = node('select', 'fx-input');
  filter.setAttribute('aria-label', '筛选院区');
  for (const ward of ['', ...wards]) {
    const opt = node('option', '', ward || '全部区域');
    opt.value = ward;
    filter.append(opt);
  }
  const grid = node('div', 'fx-wards');
  const filterBar = node('div', 'fx-bed-filters');
  filterBar.setAttribute('role', 'group');
  filterBar.setAttribute('aria-label', '筛选床位状态');
  const people = new Map(active(ctx).map((person) => [person.bedId, person]));
  const states = [
    ['全部床位', ''],
    ['已入住', '已入住'],
    ['空闲', '空闲']
  ];
  let status = '';
  function draw() {
    grid.replaceChildren();
    for (const button of filterBar.children)
      button.setAttribute('aria-pressed', String(button.dataset.value === status));
    for (const ward of wards.filter((w) => !filter.value || filter.value === w)) {
      const inWard = all.filter((b) => b.ward === ward);
      const visible = inWard.filter((b) => !status || b.status === status);
      if (!visible.length) continue;
      const rooms = new Map();
      for (const bed of visible) {
        const room = bed.room || bed.label.replace(/-[^-]+$/, '');
        if (!rooms.has(room)) rooms.set(room, []);
        rooms.get(room).push(bed);
      }
      const layout = node('div', 'fx-room-layout');
      for (const [room, beds] of rooms) {
        const slots = node('div', 'fx-bed-grid');
        for (const bed of beds) {
          const person = people.get(bed.id);
          const available = bed.status === '空闲';
          const button = node('button', 'fx-bed ' + (available ? 'available' : 'occupied'), [
            node('strong', '', bed.label),
            node('span', '', person?.name || (available ? '空闲床位' : '已入住')),
            node(
              'small',
              '',
              person?.level || (available && canAct(ctx, 'care.admit') ? '可办理入住' : bed.status)
            )
          ]);
          button.type = 'button';
          button.disabled = !person && (!available || !canAct(ctx, 'care.admit'));
          button.addEventListener('click', () =>
            person ? profile(ctx, person) : admit(ctx, { bedId: bed.id })
          );
          slots.append(button);
        }
        layout.append(
          node('section', 'fx-room', [
            node('h3', 'fx-room-title', [
              ctx.ui.icon('bed', 15),
              String(room).includes('房') ? room : room + ' 房'
            ]),
            slots
          ])
        );
      }
      const count = inWard.filter((b) => b.status === '空闲').length;
      const occupied = inWard.length - count;
      const occupancy = node('progress', 'fx-occupancy');
      occupancy.max = inWard.length;
      occupancy.value = occupied;
      occupancy.setAttribute('aria-label', ward + '入住率');
      grid.append(
        node('section', 'fx-panel', [
          node('div', 'fx-toolbar', [
            node('h2', '', ward),
            node('div', 'fx-ward-summary', [
              occupancy,
              node('span', '', '已入住 ' + occupied + ' / ' + inWard.length + ' 床'),
              node('span', 'fx-count', '空闲 ' + count + ' 床')
            ])
          ]),
          layout
        ])
      );
    }
    if (!grid.childElementCount)
      grid.append(node('div', 'fx-empty fx-panel', '没有符合条件的床位'));
  }
  for (const [label, value] of states) {
    const button = node('button', '', label);
    button.type = 'button';
    button.dataset.value = value;
    button.addEventListener('click', () => {
      status = value;
      draw();
    });
    filterBar.append(button);
  }
  filter.addEventListener('change', draw);
  draw();
  return page(
    ctx,
    '床位管理',
    '按区域查看床态，选择床位办理入住或查阅在住档案。',
    canAct(ctx, 'care.completeTask') ? btn(ctx, '床旁核验', () => bedside(ctx), 'primary') : null,
    kpis([
      ['床位总数', all.length],
      ['已入住', all.length - free.length],
      ['空闲床位', free.length]
    ]),
    node('div', 'fx-bed-controls', [filterBar, filter]),
    grid
  );
}
