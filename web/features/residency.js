import { careAreas } from './care-areas.js';
import { residentRoster } from './resident-roster.js';
import { medicationReceivingLink } from './medication-receiving.js';
import { openMedicationRound } from './med-rounds.js';
import { residentLabel, residentAnchor, staffLabel } from './people-labels.js';
import {
  allocate, admissionRowActions, billingSchedule, bindContractFields, contractFields, historicInquiries,
  isTrial, labelBedStay, register, statusLabel,
} from './admission.js';
import { goToRoom, roomsPage } from './rooms.js';
import { roomTypeLabel } from './room-vector.js';
import { residentInsights } from './resident-insights.js';
import { healthProfile } from './resident-health.js';
import {
  hasGrant,
  canAct,
  node,
  add,
  page,
  table,
  tabs,
  currentTab,
  kpis,
  field,
  select,
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
import { confirmStay, endTrial } from './trial-stays.js';
import { trialFollowups } from './trial-followups.js';
import { trialLength } from './trial-terms.js';

import { bedCard, familyPreview, bedside } from './bedcard.js';

export const levels = ['自理', '半失能', '失能'];

const renewalReasons = {
  expired: '合同已到期',
  securityUsed: '已动用押金',
  upcoming: '合同即将到期',
};

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
    description: (row ? residentLabel(ctx, row) + ' · ' : '') + (ctx.state.retainServiceRecords ? '确认后释放床位，档案转为只读，由档案负责人核定保管期限。' : '确认后释放当前床位，退住档案保留 365 天。'),
    fields: [...(row ? [] : [stayPicker(ctx, person => !isTrial(person))]), memo('note', '退住小结', true)],
    map: (v) => ({
      ...v,
      residentId: row?.id || v.residentId
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
      ...(row ? [] : [stayPicker(ctx)]),
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
      residentId: row?.id || v.residentId
    })
  });
}

function stayPicker(ctx, include = () => true) {
  return select('residentId', '在住长辈', active(ctx).filter(include).map(person => ({
    value: person.id, label: residentLabel(ctx, person),
  })));
}

function leaveDirectory(ctx) {
  if (!hasGrant(ctx, 'intake', 'finance')) return ctx.ui.empty('当前岗位没有请假台账的查看权限。');
  const people = new Map(ctx.state.residents.map(row => [row.id, row]));
  const day = today(ctx);
  const stage = row => row.endDate < day ? '已结束' : row.startDate > day ? '待开始' : '请假中';
  const rows = (ctx.state.leaves || []).filter(row => people.has(row.residentId))
    .sort((a,b) => b.startDate.localeCompare(a.startDate) || b.id.localeCompare(a.id));
  return page(ctx, '请假管理', '', canAct(ctx, 'care.leave') ? btn(ctx, '登记请假', () => leave(ctx), 'primary') : null,
    table(ctx, { title:'请假台账', rows, empty:'尚无请假记录。',
      search:{placeholder:'搜索姓名、房号或请假事由', value:row => [residentLabel(ctx,people.get(row.residentId)),row.reason].join(' ')},
      filter:{label:'请假状态', value:stage, options:['待开始','请假中','已结束']},
      cols:[
        {label:'长辈',view:row => residentAnchor(ctx,people.get(row.residentId))},
        {label:'开始日期',view:row => row.startDate}, {label:'结束日期',view:row => row.endDate},
        {label:'状态',view:row => badge(ctx,stage(row))},
        ...(hasGrant(ctx,'intake') ? [{label:'请假事由',view:row => row.reason || '未填写'}] : []),
        {label:'登记日期',view:row => row.date},
      ],
    }));
}

function dischargeDirectory(ctx) {
  if (!hasGrant(ctx, 'residents','care','intake','finance','clinical'))
    return ctx.ui.empty('当前岗位没有退住记录的查看权限。');
  const priorBeds = new Map();
  for (const move of ctx.state.bedMoves || []) {
    if (move.kind === '退住' && move.beforeBedId) priorBeds.set(move.residentId, move.beforeBedId);
  }
  const rows = ctx.state.residents.filter(row => row.status === '已退住')
    .sort((a,b) => (b.dischargedAt || '').localeCompare(a.dischargedAt || ''));
  return page(ctx, '退住记录', '', canAct(ctx, 'care.discharge') ? btn(ctx, '办理退住', () => discharge(ctx), 'primary') : null,
    table(ctx, {title:'退住归档名册', rows, empty:'尚无保管期内的退住档案。',
      search:{placeholder:'搜索姓名、档案号或原床位', value:row => [row.name,row.id,bedName(ctx,priorBeds.get(row.id))].join(' ')},
      cols:[
        {label:'长辈',view:row => residentAnchor(ctx,row)},
        {label:'原床位',view:row => bedName(ctx,priorBeds.get(row.id))},
        {label:'入住日期',view:row => row.admittedAt || '—'},
        {label:'退住日期',view:row => row.dischargedAt || '待核实'},
        {label:'保管至',view:row => ctx.state.retainServiceRecords ? '档案保全' : row.archiveUntil || '待核实'},
        ...(hasGrant(ctx,'intake') ? [{label:'退住小结',view:row => row.dischargeNote || '未登记'}] : []),
        {label:'操作',view:row => link(ctx,'查看详细档案',() => openDossier(ctx,row))},
      ],
    }));
}

