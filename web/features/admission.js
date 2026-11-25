import { residentLabel, residentAnchor } from './people-labels.js';
import {
  node,
  btn,
  badge,
  facts,
  field,
  money,
  named,
  select,
  options,
  choose,
  table,
  today,
  canAct,
} from './shared.js';
import { admissionPayment } from './billing.js';
import { profile } from './residency.js';
import { trialLength, trialLastDay, trialTermFields } from './trial-terms.js';
import { confirmStay, endTrial } from './trial-stays.js';
import { admissionFinance, admissionFinanceFields } from './admission-fees.js';

const statuses = { 未入住: '未入住', 在住: '在住', 已退住: '归档老人' };
export const isTrial = (row) => ['在住', '试住到期待确认'].includes(row.status) && row.stayType === 'trial';
export const statusLabel = (row) => isTrial(row) && row.bedId ? '试住中' : statuses[row.status] || row.status;
export const labelBedStay = (label, row) => row?.bedId && isTrial(row) ? label + ' · 试住中' : label;
const archived = (row) => row.status === '已退住';

const stayTypes = [
  { value: 'formal', label: '正式入住' },
  { value: 'trial', label: '试住' },
];

export function contractFields(day, endDate = '') {
  return [
    select('contractTerm', '合同期限', [
      { value: 'open', label: '无期限' },
      { value: 'fixed', label: '固定期限' },
    ], { value: endDate ? 'fixed' : 'open' }),
    field('endDate', '合同到期日', { type: 'date', min: day, value: endDate }),
  ];
}

export function bindContractFields(dialog) {
  const { contractTerm, endDate } = dialog.querySelector('form').elements;
  const update = () => {
    const fixed = contractTerm.value === 'fixed';
    endDate.disabled = !fixed;
    endDate.required = fixed;
    endDate.closest('label').hidden = !fixed;
  };
  contractTerm.addEventListener('change', update);
  update();
}

export const billingSchedule = (resident) => resident.billingDay
  ? '月付 · 每月 ' + resident.billingDay + ' 日'
  : '月付 · 原自然月账期';

export function monthlyDayField(day, defaultDay, eventName) {
  const anchor = Number(day.slice(-2));
  return select('billingDay', '月付账单日',
    Array.from({ length: 31 }, (_, i) => ({
      value: String(i + 1),
      label: '每月 ' + (i + 1) + ' 日' + (i + 1 === anchor ? '（' + eventName + '）' : ''),
    })), { value: String(defaultDay || anchor) });
}

export function bindAdmissionDate(dialog, eventName, { preserveBillingDay = false, contractMin = '' } = {}) {
  const { admittedAt, billingDay, endDate } = dialog.querySelector('form').elements;
  let billingDayEdited = preserveBillingDay;
  billingDay.addEventListener('change', () => { billingDayEdited = true; });
  const sync = () => {
    if (!admittedAt.value) return;
    const anchor = Number(admittedAt.value.slice(-2));
    for (const option of billingDay.options) {
      option.textContent = '每月 ' + option.value + ' 日' + (Number(option.value) === anchor ? '（' + eventName + '）' : '');
    }
    if (!billingDayEdited) billingDay.value = String(anchor);
    endDate.min = admittedAt.value > contractMin ? admittedAt.value : contractMin;
  };
  admittedAt.addEventListener('change', sync);
  sync();
}

