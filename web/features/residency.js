import {
  allocate, billingSchedule, bindContractFields, contractFields, historicInquiries,
  isTrial, register, registry, statusLabel,
} from './admission.js';
import { displayAmount } from './profile-controls.js';
import { roomsPage } from './rooms.js';
import { residentInsights } from './resident-insights.js';
import { careTimeline, scopedHistoryButton } from './care-timeline.js';
import {
  hasGrant,
  canAct,
  node,
  add,
  page,
  table,
  tabs,
  kpis,
  field,
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
import { clinicalHistory } from './care-pathway.js';
import { confirmStay, endTrial, trialList } from './trial-stays.js';
import { trialFollowups } from './trial-followups.js';
import { trialLength } from './trial-terms.js';

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
  allocate(
    ctx,
    null,
    ctx.state.beds.find((b) => b.id === defaults.bedId)
  );
}

export function transfer(ctx, row, targetBed) {
  allocate(ctx, row, targetBed);
}

function discharge(ctx, row) {
  runForm(ctx, {
    title: '办理退住',
    action: 'care.discharge',
    description: '确认后将释放 ' + row.name + ' 的床位，转为只读归档，保管 365 天。',
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
  const min = nextDay(row.endDate > today(ctx) ? row.endDate : today(ctx));
  const dialog = ctx.dialog({
    title: '续住登记',
    description: row.name + ' · 原合同到期日 ' + row.endDate,
    fields: contractFields(min, min),
    submitLabel: '核对续住',
    onSubmit: ({ contractTerm, endDate }) =>
      ctx.command('care.renew', { residentId: row.id, endDate: contractTerm === 'fixed' ? endDate : '' }, {
        title: '确认续住', target: row.name,
        fields: [['原合同到期日', row.endDate], ['续住合同期限', contractTerm === 'fixed' ? endDate : '无期限']],
      }),
  });
  bindContractFields(dialog);
}

export function profile(ctx, row) {
  const { state } = ctx;
  const own = (name) => {
    const entries = (state[name] || []).filter((item) => item.residentId === row.id);
    return name === 'bills' ? entries : byRecent(entries);
  };
  const summary = node('div', 'fx-profile fx-admission-profile');
  summary.append(recordIdentity(ctx, { ...row, status: statusLabel(row) }, row.level));
  if (row.status === '未入住' && canAct(ctx, 'care.fileArchive'))
    summary.append(
      btn(ctx, '封存为归档老人', () =>
        runForm(ctx, {
          title: '封存历史档案',
          action: 'care.fileArchive',
          description: row.name + ' · 此后该档案只读，日常资料从原退住日起保管 365 天。',
          fields: [
            field('archiveDate', '原退住或归档日期', {
              type: 'date',
              value: today(ctx),
              max: today(ctx)
            })
          ],
          map: (v) => ({ ...v, residentId: row.id })
        })
      )
    );
  if (row.status === '未入住' && canAct(ctx, 'care.admit'))
    summary.append(btn(ctx, '从此档案办理入住', () => allocate(ctx, row), 'primary'));
  if (row.status === '已退住') {
    const dated =
      row.dischargedAt &&
      /^\d{4}-\d{2}-\d{2}$/.test(row.dischargedAt) &&
      Number.isFinite(Date.parse(row.dischargedAt)) &&
      new Date(row.dischargedAt).toISOString().slice(0, 10) === row.dischargedAt;
    summary.append(
      node(
        'p',
        'rounds-warning',
        dated
          ? '只读归档 · ' + row.dischargedAt + ' 退住 · 日常档案保管 365 天'
          : '原退住日期待核实，保管期限尚未起算。'
      )
    );
    if (!dated && canAct(ctx, 'care.dateArchive'))
      summary.append(
        btn(ctx, '按凭证补登退住日期', () =>
          runForm(ctx, {
            title: '按原凭证补登退住日期',
            action: 'care.dateArchive',
            description:
              '以原凭证日期计算 365 天。确认已满保管期的日期后，将立即清理日常资料并保留原件与账务凭证。',
            fields: [field('archiveDate', '原凭证上的退住日期', { type: 'date', max: today(ctx) })],
            map: (v) => ({ ...v, residentId: row.id })
          })
        )
      );
  }
  if (row.status === '在住' && hasGrant(ctx, 'care', 'clinical'))
    summary.append(residentInsights(ctx, row.id));
  add(
    summary,
    facts([
      [
        '年龄 / 性别',
        [row.age == null ? '' : row.age + ' 岁', row.gender].filter(Boolean).join(' · ')
      ],
      ['入住日期', row.admittedAt],
      ['床位', bedName(ctx, row.bedId)],
      ...(row.admittedAt ? [
        ['入住方式', row.stayType === 'trial' ? '试住' : '正式入住'],
        ...(row.formalizedAt ? [['转正日期', row.formalizedAt]] : []),
        ...(row.trialDays ? [['试住约定', trialLength(row.trialDays) + ' · 至 ' + row.trialEndsAt]] : []),
        ...(row.trialPrice != null ? [['一次性试住费', money(row.trialPrice)]] : []),
        ...(row.stayType !== 'trial' ? [
          ['月付安排', billingSchedule(row)],
          ['合同期限', row.endDate || '无期限'],
        ] : []),
      ] : []),
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
  const changes = scopedHistoryButton(ctx, 'resident', row.id);
  if (changes) shortcuts.append(changes);
  if (row.status === '在住' && hasGrant(ctx, 'care'))
    shortcuts.append(
      btn(ctx, '照护时间线', () =>
        ctx.detail(row.name + ' · 照护记录', careTimeline(ctx, 'resident', row.id))
      )
    );
  if (state.user.routes.includes('dossier'))
    shortcuts.append(btn(ctx, '打开详细档案', () => openDossier(ctx, row), 'primary'));
  if (row.status === '在住' && hasGrant(ctx, 'care', 'clinical'))
    shortcuts.append(btn(ctx, '服务记录预览', () => familyPreview(ctx, row)));
  if (shortcuts.childElementCount) summary.append(shortcuts);
  if (row.status === '在住') {
    const actions = choose();
    if (hasGrant(ctx, 'intake', 'care'))
      actions.append(btn(ctx, '床头卡', () => bedCard(ctx, row)));
    if (canAct(ctx, 'care.archive')) actions.append(btn(ctx, '复核摘要', () => archive(ctx, row)));
    if (canAct(ctx, 'care.leave')) actions.append(btn(ctx, '登记请假', () => leave(ctx, row)));
    if (isTrial(row)) {
      if (canAct(ctx, 'care.confirmStay')) actions.append(btn(ctx, '试住转正式', () => confirmStay(ctx, row)));
      if (canAct(ctx, 'care.endTrial')) actions.append(btn(ctx, '未转正离院', () => endTrial(ctx, row)));
    }
    if (!isTrial(row) && row.endDate && canAct(ctx, 'care.renew')) actions.append(btn(ctx, '续住', () => renew(ctx, row)));
    if (canAct(ctx, 'care.transfer')) actions.append(btn(ctx, '转床', () => transfer(ctx, row)));
    if (!isTrial(row) && canAct(ctx, 'care.discharge')) actions.append(btn(ctx, '退住', () => discharge(ctx, row)));
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
    block('收费', 'bills', ['finance'], (b) =>
      named(b.month + (b.kind === 'trial' ? ' · 一次性试住费' : ' · 月费') + ' · ' + money(b.amount), b.status + ' · 待缴 ' + money(b.balance))
    ),
    block('请假记录', 'leaves', ['finance', 'intake'], (l) =>
      named(l.startDate + ' 至 ' + l.endDate, l.reason)
    ),
    block('历史档案', 'archives', ['clinical', 'medical'], (a) =>
      named(a.summary || a.note || '档案更新', a.date)
    )
  );
  if (hasGrant(ctx, 'relatives')) {
    const details = (state.dossierProfiles || []).find((p) => p.residentId === row.id) || {};
    history.append(
      section(
        '费用来源',
        node('p', '', details.fundingSources?.join('、') || details.incomeSource || '未登记')
      ),
      section(
        '长者养老金收入',
        node('p', '', displayAmount(details.pensionBand, details.pensionAmount))
      )
    );
  }
  if (history.childElementCount) summary.append(history);
  add(summary, clinicalHistory(ctx, row));
  ctx.detail('长者档案', summary);
}

export function inquiryForm(ctx) {
  register(ctx);
}

export function intake(ctx) {
  return residents(ctx);
}

export function residents(ctx) {
  const choices = [
    ['all', '档案名册', () => node('div', 'fx-profile', [registry(ctx), historicInquiries(ctx)])],
    ['trials', '试住管理', () => node('div', 'fx-page-stack', [trialList(ctx), trialFollowups(ctx)])],
  ];
  if (canAct(ctx, 'care.renew'))
    choices.push([
      'renew',
      '到期续住',
      () =>
        table(ctx, {
          title: '到期及未来 30 天到期的档案',
          rows: expiringContracts(ctx.state.residents, today(ctx)),
          cols: [
            { label: '长者', view: (r) => r.name },
            { label: '合同到期', view: (r) => r.endDate },
            { label: '办理', view: (r) => link(ctx, '续住', () => renew(ctx, r)) }
          ]
        })
    ]);
  return page(
    ctx,
    '长者档案',
    '',
    canAct(ctx, 'care.register') ? btn(ctx, '新建长者档案', () => register(ctx), 'primary') : null,
    choices.length > 1 ? tabs('residents', choices) : choices[0][2]()
  );
}

function allBeds(ctx) {
  const all = ctx.state.beds;
  const free = bedOptions(ctx);
  const wardName = (b) =>
    [...(ctx.state.bedLocations?.[b.id]?.slice(0, 2) || []), b.ward].join(' / ');
  const wards = [...new Set(all.map(wardName))];
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
      const inWard = all.filter((b) => wardName(b) === ward);
      const visible = inWard.filter((b) => !status || b.status === status);
      if (!visible.length) continue;
      const rooms = new Map();
      for (const bed of visible) {
        const room = [
          ctx.state.bedLocations?.[bed.id]?.[2],
          bed.room || bed.label.replace(/-[^-]+$/, '')
        ]
          .filter(Boolean)
          .join(' · ');
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
              person && isTrial(person) ? ['试住中', person.level].filter(Boolean).join(' · ')
                : person?.level || (available && canAct(ctx, 'care.admit') ? '可办理入住' : bed.status)
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
  return node('div', 'fx-profile', [
    kpis([
      ['床位总数', all.length],
      ['已入住', all.length - free.length],
      ['空闲床位', free.length]
    ]),
    node('div', 'fx-bed-controls', [filterBar, filter]),
    grid
  ]);
}

export function beds(ctx) {
  return page(
    ctx,
    '床位管理',
    '',
    canAct(ctx, 'care.completeTask') ? btn(ctx, '床旁核验', () => bedside(ctx), 'primary') : null,
    tabs('beds', [
      ['all', '全部床位', () => allBeds(ctx)],
      ['plan', '楼层平面图', () => roomsPage(ctx, true)]
    ])
  );
}
export function expiringContracts(residents, day) {
  const cutoff = new Date(day + 'T00:00:00Z');
  cutoff.setUTCDate(cutoff.getUTCDate() + 30);
  const limit = cutoff.toISOString().slice(0, 10);
  return residents
    .filter((r) => r.status === '在住' && !isTrial(r) && r.endDate && r.endDate <= limit)
    .sort((a, b) => a.endDate.localeCompare(b.endDate));
}