function renew(ctx, row) {
  const min = nextDay(row.endDate > today(ctx) ? row.endDate : today(ctx));
  const dialog = ctx.dialog({
    title: '续住登记',
    description: [
      residentLabel(ctx, row), '原合同到期日 ' + row.endDate,
      row.renewalReminder && renewalReasons[row.renewalReminder.reason],
    ].filter(Boolean).join(' · '),
    fields: contractFields(min, min),
    submitLabel: '核对续住',
    onSubmit: ({ contractTerm, endDate }) =>
      ctx.command('care.renew', { residentId: row.id, endDate: contractTerm === 'fixed' ? endDate : '' }, {
        title: '确认续住', target: residentLabel(ctx, row),
        fields: [['原合同到期日', row.endDate], ['续住合同期限', contractTerm === 'fixed' ? endDate : '无期限']],
      }),
  });
  bindContractFields(dialog);
}

export function profile(ctx, row, lifeEvent) {
  if (lifeEvent) return openDossier(ctx, row, lifeEvent);
  const basic = [
    ['年龄 / 性别', [row.age == null ? '' : row.age + ' 岁', row.gender].filter(Boolean).join(' · ')],
    ['床位', row.bedId ? labelBedStay(bedName(ctx, row.bedId), row) : '未分配'],
    ['入住日期', row.admittedAt],
    ['联系方式', row.contact],
  ].filter(([, value]) => value);
  const summary = node('div', 'fx-profile resident-brief', [
    recordIdentity(ctx, { ...row, status: statusLabel(row) }, row.level),
    section('常用资料', facts(basic)),
    hasGrant(ctx, 'care', 'clinical', 'medical') ? healthProfile(ctx, row, {compact: true}) : null,
    row.status === '在住' && hasGrant(ctx, 'care', 'clinical')
      ? residentInsights(ctx, row.id, {compact: true}) : null,
  ]);
  const dialog = ctx.detail('长辈简易档案', summary);
  const head = dialog.querySelector('.dialog-head');
  const open = btn(ctx, '打开详细档案', () => {
    const live = ctx.current?.() || ctx;
    const resident = live.state.residents.find(person => person.id === row.id);
    if (resident) {
      if (live.openWorkspaceTab) dialog.close();
      openDossier(live, resident);
    }
    else ctx.toast('该长辈档案未开放或已失效');
  }, 'primary');
  open.classList.add('resident-brief-open');
  head.insertBefore(open, head.lastElementChild);
  return dialog;
}