export function register(ctx, inquiry) {
  const notify = node('div', 'admission-match');
  notify.setAttribute('aria-live', 'polite');
  const day = today(ctx);
  const oldest = new Date(day + 'T00:00:00Z');
  oldest.setUTCDate(oldest.getUTCDate() - 364);
  const dialog = ctx.dialog({
    title: '新建长辈档案',
    content: notify,
    fields: [
      field('name', '姓名', { value: inquiry?.name || '', maxLength: 60 }),
      select('kind', '档案类别', [
        { value: 'new', label: '新档案 · 等待入住' },
        { value: 'archive', label: '归档老人 · 仅保管资料' },
      ]),
      ...(ctx.state.campusOptions?.length
        ? [
            select(
              'campusId',
              '建档分院',
              ctx.state.campusOptions.map((c) => ({ value: c.id, label: c.name })),
              { value: inquiry?.campusId }
            ),
          ]
        : []),
      select('gender', '性别', options(['未登记', '女', '男'])),
      select(
        'age',
        '年龄',
        [
          { value: '', label: '未登记' },
          ...Array.from({ length: 126 }, (_, i) => ({ value: String(i), label: i + ' 岁' })),
        ],
        { required: false }
      ),
      field('archiveDate', '原退住或归档日期', {
        type: 'date',
        value: day,
        min: oldest.toISOString().slice(0, 10),
        max: day,
        required: false,
      }),
    ],
    submitLabel: '建立档案',
    onSubmit: (v) => {
      const payload = { ...v, name: v.name.trim() };
      if (!payload.age) delete payload.age;
      if (v.kind !== 'archive') delete payload.archiveDate;
      if (inquiry) payload.inquiryId = inquiry.id;
      const same = matching(payload.name);
      if (same.length) payload.acknowledgeArchive = true;
      return ctx.command('care.register', payload, {
        title: same.length ? '核实与归档老人的身份并建立独立档案' : '建立长辈档案',
        target: payload.name,
        fields: [
          ['类别', v.kind === 'archive' ? '归档老人，保管 365 天' : '未入住，建档后可分床'],
          ...(same.length ? [['同名归档', same.map((x) => residentLabel(ctx, x) + ' · ' + x.id).join('、')]] : []),
          ...(v.kind === 'archive' ? [['归档日期', v.archiveDate || day]] : []),
        ],
      });
    },
  });
  function matching(name) {
    return ctx.state.residents.filter((r) => archived(r) && r.name === name.trim());
  }
  const controls = dialog.querySelector('form').elements;
  const show = () => {
    controls.archiveDate.closest('label').hidden = controls.kind.value !== 'archive';
    controls.archiveDate.disabled = controls.kind.value !== 'archive';
    const rows = matching(controls.name.value);
    notify.replaceChildren();
    if (rows.length) {
      notify.append(
        node('strong', '', '发现同名归档老人，请核对档案号。'),
        ...rows.map(r => node('div', '', [residentAnchor(ctx, r), ' · ' + r.id + ' · ' + (r.dischargedAt || '历史归档')]))
      );
    }
  };
  controls.kind.onchange = show;
  controls.name.oninput = show;
  show();
  controls.name.focus();
}

function bedLabel(ctx, id) {
  const bed = ctx.state.beds.find((b) => b.id === id);
  const place = ctx.state.bedLocations?.[id];
  return bed ? [...(place || [bed.ward]), bed.label].filter(Boolean).join(' / ') : '—';
}

