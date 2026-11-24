import {
  hasGrant,
  kpis,
  link,
  money,
  node,
  records,
  residentName,
  table,
  today,
} from './shared.js';
function sumMoney(rows, key) {
  return rows.reduce((total, row) => total + Math.round(row[key] * 100), 0) / 100;
}

export function monthlyPanel(ctx) {
  const state = ctx.state;
  const picker = node('input', 'fx-input');
  picker.type = 'month';
  picker.value = today(ctx).slice(0, 7);
  picker.max = picker.value;
  const body = node('div', 'fx-page');
  function draw() {
    const month = picker.value;
    if (!month || !picker.checkValidity()) {
      body.replaceChildren(ctx.ui.empty('请选择截至本月的有效月份'));
      return;
    }
    const inMonth = (row) => row.date?.slice(0, 7) === month;
    const bills = state.bills.filter((b) => b.month === month);
    const deposits = state.depositEntries.filter(inMonth);
    const payments = state.payments.filter(inMonth);
    const cash = payments.filter((p) => p.method === '线下登记');
    const offsets = payments.filter((p) => p.method === '预交金冲抵');
    const tasks = state.tasks.filter((t) => inMonth(t) && t.status !== '已取消');
    const completed = tasks.filter((t) => t.status === '已完成');
    const goods = state.transactions.filter((t) => inMonth(t) && t.type === '出库');
    const paymentsDetail = () =>
      ctx.detail(
        month + ' · 入款凭证',
        records(
          [
            ...cash.map((p) => ({
              ...p,
              channel: '线下核销',
            })),
            ...deposits.map((p) => ({
              ...p,
              channel: '预交到账',
            })),
          ].sort((a, b) => b.date.localeCompare(a.date)),
          (p) =>
            p.date +
            ' · ' +
            residentName(ctx, p.residentId) +
            ' · ' +
            p.channel +
            ' ' +
            money(p.amount) +
            ' · ' +
            p.id
        )
      );
    const ranges = [
      ...(hasGrant(ctx, 'finance')
        ? [
            [
              '账期应收',
              money(sumMoney(bills, 'amount')),
              bills.length + ' 笔账单',
              () =>
                ctx.detail(
                  month + ' · 账单明细',
                  records(
                    bills,
                    (b) =>
                      residentName(ctx, b.residentId) +
                      ' · ' +
                      b.id +
                      ' · ' +
                      money(b.amount) +
                      '，当前待缴 ' +
                      money(b.balance)
                  )
                ),
            ],
            [
              '当月实际入款',
              money(sumMoney(cash, 'amount') + sumMoney(deposits, 'amount')),
              '按到账日期汇总',
              paymentsDetail,
            ],
            [
              '预交金冲抵',
              money(sumMoney(offsets, 'amount')),
              '已计入对应账单的核销',
              () =>
                ctx.detail(
                  month + ' · 冲抵明细',
                  records(
                    offsets,
                    (p) =>
                      p.date +
                      ' · ' +
                      residentName(ctx, p.residentId) +
                      ' · ' +
                      p.billId +
                      ' · ' +
                      money(p.amount)
                  )
                ),
            ],
          ]
        : []),
      ...(hasGrant(ctx, 'care')
        ? [
            [
              '计划工单完成',
              completed.length + ' / ' + tasks.length + ' 项',
              '按计划日期汇总',
              () =>
                ctx.detail(
                  month + ' · 照护明细',
                  table(ctx, {
                    title: '工单记录',
                    rows: tasks,
                    search: {
                      value: (t) => t.title + ' ' + residentName(ctx, t.residentId),
                    },
                    cols: [
                      {
                        label: '日期',
                        view: (t) => t.date,
                      },
                      {
                        label: '长者',
                        view: (t) => residentName(ctx, t.residentId),
                      },
                      {
                        label: '工单',
                        view: (t) => t.title,
                      },
                      {
                        label: '状态',
                        view: (t) => t.status,
                      },
                    ],
                  })
                ),
            ],
          ]
        : []),
    ];
    const breakdown = table(ctx, {
      title: '月度经营指标',
      rows: ranges,
      cols: [
        {
          label: '指标',
          view: (r) => r[0],
        },
        {
          label: '合计',
          view: (r) => r[1],
        },
        {
          label: '口径',
          view: (r) => r[2],
        },
        {
          label: '明细',
          align: 'end',
          view: (r) => link(ctx, '查看凭证', r[3]),
        },
      ],
    });
    const usage = state.inventory
      .map((item) => ({
        item,
        rows: goods.filter((t) => t.itemId === item.id),
      }))
      .filter((s) => s.rows.length);
    const consumption = table(ctx, {
      title: '物资领用',
      rows: usage,
      cols: [
        {
          label: '物资',
          view: (g) => g.item.name,
        },
        {
          label: '出库量',
          view: (g) => g.rows.reduce((a, t) => a + t.quantity, 0) + ' ' + g.item.unit,
        },
        {
          label: '单据',
          view: (g) => g.rows.length + ' 笔',
        },
        {
          label: '明细',
          align: 'end',
          view: (g) =>
            link(ctx, '查看流水', () =>
              ctx.detail(
                g.item.name + ' · ' + month,
                records(
                  g.rows,
                  (t) => t.date + ' · ' + t.quantity + ' ' + g.item.unit + ' · ' + t.note
                )
              )
            ),
        },
      ],
    });
    body.replaceChildren(
      ...(hasGrant(ctx, 'finance')
        ? [
            kpis([
              ['本期账单当前待缴', money(sumMoney(bills, 'balance'))],
              ['预交到账', money(sumMoney(deposits, 'amount'))],
              ['线下直接收款', money(sumMoney(cash, 'amount'))],
            ]),
          ]
        : []),
      ...(ranges.length ? [breakdown] : []),
      ...(hasGrant(ctx, 'inventory') ? [consumption] : [])
    );
  }
  picker.addEventListener('input', draw);
  const label = node('label', 'fx-actions', [node('span', '', '经营月份'), picker]);
  draw();
  return node('section', 'fx-page', [label, body]);
}
