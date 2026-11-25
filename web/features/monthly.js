import { residentAnchor } from './people-labels.js';
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
import { isDirectReceipt } from './receipt-ledger.js';
const receiptCount = (rows) => new Set(rows.map((row) => row.receiptId || row.id)).size;

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
    const cash = payments.filter(isDirectReceipt);
    const expenses = (state.expenses || []).filter(inMonth);
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
              channel: p.method,
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
              '机构实际支出',
              money(sumMoney(expenses, 'amount')),
              expenses.length + ' 笔支出凭证',
              () =>
                ctx.detail(
                  month + ' · 支出凭证',
                  records(
                    expenses,
                    (r) =>
                      r.date +
                      ' · ' +
                      r.voucher +
                      ' · ' +
                      r.payee +
                      ' · ' +
                      r.note +
                      ' · ' +
                      money(r.amount)
                  )
                ),
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
                        label: '长辈',
                        view: (t) => residentAnchor(ctx, t.residentId),
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
              ['直接收款', money(sumMoney(cash, 'amount'))],
              [
                '本月收支净额',
                money(
                  sumMoney(cash, 'amount') +
                    sumMoney(deposits, 'amount') -
                    sumMoney(expenses, 'amount')
                ),
              ],
            ]),
          ]
        : []),
      compareMonths(ctx, month),
      ...(ranges.length ? [breakdown] : []),
      ...(hasGrant(ctx, 'inventory') ? [consumption] : [])
    );
  }
  picker.addEventListener('input', draw);
  const label = node('label', 'fx-actions', [node('span', '', '经营月份'), picker]);
  draw();
  return node('section', 'fx-page', [label, body]);
}

function compareMonths(ctx, month) {
  const state = ctx.state;
  const [year, m] = month.split('-').map(Number);
  const prevEnd = new Date(Date.UTC(year, m - 1, 0));
  const prior = prevEnd.toISOString().slice(0, 7);
  const now = today(ctx);
  const currentEnd =
    month === now.slice(0, 7) ? now : new Date(Date.UTC(year, m, 0)).toISOString().slice(0, 10);
  const priorEnd =
    month === now.slice(0, 7)
      ? prior + '-' + String(Math.min(Number(now.slice(-2)), prevEnd.getUTCDate())).padStart(2, '0')
      : prevEnd.toISOString().slice(0, 10);
  const included = (r, start, end) => r.date?.startsWith(start) && r.date <= end;
  const data = [];
  function metric(label, rows, measure, format, detail, analyze) {
    const cur = rows.filter((r) => included(r, month, currentEnd));
    const prev = rows.filter((r) => included(r, prior, priorEnd));
    const a = measure(cur),
      b = measure(prev);
    const change = Math.round((a - b) * 100) / 100;
    data.push({
      label,
      a: format(a),
      b: format(b),
      change: (change > 0 ? '+' : '') + format(change),
      assessment: analyze(cur, prev, change),
      show: () =>
        ctx.detail(
          label + ' · 环比依据',
          node('div', 'fx-page', [
            node('h3', '', month + ' 至 ' + currentEnd),
            records(cur, detail),
            node('h3', '', prior + ' 至 ' + priorEnd),
            records(prev, detail),
          ])
        ),
    });
  }
  if (hasGrant(ctx, 'finance')) {
    const cash = [
      ...state.depositEntries,
      ...state.payments.filter(isDirectReceipt),
    ];
    const describe = (r) => r.date + ' · ' + (r.voucher || r.id) + ' · ' + money(r.amount);
    metric('实际入款', cash, (r) => sumMoney(r, 'amount'), money, describe, (cur, prev, delta) => {
      if (!cur.length && !prev.length) return '两期均无入款凭证';
      const receipts = receiptCount(cur) + ' 笔到账，上期 ' + receiptCount(prev) + ' 笔';
      return delta < 0 ? receipts + '。可按账期核对待缴明细' : receipts;
    });
    metric('机构支出', state.expenses || [], (r) => sumMoney(r, 'amount'), money, describe, (cur) => {
      if (!cur.length) return '本期尚无支出凭证';
      const groups = new Map();
      for (const row of cur) {
        groups.set(row.category, (groups.get(row.category) || 0) + Math.round(row.amount * 100));
      }
      const [label, cents] = [...groups].sort((a, b) => b[1] - a[1])[0];
      return '支出最多为' + label + '，合计 ' + money(cents / 100);
    });
  }
  if (hasGrant(ctx, 'care')) {
    metric(
      '已完成护理工单',
      state.tasks.filter((t) => t.status === '已完成'),
      (r) => r.length,
      (n) => n + ' 项',
      (r) => r.date + ' · ' + r.title + ' · ' + r.id,
      () => {
        const pending = state.tasks.filter((r) =>
          included(r, month, currentEnd) && r.status === '待执行'
        ).length;
        return '当期计划中的 ' + pending + ' 项仍待执行';
      }
    );
  }
  if (hasGrant(ctx, 'inventory')) {
    metric(
      '领用单据',
      state.transactions.filter((t) => t.type === '出库'),
      (r) => r.length,
      (n) => n + ' 笔',
      (r) => r.date + ' · ' + r.id + ' · ' + r.note,
      (cur) => '本期共领用 ' + new Set(cur.map((r) => r.itemId)).size + ' 种物资'
    );
  }
  return table(ctx, {
    title: '月度经营诊断 · ' + currentEnd + ' / ' + priorEnd,
    rows: data,
    cols: [
      { label: '指标', view: (r) => r.label },
      { label: '本期', view: (r) => r.a },
      { label: '上期', view: (r) => r.b },
      { label: '增减', view: (r) => r.change },
      { label: '经营观察', view: (r) => r.assessment },
      { label: '依据', view: (r) => link(ctx, '对比明细', r.show) },
    ],
  });
}