export function allocate(ctx, person, targetBed, stayType = 'formal') {
  if (!person) {
    ctx.detail('选择长辈档案', registry(ctx, { bed: targetBed, stayType }));
    return;
  }
  if (archived(person)) {
    profile(ctx, person);
    return;
  }
  if (isTrial(person) && !person.bedId) return confirmStay(ctx, person, targetBed);
  const transfer = person.status === '在住';
  const free = ctx.state.beds.filter((b) => b.status === '空闲' && !b.residentId);
  if (!free.length) {
    ctx.toast('当前范围暂无可分配的空闲床位');
    return;
  }
  const action = transfer ? 'care.transfer' : 'care.admit';
  const day = today(ctx);
  const finance = !transfer && admissionFinance(ctx, action, ({ contractTerm, ...terms }) => {
    const payload = { residentId: person.id, ...terms };
    if (terms.stayType === 'trial') {
      payload.trialDays = Number(terms.trialDays);
      payload.trialPrice = Number(terms.trialPrice);
    } else payload.billingDay = Number(terms.billingDay);
    if (contractTerm !== 'fixed') delete payload.endDate;
    return payload;
  });
  const dialog = ctx.dialog({
    title: transfer ? '转移床位' : '从档案办理入住',
    description:
      residentLabel(ctx, person) +
      ' · 档案 ' +
      person.id +
      (transfer ? ' · 当前床位 ' + bedLabel(ctx, person.bedId) : ''),
    fields: [
      select(
        'bedId',
        transfer ? '新床位' : '入住床位',
        free.map((b) => ({ value: b.id, label: bedLabel(ctx, b.id) })),
        { value: targetBed?.id }
      ),
      ...(!transfer
        ? [
            select('stayType', '入住方式', stayTypes, { value: stayType }),
            select('level', '照护等级', options(['自理', '半失能', '失能']), {
              value: person.level,
            }),
            field('admittedAt', '入住日期', { type: 'date', value: day, max: day }),
            ...trialTermFields(ctx.state.trialSettings),
            monthlyDayField(day, null, '入住日'),
            ...contractFields(day),
            ...admissionFinanceFields(ctx),
          ]
        : []),
    ],
    submitLabel: transfer ? '核对转床' : '核对入住',
    onSubmit: async (values) => {
      const quote = transfer ? null : await finance.review(values);
      const payload = quote?.payload || { residentId: person.id, fromBedId: person.bedId, bedId: values.bedId };
      const fields = transfer
        ? [
            ['原床位', bedLabel(ctx, person.bedId)],
            ['新床位', bedLabel(ctx, payload.bedId)],
            ['床位变动', '确认后立即释放原床位并登记新床位。'],
          ]
        : [
            ['长辈档案', residentLabel(ctx, person) + ' · ' + person.id],
            ['入住方式', payload.stayType === 'trial' ? '试住' : '正式入住'],
            ['入住床位', bedLabel(ctx, payload.bedId)],
            ['照护等级', payload.level],
            ...(payload.stayType === 'trial'
              ? [
                ['约定试住', trialLength(payload.trialDays) + ' · 至 ' + trialLastDay(payload.admittedAt, payload.trialDays)],
              ]
              : [['收费约定', billingSchedule(payload)], ['合同期限', payload.endDate || '无期限']]),
            ...quote.fields,
          ];
      const done = await ctx.command(action, payload, {
        title: transfer ? '确认将' + residentLabel(ctx, person) + '从原床位转至新床位？' : '确认从档案办理入住',
        target: residentLabel(ctx, person),
        fields,
        expectedRevision: quote?.expectedRevision,
        confirmLabel: transfer ? '确认转床' : payload.stayType === 'trial' ? '确认试住' : '确认入住',
      });
      if (done && !transfer) admissionPayment(ctx.current(), person.id);
      return done;
    },
  });
  if (!transfer) {
    bindAdmissionDate(dialog, '入住日');
    bindContractFields(dialog);
    finance.mount(dialog);
    const form = dialog.querySelector('form');
    const controls = form.elements;
    const heading = dialog.querySelector('.dialog-head h2');
    const submit = form.querySelector('button[type=submit]');
    const hint = node('small', 'fx-muted', '遇短月时按当月最后一天出账。');
    controls.billingDay.closest('label').append(hint);
    const dates = node('small', 'fx-muted');
    dates.setAttribute('aria-live', 'polite');
    controls.trialDays.closest('label').append(dates);
    const sync = () => {
      const trial = controls.stayType.value === 'trial';
      const title = trial ? '办理试住' : '从档案办理入住';
      heading.textContent = title;
      dialog.setAttribute('aria-label', title);
      submit.textContent = trial ? '核对试住' : '核对入住';
      for (const input of [controls.trialDays, controls.trialPrice])
        input.closest('label').hidden = input.disabled = !trial;
      for (const input of [controls.billingDay, controls.contractTerm, controls.endDate]) {
        const hidden = trial || (input === controls.endDate && controls.contractTerm.value !== 'fixed');
        input.closest('label').hidden = input.disabled = hidden;
      }
      dates.textContent = '预计试住结束日 ' + trialLastDay(controls.admittedAt.value || day, controls.trialDays.value);
    };
    controls.stayType.addEventListener('change', sync);
    controls.trialDays.addEventListener('change', sync);
    controls.admittedAt.addEventListener('change', sync);
    sync();
  }
}