export function residencyDetails(ctx, row) {
  const enrollment = node('div', 'fx-profile');
  const actions = choose();
  if (row.status === '未入住' && canAct(ctx, 'care.fileArchive'))
    actions.append(
      btn(ctx, '封存为归档老人', () =>
        runForm(ctx, {
          title: '封存历史档案',
          action: 'care.fileArchive',
          description: residentLabel(ctx, row) + (ctx.state.retainServiceRecords ? ' · 归档后只读，保留法定档案及身份关联。' : ' · 此后该档案只读，日常资料从原退住日起保管 365 天。'),
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
    actions.append(btn(ctx, '从此档案办理入住', () => allocate(ctx, row), 'primary'));
  if (row.status === '已退住') {
    const dated =
      row.dischargedAt &&
      /^\d{4}-\d{2}-\d{2}$/.test(row.dischargedAt) &&
      Number.isFinite(Date.parse(row.dischargedAt)) &&
      new Date(row.dischargedAt).toISOString().slice(0, 10) === row.dischargedAt;
    enrollment.append(
      node(
        'p',
        'rounds-warning',
        dated
          ? '只读归档 · ' + row.dischargedAt + (ctx.state.retainServiceRecords ? ' 退住 · 档案保全' : ' 退住 · 日常档案保管 365 天')
          : '原退住日期待核实，保管期限尚未起算。'
      )
    );
    if (!dated && canAct(ctx, 'care.dateArchive'))
      actions.append(
        btn(ctx, '按凭证补登退住日期', () =>
          runForm(ctx, {
            title: '按原凭证补登退住日期',
            action: 'care.dateArchive',
            description:
              ctx.state.retainServiceRecords ? '按原凭证登记退住日期，机构档案保持只读保全。' : '以原凭证日期计算 365 天。确认已满保管期的日期后，将立即清理日常资料并保留原件与账务凭证。',
            fields: [field('archiveDate', '原凭证上的退住日期', { type: 'date', max: today(ctx) })],
            map: (v) => ({ ...v, residentId: row.id })
          })
        )
      );
  }
  if (hasGrant(ctx, 'residents', 'intake', 'care')) {
    const stay = [
      ['入住日期', row.admittedAt],
      ['床位', row.bedId ? labelBedStay(bedName(ctx, row.bedId), row) : '未分配'],
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
    ];
    enrollment.append(facts(stay));
  }
  if (isTrial(row)) {
    add(actions,
      canAct(ctx, 'care.confirmStay') ? btn(ctx, '确认入住', () => confirmStay(ctx, row), 'primary') : null,
      canAct(ctx, 'care.endTrial') ? btn(ctx, '取消入住', () => endTrial(ctx, row)) : null,
    );
  }
  if (row.status === '在住') {
    if (hasGrant(ctx, 'intake', 'care'))
      actions.append(btn(ctx, '床头卡', () => bedCard(ctx, row)));
    if (hasGrant(ctx, 'care', 'clinical'))
      actions.append(btn(ctx, '服务记录预览', () => familyPreview(ctx, row)));
    if (canAct(ctx, 'care.confirmMedRound'))
      actions.append(btn(ctx, '服药核对', () => openMedicationRound(ctx, {residentId: row.id})));
    add(actions, medicationReceivingLink(ctx, row));
    if (canAct(ctx, 'care.archive')) actions.append(btn(ctx, '复核摘要', () => archive(ctx, row)));
    if (canAct(ctx, 'care.leave')) actions.append(btn(ctx, '登记请假', () => leave(ctx, row)));
    if (!isTrial(row) && row.endDate && canAct(ctx, 'care.renew')) actions.append(btn(ctx, '续住', () => renew(ctx, row)));
    if (canAct(ctx, 'care.transfer')) actions.append(btn(ctx, '转床', () => transfer(ctx, row)));
    if (!isTrial(row) && canAct(ctx, 'care.discharge')) actions.append(btn(ctx, '退住', () => discharge(ctx, row)));
  }
  if (actions.childElementCount) enrollment.append(actions);
  if (row.renewalHistory?.length) {
    const entries = [...row.renewalHistory].sort((a, b) => b.date.localeCompare(a.date));
    enrollment.append(disclosure('续住记录', records(entries, (entry) => named(
      entry.source === 'payment' ? '缴费到账 · 自动续住' : '人工续住',
      [entry.date, (entry.previousEndDate || '无期限') + ' → ' + (entry.endDate || '无期限')].join(' · '),
    )), entries.length));
  }
  const block = (title, key, grants, describe) => {
    if (!hasGrant(ctx, ...grants)) return null;
    const entries = byRecent((ctx.state[key] || []).filter(item => item.residentId === row.id));
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
      named(t.title + ' · ' + t.status, t.date + ' ' + t.time + ' · ' + staffLabel(ctx, t.assignee, t.assigneeId))
    ),
    block('用药记录', 'medications', ['clinical'], (m) =>
      named(m.name + ' · ' + m.status, m.instruction)
    ),
    block('药品交接记录', 'medicationReceipts', ['clinical'], (m) =>
      named(m.name + ' · ' + m.quantity + m.unit, m.receivedAt.slice(0,16).replace('T',' ') + ' · ' + staffLabel(ctx,m.operator,m.operatorId))
    ),
    block('健康体征', 'vitals', ['clinical'], (v) =>
      named(v.metric + ' ' + v.value + ' ' + (v.unit || ''), v.date + ' · ' + v.status)
    ),
    block('请假记录', 'leaves', ['finance', 'intake'], (l) =>
      named(l.startDate + ' 至 ' + l.endDate, l.reason)
    )
  );
  return {
    enrollment: enrollment.childElementCount ? section('入住与照护办理', enrollment) : null,
    history: history.childElementCount ? disclosure('入住与照护历史', history) : null,
    clinical: clinicalHistory(ctx, row),
  };
}

export function inquiryForm(ctx) {
  register(ctx);
}

export function intake(ctx) {
  return residents(ctx);
}

function renewalSection(ctx, open) {
  if (!canAct(ctx, 'care.renew')) return null;
  const rows = renewalReminders(ctx.state.residents);
  const panel = disclosure('到期续住', table(ctx, {
    title: '续住提醒',
    rows,
    empty: '当前没有需要核对的续住事项。',
    search: { placeholder: '搜索长辈姓名', value: (r) => residentLabel(ctx, r) },
    cols: [
      { label: '长辈', view: (r) => residentAnchor(ctx, r) },
      { label: '合同到期', view: (r) => r.endDate || '无期限' },
      { label: '提醒原因', view: (r) => named(
        renewalReasons[r.renewalReminder.reason], r.renewalReminder.at,
      ) },
      { label: '办理', align: 'end', view: (r) => r.endDate
        ? link(ctx, '续住', () => renew(ctx, r))
        : link(ctx, '查看入住资料', () => openDossier(ctx, r)) },
    ],
  }), rows.length);
  panel.open = open;
  return panel;
}

export function residents(ctx) {
  const view = currentTab('residents');
  if (view === 'leaves') return leaveDirectory(ctx);
  if (view === 'discharged') return dischargeDirectory(ctx);
  const rows = ctx.state.trialFollowups || [];
  const showFollowups = view === 'followups' || view === 'trials';
  const followups = rows.length || showFollowups
    ? disclosure('试住回访', trialFollowups(ctx), rows.filter(r => r.status === '待回访').length) : null;
  if (followups) followups.open = showFollowups;
  const renewal = renewalSection(ctx, view === 'renew');
  if (view === 'renew' || view === 'followups')
    return page(ctx, view === 'renew' ? '到期续住' : '试住回访', '', null, view === 'renew' ? renewal : followups);
  const roster = residentRoster(ctx, {
    mode:'admission', initialStatus:view, create:canAct(ctx, 'care.register') ? () => register(ctx) : null,
    admit:canAct(ctx, 'care.admit') ? () => admit(ctx) : null,
    rowActions:person => admissionRowActions(ctx, person),
    detail:person => openDossier(ctx, person),
  });
  roster.append(node('div', 'roster-secondary', [followups, renewal, historicInquiries(ctx)]));
  return roster;
}

const bedViewSorts = [
  ['floor', '楼层 / 房间号'],
  ['room', '房间号'],
  ['area', '照护区域'],
  ['plan', '平面图位置'],
];
const bedNumbers = new Intl.Collator('zh-CN', {numeric: true, sensitivity: 'base'});
let bedSearchRevision = 0;

export function reopenBedFilter() {
  bedSearchRevision++;
}

function allBeds(ctx) {
  const personFor = new Map(active(ctx).map(person => [person.bedId, person]));
  const memory = ctx.workspaceState || {};
  const view = memory.bedList ||= {building:'', floor:'', area:'', status:'', query:'', order:'floor',
    capacity:'', limit:0, request:'', display:'ledger'};
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const requested = ['capacity', 'limit', 'campus', 'building', 'floor', 'room', 'status','area'].map(key => params.get(key));
  const key = JSON.stringify([bedSearchRevision,...requested]);
  if (requested.some(Boolean) && view.request !== key) {
    const [capacity, limit, campus, building, floor, room, status,area] = requested;
    view.request = key;
    view.capacity = /^[1-9]$|^1[0-2]$/.test(capacity || '') ? capacity : '';
    view.limit = /^[1-9]$|^[12][0-9]$|^30$/.test(limit || '') ? Number(limit) : 0;
    view.campus = campus || '';
    view.floor = floor || '';
    view.room = room || '';
    view.building = building || '';
    view.area = area ? 'area:'+area : '';
    view.query = '';
    view.status = { vacant: '空闲', occupied: '已入住' }[status] || '';
  } else if (!requested.some(Boolean) && view.request) {
    view.request = '';
    view.limit = 0;
    view.campus = view.floor = view.room = '';
  }
  let selectedRooms = null;
  let checkedBuildings = false;
  const directory = new Map();
  const places = new Map();
  const unmapped = '__unmapped__';

  const labelNumber = value => value.includes('房') ? value : value + ' 房';
  const scopeText = (...values) => values.filter(Boolean).join(' / ');
  const findText = value => String(value || '').normalize('NFKC').toLocaleLowerCase();
  for (const bed of ctx.state.beds) {
    const place = ctx.state.bedDirectory?.[bed.id];
    const [oldCampus, oldBuilding, oldFloor] = ctx.state.bedLocations?.[bed.id] || [];
    const campusName = place?.campusName || oldCampus || '';
    const campusId = place?.campusId || '';
    const buildingName = place?.buildingName || oldBuilding || '';
    const floorLabel = place?.floorLabel || oldFloor || '';
    const buildingId = place?.buildingId || (buildingName ? scopeText(campusName, buildingName) : unmapped);
    const floorId = place?.floorId || scopeText(buildingId, floorLabel);
    const roomNumber = place?.roomNumber || bed.room || bed.label.replace(/-[^-]+$/, '');
    const identity = place?.roomId || scopeText(buildingId, floorId, roomNumber);
    const areaPath = Array.isArray(place?.areaPath) ? place.areaPath.join(' / ') : place?.areaPath || '';
    if (buildingId !== unmapped && !directory.has(buildingId))
      directory.set(buildingId, scopeText(campusName, buildingName));
    if (!places.has(identity)) places.set(identity, {
      id: place?.roomId, buildingId, campusName, buildingName, floorId, floorLabel,
      campusId,
      floorNumber: place?.floorNumber, roomNumber, areaId: place?.areaId, areaPath,
      areaIds: place?.areaIds || [],
      x: place?.x, y: place?.y, beds: [],
    });
    places.get(identity).beds.push(bed);
  }

  const search = node('input', 'fx-input');
  search.type = 'search';
  search.maxLength = 64;
  search.placeholder = '搜索长辈姓名、房号或床号';
  search.setAttribute('aria-label', search.placeholder);
  search.value = view.query;
  const building = node('select', 'fx-input');
  const floor = node('select', 'fx-input');
  const area = node('select', 'fx-input');
  const capacity = node('select', 'fx-input');
  capacity.add(new Option('全部房型', ''));
  for (let count = 1; count <= 12; count++) capacity.add(new Option(roomTypeLabel(count), String(count)));
  capacity.value = view.capacity;
  const order = node('select', 'fx-input');
  const label = (title, control) => node('label', 'bed-list-control', [node('span', '', title), control]);
  for (const [value, title] of bedViewSorts) order.add(new Option(title, value));
  order.value = view.order;
  const controls = node('section', 'fx-panel bed-list-controls', [
    node('div', 'bed-list-fields', [
      label('搜索床位', search), label('楼栋', building), label('楼层',floor),
      label('区域或病区', area), label('房间类型', capacity), label('排序方式', order),
    ]),
  ]);
  const statusBar = node('div', 'fx-bed-filters');
  statusBar.setAttribute('role', 'group');
  statusBar.setAttribute('aria-label', '筛选床位状态');
  const count = node('span', 'fx-muted bed-list-count');
  count.setAttribute('role', 'status');
  const clearScope = link(ctx, '清除快速筛选范围', () => {
    view.limit = 0;
    view.campus = view.floor = view.room = view.building = view.area = '';
    fillBuildings();
    fillFloors();
    fillAreas();
    draw();
  });
  const modes = choose();
  modes.classList.add('desk-view-switch');
  for (const [id,title] of [['ledger','床位台账'],['board','房间看板']]) {
    const button=btn(ctx,title,()=>{view.display=id;draw();},'ghost');
    button.dataset.layout = id;
    modes.append(button);
  }
  controls.append(node('div', 'bed-list-status', [statusBar, count, clearScope,modes]));
  const cards = node('div', 'fx-wards bed-list-grid');
  const metrics = node('div', 'bed-list-metrics');

  const sortText = (a, b) => bedNumbers.compare(a || '', b || '');
  const sortFloor = (a, b) =>
    (a.floorNumber ?? Number.MAX_SAFE_INTEGER) - (b.floorNumber ?? Number.MAX_SAFE_INTEGER) ||
    sortText(a.floorLabel, b.floorLabel) || sortText(a.floorId, b.floorId);
  const sortRoom = (a, b) => sortText(a.roomNumber, b.roomNumber) || sortFloor(a, b) || sortText(a.id, b.id);
  const sortBuilding = (a, b) =>
    Number(a.buildingId === unmapped) - Number(b.buildingId === unmapped) ||
    sortText(a.campusName, b.campusName) || sortText(a.buildingName, b.buildingName) ||
    sortText(a.buildingId, b.buildingId);
  const sortArea = (a, b) =>
    Number(!a.areaPath) - Number(!b.areaPath) || sortText(a.areaPath, b.areaPath) || sortText(a.areaId, b.areaId);
  function sortPlan(a, b) {
    const aMapped = Number.isFinite(a.x) && Number.isFinite(a.y);
    const bMapped = Number.isFinite(b.x) && Number.isFinite(b.y);
    return sortFloor(a, b) || Number(bMapped) - Number(aMapped) ||
      (aMapped && bMapped ? a.y - b.y || a.x - b.x : 0) || sortRoom(a, b);
  }
  function compare(a, b) {
    const byBuilding = sortBuilding(a, b);
    if (byBuilding) return byBuilding;
    if (view.order === 'plan') return sortPlan(a, b);
    if (view.order === 'area') return sortArea(a, b) || sortFloor(a, b) || sortRoom(a, b);
    if (view.order === 'room') return sortRoom(a, b);
    return sortFloor(a, b) || sortRoom(a, b);
  }

  function choices(control, entries, prompt, value) {
    control.replaceChildren(new Option(prompt, ''), ...entries.map(([id, title]) => new Option(title, id)));
    control.value = entries.some(([id]) => id === value) ? value : '';
    return control.value;
  }
  function fillBuildings() {
    const list = [...directory].sort((a, b) => sortText(a[1], b[1]));
    if ([...places.values()].some(r => r.buildingId === unmapped))
      list.push([unmapped, '位置待登记']);
    if (view.building && !list.some(([id]) => id === view.building))
      list.push([view.building, checkedBuildings ? '指定楼栋暂不可查看' : '正在核对指定楼栋…']);
    view.building = choices(building, list, '全部楼栋', view.building);
  }
  const areaKey = room => room.areaId || scopeText(room.buildingId, room.areaPath || '未分区');
  function fillFloors() {
    const options = new Map();
    for (const room of [...places.values()].sort(sortFloor)) {
      if (view.building && view.building !== room.buildingId || view.campus && view.campus !== room.campusId) continue;
      const text=scopeText(view.building ? '' : room.buildingName,room.floorLabel);
      if (room.floorId && text) options.set(room.floorId,text);
    }
    if (view.floor && !options.has(view.floor)) options.set(view.floor,'指定楼层暂不可见');
    view.floor=choices(floor,[...options],'全部楼层',view.floor);
  }
  function roomsInBuilding() {
    return [...places.values()].filter(r =>
      (!view.building || r.buildingId === view.building) &&
      (!view.campus || r.campusId === view.campus) &&
      (!view.floor || r.floorId === view.floor) &&
      (!view.room || r.id === view.room));
  }
  function fillAreas() {
    const entries = new Map();
    for (const room of roomsInBuilding()) {
      const prefix = view.building ? '' : room.buildingName;
      if (room.areaIds.length) {
        const labels = room.areaPath.split(' / ');
        room.areaIds.forEach((id, level) =>
          entries.set('area:' + id, scopeText(prefix, ...labels.slice(0, level + 1))));
      } else {
        entries.set('area:' + areaKey(room), scopeText(prefix, '未分区'));
      }
      for (const bed of room.beds) {
        if (bed.ward) entries.set('ward:' + bed.ward, '病区 · ' + bed.ward);
      }
    }
    if (view.area && view.area === 'area:'+params.get('area') && !entries.has(view.area))
      entries.set(view.area,'指定区域（暂无可见床位）');
    const list = [...entries].sort((a, b) => sortText(a[1], b[1]));
    view.area = choices(area, list, '全部区域与病区', view.area);
  }
  function inArea(room, bed) {
    return !view.area || view.area === 'area:' + areaKey(room) ||
      room.areaIds.some(id => view.area === 'area:' + id) || view.area === 'ward:' + bed.ward;
  }
  function matches(bed, room, terms) {
    const person = personFor.get(bed.id);
    const fields = [bed.label, bed.ward, person?.name, room.roomNumber, room.areaPath,
      room.buildingName, room.campusName, room.floorLabel].map(findText);
    return terms.every(term => fields.some(value => value.includes(term)));
  }

  function groupFor(room) {
    const buildingTitle = scopeText(room.campusName, room.buildingName) || '位置待登记';
    if (view.order === 'room') return [room.buildingId, buildingTitle];
    if (view.order === 'area') return [
      JSON.stringify([room.buildingId, areaKey(room)]),
      scopeText(buildingTitle, room.areaPath || '未分区'),
    ];
    return [room.floorId, scopeText(buildingTitle, room.floorLabel || '楼层待登记')];
  }
  function renderBed(bed) {
    const person = personFor.get(bed.id);
    const available = bed.status === '空闲';
    const canAdmit = available && canAct(ctx, 'care.admit');
    const button = node('button', 'fx-bed ' + (available ? 'available' : 'occupied'), [
      node('strong', '', labelBedStay(bed.label, person)),
      node('span', '', person ? residentLabel(ctx, person) : available ? '空闲床位' : bed.status),
      node('small', '', person?.level || (canAdmit ? '可办理入住' : bed.status)),
    ]);
    button.type = 'button';
    button.disabled = !person && !canAdmit;
    button.addEventListener('click', () =>
      person ? profile(ctx, person) : admit(ctx, {bedId: bed.id}));
    return button;
  }
  function renderRoom(room, beds) {
    const title = labelNumber(room.roomNumber);
    const within = view.order === 'room' || view.order === 'area' ? room.floorLabel : room.areaPath;
    const showMap = room.id ? link(ctx, '在平面图定位', () => goToRoom(ctx, room.id)) : null;
    if (showMap) showMap.setAttribute('aria-label', '在平面图定位 ' + scopeText(room.buildingName, room.floorLabel, title));
    return node('section', 'fx-room bed-list-room', [
      node('div', 'bed-list-room-heading', [
        node('div', '', [
          node('h3', 'fx-room-title', [ctx.ui.icon('bed', 15), title]),
          node('small', 'fx-muted', scopeText(roomTypeLabel(room.beds.length), within)),
        ]),
        showMap,
      ]),
      node('div', 'fx-bed-grid', [...beds].sort((a, b) => sortText(a.label, b.label)).map(renderBed)),
    ]);
  }
  function renderGroup(group) {
    const occupancy = node('progress', 'fx-occupancy');
    occupancy.max = group.total;
    occupancy.value = group.occupied;
    occupancy.setAttribute('aria-label', group.title + '入住率');
    return node('section', 'fx-panel', [
      node('div', 'fx-toolbar', [
        node('h2', '', group.title),
        node('div', 'fx-ward-summary', [
          occupancy, node('span', '', '已入住 ' + occupancy.value + ' / ' + group.total + ' 床'),
          node('span', 'fx-count', '空闲 ' + group.vacant + ' 床'),
        ]),
      ]),
      node('div', 'fx-room-layout', group.rooms),
    ]);
  }

  function draw() {
    const terms = findText(view.query).trim().split(/\s+/).filter(Boolean);
    const groups = new Map();
    let total = 0;
    let occupied = 0;
    let vacant = 0;
    let shown = 0;
    let shownRooms = 0;
    let matchedRooms = 0;
    const ledger = [];
    for (const room of roomsInBuilding().sort(compare)) {
      if (view.capacity && Number(view.capacity) !== room.beds.length) continue;
      const matched = room.beds.filter(bed => inArea(room, bed) && matches(bed, room, terms));
      const visible = matched.filter(bed => !view.status || bed.status === view.status);
      if (visible.length) matchedRooms++;
      if (selectedRooms && view.limit && !selectedRooms.has(room.id)) continue;
      if (view.limit && shownRooms >= view.limit) continue;
      const free = matched.filter(bed => bed.status === '空闲').length;
      const used = matched.filter(bed => Boolean(personFor.get(bed.id) || bed.residentId || bed.status==='已入住')).length;
      occupied += used;
      total += matched.length;
      vacant += free;
      if (!matched.length) continue;
      const [key, title] = groupFor(room);
      if (!groups.has(key)) groups.set(key, {title, rooms: [], total: 0, vacant: 0, occupied:0});
      const group = groups.get(key);
      group.total += matched.length;
      group.vacant += free;
      group.occupied += used;
      if (visible.length) {
        if (view.display==='board') group.rooms.push(renderRoom(room, visible));
        else ledger.push(...[...visible].sort((a,b)=>sortText(a.label,b.label)).map(bed=>({id:bed.id,bed,room})));
        shownRooms++;
      }
      shown += visible.length;
    }
    for (const button of statusBar.children)
      button.setAttribute('aria-pressed', String(button.dataset.value === view.status));
    for (const button of modes.children) button.setAttribute('aria-pressed',String(button.dataset.layout===view.display));
    metrics.replaceChildren(kpis([['床位总数', total], ['已入住', occupied], ['空闲床位', vacant],['其他状态',total-occupied-vacant]]));
    count.textContent = '显示 ' + shownRooms + ' 间，' + shown + ' 张床位' +
      (shownRooms < matchedRooms ? '（共 ' + matchedRooms + ' 间符合条件）' : '');
    clearScope.hidden = !(view.limit || view.campus || view.building || view.floor || view.room || view.area);
    if (view.display==='ledger') {
      cards.replaceChildren(table(ctx,{title:'床位台账',rows:ledger,empty:'没有符合条件的床位。',
        cols:[
          {label:'床号 / 房型',view:({bed,room})=>named(labelBedStay(bed.label,personFor.get(bed.id)),roomTypeLabel(room.beds.length))},
          {label:'分院 / 楼层',view:({room})=>scopeText(room.campusName,room.buildingName,room.floorLabel) || '待登记'},
          {label:'区域',view:({room})=>room.areaPath || '未分区'},
          {label:'床位状态',view:({bed})=>badge(ctx,bed.status,bed.status==='空闲'?'green':'neutral')},
          {label:'在住长辈',view:({bed})=>personFor.has(bed.id) ? residentAnchor(ctx,personFor.get(bed.id)) : '—'},
          {label:'操作',view:({bed,room})=>choose(
            room.id ? link(ctx,'平面图定位',()=>goToRoom(ctx,room.id)) : null,
            personFor.has(bed.id) ? link(ctx,'查看档案',()=>profile(ctx,personFor.get(bed.id))) :
              bed.status==='空闲' && canAct(ctx,'care.admit') ? link(ctx,'办理入住',()=>admit(ctx,{bedId:bed.id})) : null,
          )},
        ]}));
      return;
    }
    const visibleGroups = [...groups.values()].filter(group => group.rooms.length);
    cards.replaceChildren(...(visibleGroups.length ? visibleGroups.map(renderGroup)
      : [node('div', 'fx-empty fx-panel', '没有符合条件的床位')]));
  }

  const statuses = new Set(['已入住','空闲',...ctx.state.beds.map(b=>b.status).filter(Boolean)]);
  for (const [value, title] of [['', '全部床位'], ...[...statuses].map(status=>[status,status])]) {
    const button = node('button', '', title);
    button.type = 'button';
    button.dataset.value = value;
    button.addEventListener('click', () => { view.status = value; draw(); });
    statusBar.append(button);
  }
  building.addEventListener('change', () => {
    view.building = building.value;
    view.campus = view.floor = view.room = view.area = '';
    view.limit = 0;
    fillFloors();
    fillAreas();
    draw();
  });
  floor.addEventListener('change',()=>{view.floor=floor.value;view.room='';view.limit=0;fillAreas();draw();});
  area.addEventListener('change', () => { view.area = area.value; draw(); });
  capacity.addEventListener('change', () => { view.capacity = capacity.value; view.limit = 0; draw(); });
  order.addEventListener('change', () => { view.order = order.value; draw(); });
  search.addEventListener('input', event => {
    if (!event.isComposing) { view.query = search.value; draw(); }
  });
  search.addEventListener('compositionend', () => { view.query = search.value; draw(); });
  fillBuildings();
  fillFloors();
  fillAreas();
  draw();
  const panel = node('div', 'fx-profile bed-list', [metrics, controls, cards]);

  // Include empty buildings in the selector without making the bed cards wait for a second response.
  ctx.get('/api/facility').then(result => {
    checkedBuildings = true;
    for (const item of result.buildings) directory.set(item.id, scopeText(item.campusName, item.name));
    fillBuildings();
    fillAreas();
    draw();
  }).catch(() => {});
  if (view.limit) {
    const query = new URLSearchParams({limit: String(view.limit)});
    for (const [name, value] of Object.entries({
      bedCount: view.capacity, campusId: view.campus, buildingId: view.building, floorId: view.floor, roomId: view.room,
    })) if (value) query.set(name, value);
    ctx.get('/api/facility/rooms?' + query).then(result => {
      if (!view.limit) return;
      selectedRooms = new Set(result.rooms.map(room => room.id));
      draw();
    }).catch(() => {});
  }
  return panel;
}

export function beds(ctx) {
  return page(
    ctx,
    '床位管理',
    '',
    canAct(ctx, 'care.completeTask') ? btn(ctx, '床旁核验', () => bedside(ctx), 'primary') : null,
    tabs('beds', [
      ['all', '全部床位', () => allBeds(ctx)],
      ['plan', '楼层平面图', () => roomsPage(ctx, true)],
      ['zones', '区域设置', () => careAreas(ctx)]
    ])
  );
}
export function renewalReminders(residents) {
  return residents
    .filter((r) => r.status === '在住' && !isTrial(r) && renewalReasons[r.renewalReminder?.reason])
    .sort((a, b) => a.renewalReminder.at.localeCompare(b.renewalReminder.at));
}
