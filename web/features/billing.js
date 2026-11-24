import { residentLabel, residentAnchor } from './people-labels.js';
import {
  node,
  page,
  table,
  tabs,
  kpis,
  field,
  select,
  residentName,
  choose,
  btn,
  canAct,
  link,
  named,
  badge,
  facts,
  section,
  records,
  today,
  money,
} from './shared.js';

import { cashierActions, feeSettings, receiptDescription, recordCash } from './cashier.js';
import { receiptFacts, receiptLedger, receiptRows } from './receipt-ledger.js';
import { chargesEditor, feeLedger, lineDescription } from './charge-lines.js';
import { channelOrders, expensePanel, reminders } from './settlements.js';
import { billingPolicyFields } from './admission-fees.js';
import { billingNotices } from './billing-notices.js';

const billType = (bill) => {
  if (bill.kind === 'trial') return '一次性试住费';
  if (bill.kind === 'security') return '入住押金';
  return '月费';
};

function residentBillingPolicy(ctx, person) {
  const current = person.admissionTerms;
  return ctx.dialog({
    title: '账单提醒与押金设置',
    description: residentName(ctx, person.id) + ' · 提前天数填 0 时仅在账单日提醒。已出具的押金账单金额保持原约定。',
    fields: billingPolicyFields(current),
    onSubmit: ({ reminderDays, securityMode }) => ctx.command('ops.residentBillingPolicy', {
      residentId: person.id, reminderDays: Number(reminderDays), securityMode,
    }, {
      title: '确认账单提醒与押金设置', target: residentName(ctx, person.id),
      fields: [
        ['月费提醒', Number(reminderDays) ? '提前 ' + reminderDays + ' 天及账单日' : '账单日'],
        ['逾期处理', securityMode === 'overdue' ? '可按未用押金余额抵扣，继续提醒' : '按约定提醒'],
      ],
    }),
  });
}