const registryFilters = [
  ['pending', '待办理', r => r.status === '未入住' || isTrial(r)],
  ['notAdmitted', '待入住', r => r.status === '未入住'],
  ['trials', '试住', isTrial],
  ['trial-expired', '试住期满待确认', r => isTrial(r) && !r.bedId],
  ['in-house', '正式在住', r => r.status === '在住' && !isTrial(r)],
  ['archived', '归档老人', r => ['已退住', '归档到期'].includes(r.status)],
  ['all-statuses', '全部状态', () => true],
];

function stayArrangement(ctx, row) {
  const bed = row.bedId ? bedLabel(ctx, row.bedId) : '未分配床位';
  if (isTrial(row)) {
    const term = [
      row.trialDays ? trialLength(row.trialDays) : '试住',
      [row.admittedAt, row.trialEndsAt].filter(Boolean).join(' 至 '),
      row.trialPrice == null ? '' : money(row.trialPrice),
    ].filter(Boolean).join(' · ');
    return named(row.bedId ? labelBedStay(bed, row) : '试住床位已释放', term);
  }
  if (row.dischargedAt) return named(row.dischargedAt, '退住归档');
  return row.admittedAt ? named(bed, row.admittedAt + ' 入住') : bed;
}

function showTrial(ctx, row) {
  const active = isTrial(row);
  const recorded = active || row.trialEndsAt || row.trialDays;
  const state = active ? (row.bedId ? '试住中' : '期满待确认')
    : row.formalizedAt ? '已转正式入住' : '试住已结束';
  const details = recorded ? facts([
    ['状态', state],
    ['试住开始日', row.admittedAt],
    ['约定结束日', row.trialEndsAt],
    ...(row.trialDays ? [['试住时长', trialLength(row.trialDays)]] : []),
    ...(row.trialPrice == null ? [] : [['一次性试住费', money(row.trialPrice)]]),
    ...(active ? [['床位', row.bedId ? labelBedStay(bedLabel(ctx, row.bedId), row) : '试住床位已释放']] : []),
    ...(row.formalizedAt ? [['正式入住生效日', row.formalizedAt]] : []),
  ]) : ctx.ui.empty('该长辈暂无试住记录。');
  ctx.detail('试住记录', node('div', 'fx-profile', [
    node('strong', '', residentLabel(ctx, row)), details,
  ]));
}

function registryActions(ctx, row, { bed, stayType, workbench }) {
  const trial = isTrial(row);
  const pending = row.status === '未入住' && !row.bedId;
  const canAdmit = pending && canAct(ctx, 'care.admit');
  return choose(
    workbench && (pending || trial || row.trialEndsAt || row.trialDays)
      ? btn(ctx, '试住', () => showTrial(ctx, row), 'ghost') : null,
    canAdmit ? btn(ctx, workbench || stayType === 'formal' ? '办理入住' : '办理试住',
      () => allocate(ctx, row, bed, workbench ? 'formal' : stayType), 'ghost') : null,
    workbench && canAdmit ? btn(ctx, '办理试住', () => allocate(ctx, row, bed, 'trial'), 'ghost') : null,
    trial && canAct(ctx, 'care.confirmStay') ? btn(ctx, workbench ? '办理入住' : '确认入住',
      () => confirmStay(ctx, row, bed), 'ghost') : null,
    trial && canAct(ctx, 'care.endTrial') ? btn(ctx, '取消入住', () => endTrial(ctx, row), 'ghost') : null,
    row.status === '在住' && row.bedId && (!trial || bed) && canAct(ctx, 'care.transfer')
      ? btn(ctx, '转床', () => allocate(ctx, row, bed), 'ghost') : null,
    !bed && !trial && row.status === '在住' && row.admissionStatus && canAct(ctx, 'ops.pay')
      ? btn(ctx, '入住交费', () => admissionPayment(ctx, row.id), 'ghost') : null,
    btn(ctx, '查看档案', () => profile(ctx, row), 'ghost'),
  );
}

