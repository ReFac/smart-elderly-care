import {
  node,
  page,
  table,
  tabs,
  kpis,
  field,
  select,
  options,
  residentField,
  residentName,
  choose,
  btn,
  link,
  named,
  badge,
  runForm,
  facts,
  section,
  records,
  today,
  money,
} from './shared.js';

import { chargesEditor, feeLedger, lineDescription } from './charge-lines.js';
import { channelOrders, expensePanel, reminders } from './settlements.js';

function generate(ctx) {
  const resident = select(
    'residentId',
    '长者',
    ctx.state.residents.filter(r=>r.admittedAt).map((r) => ({
      value: r.id,
      label: r.name + ' · ' + r.status,
    }))
  );
  const month = today(ctx).slice(0, 7);
  const unbilled = ctx.state.residents.find(
    (r) =>
      r.status === '在住' &&
      !ctx.state.bills.some((b) => b.residentId === r.id && b.month === month)
  );
  if (unbilled) resident.value = unbilled.id;
  if (!ctx.state.allowedActions.includes('ops.bill')) return ctx.toast('当前账号无权核算账单');
  const editor=chargesEditor(ctx);
  ctx.dialog({
    title:'核算月度账单',
    content:editor.element,
    async onSubmit(values) {
      const payload=Object.fromEntries(Object.entries(values).filter(([,v])=>v!==''));
      payload.items=editor.read();
      const response=await fetch('/api/billing/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload,revision:ctx.state.revision})});
      const quote=await response.json();
      if (!response.ok) throw new Error(quote.error||'无法核算');
      return ctx.command('ops.bill',payload,{title:'确认账单明细',target:residentName(ctx,payload.residentId)+' · '+quote.month,
        fields:[...quote.lineItems.map(l=>[l.label,lineDescription(l)]),['应收合计',money(quote.amount)]]});
    },
    description:
      '已退住按退住日截断，在住按月末预估。留空的日费率和请假天数使用床位、照护等级及请假台账的默认值。',
    submitLabel: '生成账单',
    fields: [
      resident,
      field('month', '账期', {
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
}

function deposit(ctx) {
  runForm(ctx, {
    title: '登记预交金',
    action: 'ops.deposit',
    description: '到账后按顺序冲抵该长者的待缴费用，剩余金额计入预交余额。',
    fields: [
      residentField(ctx),
      field('amount', '到账金额（元）', {
        type: 'number',
        min: '0.01',
        step: '0.01',
      }),
    ],
    submitLabel: '登记到账',
  });
}

function pay(ctx, bill) {
  runForm(ctx, {
    title: '登记线下收款',
    action: 'ops.pay',
    description:
      residentName(ctx, bill.residentId) + ' · ' + bill.month + ' 待缴 ' + money(bill.balance),
    fields: [
      field('amount', '实收金额（元）', {
        type: 'number',
        min: '0.01',
        max: bill.balance,
        step: '0.01',
        value: bill.balance,
      }),
      select('method', '登记方式', options(['线下登记'])),
    ],
    map: (v) => ({
      ...v,
      billId: bill.id,
    }),
    submitLabel: '确认核销',
  });
}

export function billDetail(ctx, bill) {
  const content = node('div', 'fx-profile', [
    facts([
      ['长者', residentName(ctx, bill.residentId)],
      ['账期', bill.month],
      ['计费区间', bill.startDate + ' 至 ' + bill.endDate],
      ['计费天数', String(bill.serviceDays)],
      ['期末等级快照', bill.careLevel],
      ['期末床位日费', money(bill.bedFee)],
      ['期末护理日费', money(bill.careFee)],
      ['月度套餐', money(bill.packageFee)],
      ['请假天数', String(bill.leaveDays)],
      ['应收总额', money(bill.amount)],
      ['已收总额', money(bill.paid)],
      ['待缴余额', money(bill.balance)],
    ]),
    section('全部收费明细',feeLedger(bill)),
    ...(bill.segments
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
        (p) => named(p.method + ' · ' + money(p.amount), p.date)
      )
    ),
  ]);
  if (bill.balance > 0) content.append(btn(ctx, '登记收款', () => pay(ctx, bill), 'primary'));
  ctx.detail('账单明细', content);
}

export function billing(ctx) {
  const bills = ctx.state.bills;
  return page(
    ctx,
    '财务管理',
    '按项核算房间床位、饮食、护理及约定费用，核对欠费和预交金。',
    choose(
      btn(ctx, '登记预交金', () => deposit(ctx)),
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
                view: (b) => residentName(ctx, b.residentId),
              },
              {
                label: '账期',
                view: (b) => b.month,
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
      ['orders', '渠道对账', () => channelOrders(ctx)],
      ['reminders', '欠费提醒', () => reminders(ctx)],
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
                view: (r) => residentName(ctx, r.residentId),
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
                        (e) => named(money(e.amount), e.date)
                      )
                    )
                  ),
              },
            ],
          }),
      ],
      [
        'payments',
        '收款流水',
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
                view: (r) => residentName(ctx, r.residentId),
              },
              {
                label: '账单编号',
                view: (r) => r.billId,
              },
              {
                label: '核销方式',
                view: (r) => r.method,
              },
              {
                label: '金额',
                view: (r) => money(r.amount),
              },
            ],
          }),
      ],
    ])
  );
}