function generate(ctx, selected, onIssued) {
  if (!ctx.state.allowedActions.includes('ops.bill')) return ctx.toast('当前账号无权核算账单');
  const due = new Map((ctx.state.billingDue || []).map((r) => [r.residentId, r]));
  const people = ctx.state.residents.filter((r) =>
    (!onIssued || r.id === selected.residentId) && r.admittedAt && r.stayType !== 'trial' && (!r.billingDay || due.has(r.id)));
  if (!people.length) return ctx.toast('当前没有可核算的月付账期');
  const resident = select(
    'residentId',
    '长者',
    people.map((r) => ({ value: r.id, label: residentLabel(ctx, r) + ' · ' + r.status })),
  );
  const month = today(ctx).slice(0, 7);
  const unbilled = people.find(
    (r) =>
      r.status === '在住' &&
      !ctx.state.bills.some((b) => !['trial', 'security'].includes(b.kind) && b.residentId === r.id && b.month === month)
  );
  resident.value = selected?.residentId || due.keys().next().value || unbilled?.id || people[0].id;
  const editor=chargesEditor(ctx);
  const schedule = node('p', 'fx-muted');
  schedule.setAttribute('aria-live', 'polite');
  const dialog = ctx.dialog({
    title:'核算月度账单',
    content:node('div', 'fx-profile', [schedule, editor.element]),
    async onSubmit(values) {
      const payload=Object.fromEntries(Object.entries(values).filter(([,v])=>v!==''));
      const cycle = due.get(payload.residentId);
      if (cycle) Object.assign(payload, { month: cycle.month, billingDate: cycle.billingDate });
      payload.items=editor.read();
      const response=await fetch('/api/billing/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload,revision:ctx.state.revision})});
      const quote=await response.json();
      if (!response.ok) throw new Error(quote.error||'无法核算');
      const done = await ctx.command('ops.bill',payload,{title:'确认账单明细',target:residentName(ctx,payload.residentId)+' · '+quote.month,
        fields:[['账单日期',quote.billingDate || quote.month], ['计费区间',quote.startDate + ' 至 ' + quote.endDate],
          ...quote.lineItems.map(l=>[l.label,lineDescription(l)]),['应收合计',money(quote.amount)]]});
      if (done && onIssued) onIssued(ctx.current(), payload.residentId);
      return done;
    },
    description:
      '按长者约定的账期核算。日费率和请假天数留空时，使用相应床位、照护等级及请假记录。',
    submitLabel: '生成账单',
    fields: [
      resident,
      field('month', '原自然月账期', {
        type: 'month',
        value: today(ctx).slice(0, 7),
        max: today(ctx).slice(0, 7),
      }),
      field('bedFee', '床位日费（元）', {
        type: 'number',
        required: false,
        min: 0,
        step: '0.01',
        placeholder: '按床位核算',
      }),
      field('careFee', '护理日费（元）', {
        type: 'number',
        required: false,
        min: 0,
        step: '0.01',
        placeholder: '按照护等级核算',
      }),
      field('packageFee', '月度套餐（元）', {
        type: 'number',
        min: 0,
        step: '0.01',
        value: '0',
      }),
      field('leaveDays', '请假天数', {
        type: 'number',
        required: false,
        min: 0,
        step: 1,
        placeholder: '按请假记录核算',
      }),
    ],
  });
  const form = dialog.querySelector('form');
  function sync() {
    const cycle = due.get(form.elements.residentId.value);
    form.elements.month.closest('label').hidden = form.elements.month.disabled = Boolean(cycle);
    schedule.textContent = cycle
      ? '本次账单日 ' + cycle.billingDate + ' · 计费区间 ' + cycle.startDate + ' 至 ' + cycle.endDate
      : '此档案沿用原自然月账期。请选择要核算的月份。';
  }
  form.elements.residentId.addEventListener('change', sync);
  sync();
}

export function admissionPayment(ctx, residentId) {
  if (!canAct(ctx, 'ops.pay') && !canAct(ctx, 'ops.paymentOrder')) return;
  const person = ctx.state.residents.find((r) => r.id === residentId);
  if (!person) return;
  const related = ctx.state.bills.filter((b) => b.residentId === residentId);
  const admission = person.admissionPayment;
  const bills = admission ? [admission.billId, admission.securityBillId]
    .map((id) => related.find((bill) => bill.id === id)).filter(Boolean) : related;
  const due = ctx.state.billingDue?.find((r) => r.residentId === residentId);
  const account = ctx.state.deposits.find((a) => a.residentId === residentId);
  const editable = canAct(ctx, 'ops.residentBillingPolicy') && person.admissionTerms &&
    person.status === '在住' && person.stayType === 'formal';
  const body = node('div', 'fx-profile', [
    facts([['长者', residentName(ctx, residentId)],
      ...(person.admissionStatus ? [['入住交费状态', person.admissionStatus]] : []), ['可用预缴金', money(account?.amount)]]),
    ...bills.map((bill) => section((admission && bill.kind !== 'trial' && bill.kind !== 'security' ? '首期月费' : billType(bill)) +
      ' · ' + (bill.billingDate || bill.month),
      node('div', '', [
        facts([['应缴', money(bill.amount)], ['已核销', money(bill.paid)], ['待缴', money(bill.balance)]]),
        choose(link(ctx, '查看费用明细', () => billDetail(ctx, bill)),
          bill.balance > 0 ? cashierActions(ctx, bill, true) : badge(ctx, '已结清')),
      ]))),
    choose(!admission && due && canAct(ctx, 'ops.bill') && btn(ctx, '核算入住首期账单并收款', () => generate(ctx, due, admissionPayment), 'primary'),
      canAct(ctx, 'ops.deposit') && btn(ctx, '登记已收预缴金', () => recordCash(ctx, { residentId })),
      editable && btn(ctx, '账单提醒与押金设置', () => residentBillingPolicy(ctx, person))),
  ]);
  ctx.detail('入住交费', body);
}

export function billDetail(ctx, bill) {
  const monthly = !['trial', 'security'].includes(bill.kind);
  const securityUsed = bill.kind === 'security'
    ? ctx.state.payments.filter((payment) => payment.securityBillId === bill.id).reduce((total, p) => total + p.amount, 0) : null;
  const content = node('div', 'fx-profile', [
    facts([
      ['长者', residentName(ctx, bill.residentId)],
      ['收费类型', billType(bill)],
      ['账期', bill.month],
      ...(bill.billingDate ? [['账单日期', bill.billingDate]] : []),
      ...(bill.endDate ? [['计费区间', bill.startDate + ' 至 ' + bill.endDate]] : []),
      ...(monthly ? [
        ['计费天数', String(bill.serviceDays)],
        ['期末等级快照', bill.careLevel],
        ['期末床位日费', money(bill.bedFee)],
        ['期末护理日费', money(bill.careFee)],
        ['月度套餐', money(bill.packageFee)],
        ['请假天数', String(bill.leaveDays)],
      ] : []),
      ['应收总额', money(bill.amount)],
      ['已核销总额', money(bill.paid)],
      ['待缴余额', money(bill.balance)],
      ...(securityUsed != null ? [['已用于账单冲抵', money(securityUsed)], ['在账押金余额', money((bill.paid || 0) - securityUsed)]] : []),
    ]),
    section('全部收费明细',feeLedger(bill)),
    ...(monthly && bill.segments
      ? [
          section(
            '分段计费依据',
            records(bill.segments, (s) =>
              named(
                s.start + ' 至 ' + s.end + ' · ' + (s.bedLabel || '床位未记载') + ' · ' + s.level,
                s.days +
                  ' 天，护理减免 ' +
                  s.leaveDays +
                  ' 天，床位 ' +
                  money(s.bedFee) +
                  '/日，护理 ' +
                  money(s.careFee) +
                  '/日'
              )
            )
          ),
          facts([
            ['床位合计', money(bill.bedTotal)],
            ['护理合计', money(bill.careTotal)],
            [
              '手工确认',
              bill.manualOverrides
                ?.map(
                  (k) => ({ bedFee: '床位日费', careFee: '护理日费', leaveDays: '减免天数' })[k]
                )
                .join('、') || '按业务记录核算',
            ],
          ]),
        ]
      : []),
    section(
      '核销流水',
      records(
        ctx.state.payments.filter((p) => p.billId === bill.id),
        (p) => named(p.method + ' · ' + money(p.amount), receiptDescription(p))
      )
    ),
  ]);
  const vouchers = receiptRows(ctx.state).filter((r) => r.billId === bill.id || r.bills.has(bill.id));
  if (vouchers.length) content.append(section('原始收款凭证', records(vouchers, (row) => receiptFacts(row, bill.id))));
  if (bill.balance > 0) content.append(cashierActions(ctx, bill));
  ctx.detail('账单明细', content);
}

export function billing(ctx) {
  const bills = ctx.state.bills;
  return page(
    ctx,
    '财务管理',
    '按项核算房间床位、饮食、护理及约定费用，核对欠费和预交金。',
    choose(
      ctx.state.allowedActions.includes('ops.paymentFees') && btn(ctx, '收款手续费设置', () => feeSettings(ctx)),
      btn(ctx, '登记预缴金', () => recordCash(ctx)),
      btn(ctx, '核算账单', () => generate(ctx), 'primary')
    ),
    kpis([
      ['累计应收', money(bills.reduce((s, b) => s + b.amount, 0))],
      ['已收金额', money(bills.reduce((s, b) => s + b.paid, 0))],
      ['待缴余额', money(bills.reduce((s, b) => s + b.balance, 0))],
    ]),
    tabs('billing', [
      [
        'bills',
        '收费账单',
        () =>
          table(ctx, {
            title: '账单明细',
            rows: bills,
            search: {
              placeholder: '搜索长者或账期',
              value: (b) => residentName(ctx, b.residentId) + ' ' + b.month,
            },
            filter: {
              value: (b) => b.status,
            },
            cols: [
              {
                label: '长者',
                view: (b) => residentAnchor(ctx, b.residentId),
              },
              {
                label: '账期',
                view: (b) => named(b.billingDate || b.month, billType(b)),
              },
              {
                label: '应收金额',
                view: (b) => money(b.amount),
              },
              {
                label: '待缴余额',
                view: (b) => money(b.balance),
              },
              {
                label: '状态',
                view: (b) => badge(ctx, b.status),
              },
              {
                label: '操作',
                align: 'end',
                view: (b) => link(ctx, '查看明细', () => billDetail(ctx, b)),
              },
            ],
          }),
      ],
      ['due', '待出月账单', () => table(ctx, {
        title: '已到账单日的月付账期',
        rows: ctx.state.billingDue || [],
        empty: '当前没有已到期且尚未出账的约定月付账期。',
        search: { placeholder: '搜索长者', value: (r) => residentName(ctx, r.residentId) },
        cols: [
          { label: '长者', view: (r) => residentAnchor(ctx, r.residentId) },
          { label: '本期账单日', view: (r) => r.billingDate },
          { label: '计费区间', view: (r) => r.startDate + ' 至 ' + r.endDate },
          { label: '操作', align: 'end', view: (r) => ctx.state.allowedActions.includes('ops.bill')
            ? link(ctx, '核算本期', () => generate(ctx, r)) : null },
        ],
      })],
      ['orders', '渠道对账', () => channelOrders(ctx)],
      ['reminders', '欠费提醒', () => reminders(ctx)],
      ['billingNotices', '账单日提醒', () => billingNotices(ctx, (bill) => billDetail(ctx, bill))],
      ['expenses', '支出登记', () => expensePanel(ctx)],
      [
        'deposits',
        '预交余额',
        () =>
          table(ctx, {
            title: '预交账户',
            rows: ctx.state.deposits,
            search: {
              placeholder: '搜索长者姓名',
              value: (r) => residentName(ctx, r.residentId),
            },
            cols: [
              {
                label: '长者',
                view: (r) => residentAnchor(ctx, r.residentId),
              },
              {
                label: '账户编号',
                view: (r) => r.id,
              },
              {
                label: '可用余额',
                view: (r) => money(r.amount),
              },
              {
                label: '操作',
                align: 'end',
                view: (r) =>
                  link(ctx, '到账记录', () =>
                    ctx.detail(
                      '预交金到账记录',
                      records(
                        ctx.state.depositEntries.filter((e) => e.residentId === r.residentId),
                        (e) => named(money(e.amount), receiptDescription(e))
                      )
                    )
                  ),
              },
            ],
          }),
      ],
      ['receipts', '实收流水', () => receiptLedger(ctx)],
      [
        'payments',
        '账单核销记录',
        () =>
          table(ctx, {
            title: '账单核销记录',
            rows: ctx.state.payments,
            search: {
              placeholder: '搜索长者或账单',
              value: (r) => residentName(ctx, r.residentId) + ' ' + r.billId,
            },
            filter: {
              value: (r) => r.method,
              all: '全部方式',
            },
            cols: [
              {
                label: '收款日期',
                view: (r) => r.date,
              },
              {
                label: '长者',
                view: (r) => residentAnchor(ctx, r.residentId),
              },
              {
                label: '账单编号',
                view: (r) => r.billId,
              },
              {
                label: '核销方式',
                view: (r) => [r.method, r.channel !== r.method && r.channel].filter(Boolean).join(' · '),
              },
              {
                label: '核销金额',
                view: (r) => money(r.amount),
              },
              { label: '机构手续费', view: (r) => r.feeAmount == null ? '—' : money(r.feeAmount) },
              {
                label: '净入账',
                view: (r) => r.netAmount == null ? '—' : money(r.netAmount),
              },
            ],
          }),
      ],
    ])
  );
}