export function registry(ctx, { bed = null, stayType = 'formal', workbenchStatus, onStatusChange } = {}) {
  const workbench = workbenchStatus !== undefined;
  const panel = node('div', 'admission-registry');
  const search = node('input', 'fx-input');
  search.type = 'search';
  search.placeholder = '搜索所有档案的姓名、姓氏或档案号';
  search.setAttribute('aria-label', search.placeholder);
  const body = node('div'),
    scope = node('small', 'fx-muted'),
    toggle = node('button', 'btn btn-ghost admission-all');
  toggle.type = 'button';
  const status = node('select', 'fx-input');
  status.setAttribute('aria-label', '入住状态');
  for (const [value, label] of registryFilters) status.add(new Option(label, value));
  status.value = registryFilters.some(([key]) => key === workbenchStatus) ? workbenchStatus : 'pending';
  let all = false;
  function draw() {
    const term = search.value.trim().normalize('NFKC').toLocaleLowerCase();
    const selected = registryFilters.find(([key]) => key === status.value) || registryFilters[0];
    const people = [...ctx.state.residents]
      .reverse()
      .filter((r) =>
        term
          ? (residentLabel(ctx, r) + ' ' + r.id).normalize('NFKC').toLocaleLowerCase().includes(term)
          : workbench ? selected[2](r) : all || r.status === '未入住' || isTrial(r)
      );
    if (!term && workbench && ['trials', 'trial-expired'].includes(selected[0]))
      people.sort((a, b) => (a.trialEndsAt || '').localeCompare(b.trialEndsAt || ''));
    status.disabled = Boolean(term);
    scope.textContent = term ? '搜索范围 · 全部档案' : workbench
      ? selected[0] === 'pending' ? '含待入住与试住档案' : ''
      : all ? '全部档案' : '待入住 · 含试住待确认档案';
    toggle.hidden = !!term;
    toggle.textContent = all ? '仅查看待入住档案' : '查看全部档案（含在住及归档老人）';
    body.replaceChildren(
      table(ctx, {
        title: term ? '搜索结果' : workbench ? '入住登记' : all ? '全部档案' : '待入住档案',
        rows: people,
        empty: term
          ? '没有找到匹配档案，可尝试姓名中的一个字。'
          : workbench ? '当前没有该状态的入住档案。'
          : all
            ? '暂无长辈档案。'
            : '暂无待入住档案，可新建档案或查看下方全部档案。',
        cols: [
          {
            label: '长辈',
            view: (r) =>
              node('div', 'fx-named', [node('strong', '', residentAnchor(ctx, r)), node('small', '', r.id)]),
          },
          { label: '状态', view: (r) => choose(
            badge(ctx, workbench && isTrial(r) && !r.bedId ? '期满待确认' : statusLabel(r),
              workbench && isTrial(r) && !r.bedId ? 'amber' : undefined),
            !isTrial(r) && r.admissionStatus === '欠费临时入住' ? badge(ctx, r.admissionStatus, 'amber') : null,
          ) },
          {
            label: workbench ? '床位与入住安排' : '床位 / 归档日期',
            view: (r) => workbench ? stayArrangement(ctx, r) : (r.bedId ? bedLabel(ctx, r.bedId) : r.dischargedAt || '—'),
          },
          {
            label: '操作',
            align: 'end',
            view: (r) => registryActions(ctx, r, { bed, stayType, workbench }),
          },
        ],
      })
    );
  }
  search.oninput = draw;
  status.onchange = () => {
    onStatusChange?.(status.value);
    draw();
  };
  toggle.onclick = () => {
    all = !all;
    draw();
  };
  const entryFilter = workbench
    ? node('label', 'admission-state-filter', [node('span', '', '入住状态'), status]) : null;
  panel.append(node('div', 'admission-search', [search, entryFilter, scope]), body);
  if (!workbench) panel.append(toggle);
  draw();
  return panel;
}

export function historicInquiries(ctx) {
  const items = ctx.state.inquiries.filter((q) => q.status === '待跟进' && !q.residentId);
  if (!canAct(ctx, 'care.register') || !items.length) return null;
  const rows = items.map((i) =>
    node('li', '', [
      node('span', '', i.name + ' · ' + i.date),
      btn(ctx, '以咨询建档', () => register(ctx, i), 'ghost'),
    ])
  );
  return node('details', 'fx-disclosure', [
    node('summary', 'fx-disclosure-head', '待关联的历史入住咨询（' + items.length + '）'),
    node('ul', 'fx-records', rows),
  ]);
}
