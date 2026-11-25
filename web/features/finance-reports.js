import { displayLocale } from '../lib/locale.js';
import {
  badge,
  btn,
  canAct,
  choose,
  facts,
  field,
  kpis,
  link,
  money,
  node,
  records,
  residentName,
  section,
  select,
  table,
  today,
} from './shared.js';
import { residentAnchor } from './people-labels.js';
import { receiptRows, receiptFacts } from './receipt-ledger.js';

const cents = (amount) => Math.round(Number(amount || 0) * 100);
const yuan = (value) => money(value / 100);
const sum = (rows, field) => rows.reduce((n, r) => n + cents(r[field]), 0);

function printReport(ctx, title, body) {
  const sheet = node('section', 'subsidy-print-sheet', [
    node('h1', '', title),
    node('p', '', [
      ctx.state.uiSettings.institutionName,
      ' · 经办人 ',
      ctx.state.user.displayName,
      ' · 打印时间 ',
      new Date().toLocaleString(displayLocale),
    ]),
    body,
  ]);
  document.body.append(sheet);
  try {
    window.print();
  } finally {
    sheet.remove();
  }
}
function financialTable(headers, rows) {
  return node('table', 'fx-table', [
    node(
      'thead',
      '',
      node(
        'tr',
        '',
        headers.map((h) => node('th', '', h)),
      ),
    ),
    node(
      'tbody',
      '',
      rows.map((r) =>
        node(
          'tr',
          '',
          r.map((cell) => node('td', '', cell)),
        ),
      ),
    ),
  ]);
}

export function medicalFees(ctx, detail, create) {
  const codes = new Set(['medical', 'medicine', 'rehab', 'escort']);
  const lines = ctx.state.bills.flatMap((bill) =>
    (bill.lineItems || []).filter((l) => codes.has(l.code)).map((line) => ({ bill, line })),
  );
  return table(ctx, {
    title: '医疗费用明细',
    rows: lines,
    empty: '已核算账单中暂无医疗费用。',
    action: canAct(ctx, 'ops.bill') && btn(ctx, '核算含医疗费用的账单', create, 'primary'),
    search: {
      placeholder: '搜索长辈、项目或账期',
      value: (r) => [residentName(ctx, r.bill.residentId), r.line.label, r.bill.month].join(' '),
    },
    filter: {
      label: '费用类别',
      all: '全部类别',
      value: (r) => ctx.state.chargeCatalog.categories[r.line.code],
    },
    cols: [
      { label: '长辈', view: (r) => residentAnchor(ctx, r.bill.residentId) },
      { label: '账期', view: (r) => r.bill.billingDate || r.bill.month },
      { label: '收费项目', view: (r) => r.line.label },
      { label: '单价', view: (r) => money(r.line.unitPrice) },
      { label: '数量', view: (r) => r.line.quantity + ' ' + r.line.unit },
      { label: '计入账单', view: (r) => money(r.line.amount) },
      { label: '整单状态', view: (r) => badge(ctx, r.bill.status) },
      { label: '操作', view: (r) => link(ctx, '查看账单', () => detail(r.bill)) },
    ],
  });
}

export function dischargeBilling(ctx, openBill) {
  const state = ctx.state;
  const grouped = new Map();
  for (const bill of state.bills) {
    if (!grouped.has(bill.residentId)) grouped.set(bill.residentId, []);
    grouped.get(bill.residentId).push(bill);
  }
  const accounts = new Map((state.deposits || []).map((a) => [a.residentId, cents(a.amount)]));
  const used = new Map();
  for (const row of state.payments || [])
    if (row.securityBillId)
      used.set(row.securityBillId, (used.get(row.securityBillId) || 0) + cents(row.amount));
  const rows = state.residents
    .filter((p) => p.status === '已退住' && p.dischargedAt)
    .map((p) => {
      const bills = grouped.get(p.id) || [],
        advance = accounts.get(p.id) || 0,
        owed = sum(bills, 'balance');
      const held = bills
        .filter((b) => b.kind === 'security')
        .reduce((v, b) => v + cents(b.paid) - cents(b.refundedSecurity) - (used.get(b.id) || 0), 0);
      const history = (state.dischargeSettlements || []).filter(
        (r) => r.residentId === p.id && r.dischargedAt === p.dischargedAt,
      );
      const status = owed
        ? '待结清账单'
        : advance + held
          ? '待核对退款'
          : history.length
            ? '已结算'
            : '待结算';
      return { p, bills, advance, owed, held, history, status };
    })
    .sort((a, b) => b.p.dischargedAt.localeCompare(a.p.dischargedAt));
  function inspect(r) {
    const amount = r.advance + r.held;
    const review = () =>
      facts([
        ['长辈', residentName(ctx, r.p.id)],
        ['退住日期', r.p.dischargedAt],
        ['待缴余额', yuan(r.owed)],
        ['可退预缴金', yuan(r.advance)],
        ['可退押金', yuan(r.held)],
        ['状态', r.status],
      ]);
    function history() {
      return records(r.history, (x) =>
        facts([
          ['结算编号', x.id],
          ['签认日期', x.date],
          ['经办人', x.operator],
          ['已退', money(x.amount)],
          ['渠道', x.method],
          ['凭证号', x.reference],
        ]),
      );
    }
    const print = () =>
      printReport(
        ctx,
        '退住结算单',
        node('div', '', [
          review(),
          history(),
          financialTable(
            ['账单号', '账期', '应收', '已核销', '待缴'],
            r.bills.map((b) => [b.id, b.month, money(b.amount), money(b.paid), money(b.balance)]),
          ),
        ]),
      );
    const issue = () =>
      ctx.dialog({
        title: amount ? '登记已完成的线下退款' : '确认退住结算',
        description: amount
          ? '请在实际退款后填写渠道及退款流水或签收凭证号。'
          : '本次余款为零，核对后留存结算凭证。',
        content: review(),
        fields: amount
          ? [
              select('method', '实际退款渠道', ['现金', '银行转账', '微信支付', '支付宝', '银联刷卡']),
              field('reference', '退款流水或签收凭证号', { maxLength: 100 }),
            ]
          : [],
        submitLabel: '核对结算',
        onSubmit: (v) =>
          ctx.command(
            'ops.dischargeSettlement',
            { ...v, residentId: r.p.id, amount: (amount / 100).toFixed(2) },
            {
              title: '确认退住结算',
              target: residentName(ctx, r.p.id),
              fields: [
                ['已退预缴金', yuan(r.advance)],
                ['已退押金', yuan(r.held)],
                ...(amount ? [['退款凭证', v.reference]] : []),
              ],
            },
          ),
      });
    ctx.detail(
      '退住结算 · ' + r.p.name,
      node('div', 'fx-profile', [
        review(),
        section(
          '关联账单',
          records(r.bills, (b) =>
            link(ctx, b.month + ' · ' + b.status + ' · ' + money(b.amount), () => openBill(b)),
          ),
        ),
        section('历次结算凭证', history()),
      ]),
      choose(
        btn(ctx, '打印结算单', print),
        !r.owed &&
          r.status !== '已结算' &&
          canAct(ctx, 'ops.dischargeSettlement') &&
          btn(ctx, amount ? '登记已退款' : '确认结算', issue, 'primary'),
      ),
    );
  }
  return table(ctx, {
    title: '退住结算',
    rows,
    search: { placeholder: '搜索长辈、房号', value: (r) => residentName(ctx, r.p.id) },
    filter: { value: (r) => r.status },
    cols: [
      { label: '长辈', view: (r) => residentAnchor(ctx, r.p) },
      { label: '退住日期', view: (r) => r.p.dischargedAt },
      { label: '待缴余额', view: (r) => yuan(r.owed) },
      { label: '可退预缴', view: (r) => yuan(r.advance) },
      { label: '可退押金', view: (r) => yuan(r.held) },
      { label: '结算状态', view: (r) => badge(ctx, r.status) },
      { label: '操作', view: (r) => link(ctx, '查看结算', () => inspect(r)) },
    ],
  });
}

export function dayClosing(ctx) {
  const picker = node('input', 'fx-input');
  picker.type = 'date';
  picker.setAttribute('aria-label', '结算日期');
  picker.max = today(ctx);
  picker.value = today(ctx);
  const content = node('div', 'fx-profile');
  const all = receiptRows(ctx.state);
  function draw() {
    const day = picker.value;
    if (!day || day > picker.max) {
      content.replaceChildren(node('p', 'form-error', '请选择截至今天的结算日期'));
      return;
    }
    const received = all.filter((r) => r.date === day),
      expenses = (ctx.state.expenses || []).filter((r) => r.date === day);
    const refunds = (ctx.state.dischargeSettlements || []).filter((r) => r.date === day && r.amount > 0);
    const reversed = -received.reduce((s, r) => s + (r.refundOf ? r.gross : 0), 0);
    const gross = received.reduce((s, r) => s + r.gross, 0),
      expense = sum(expenses, 'amount'),
      refund = sum(refunds, 'amount');
    const feeKnown = received.every((r) => r.fee != null),
      fee = received.reduce((s, r) => s + (r.fee || 0), 0);
    const summary = [
      ['当日实收（含预缴）', yuan(gross + reversed)],
      ...(reversed ? [['收款原单退款', yuan(reversed)]] : []),
      ['机构承担手续费', feeKnown ? yuan(fee) : '有历史凭证待核对'],
      ['当日支出', yuan(expense)],
      ['退住退款', yuan(refund)],
      ['当日收支净额', feeKnown ? yuan(gross - fee - expense - refund) : '待核对手续费'],
    ];
    const entries = [
      ...received.map((r) => ({
        kind: '收款',
        ref: r.id,
        payer: residentName(ctx, r.residentId),
        method: r.channel || r.method,
        amount: yuan(r.gross),
        open: () => ctx.detail('实收凭证', receiptFacts(r)),
      })),
      ...expenses.map((r) => ({
        kind: '机构支出',
        ref: r.voucher,
        payer: r.payee,
        method: r.category,
        amount: money(r.amount),
        open: () =>
          ctx.detail(
            '支出凭证',
            facts([
              ['凭证号', r.voucher],
              ['收款方', r.payee],
              ['金额', money(r.amount)],
              ['支出日期', r.date],
            ]),
          ),
      })),
      ...refunds.map((r) => ({
        kind: '退住退款',
        ref: r.reference,
        payer: residentName(ctx, r.residentId),
        method: r.method,
        amount: money(r.amount),
        open: () =>
          ctx.detail(
            '退款登记凭证',
            facts([
              ['结算单号', r.id],
              ['退款流水', r.reference],
              ['经办人', r.operator],
              ['金额', money(r.amount)],
            ]),
          ),
      })),
    ];
    const print = () =>
      printReport(
        ctx,
        day + ' 日结报表',
        node('div', '', [
          facts(summary),
          financialTable(
            ['类型', '凭证号', '往来方', '方式', '发生额'],
            entries.map((e) => [e.kind, e.ref, e.payer, e.method, e.amount]),
          ),
        ]),
      );
    content.replaceChildren(
      kpis(summary),
      table(ctx, {
        title: '日结凭证',
        rows: entries,
        empty: '当日暂无收支凭证。',
        action: btn(ctx, '打印日结报表', print),
        filter: { label: '类型', all: '全部类型', value: (r) => r.kind },
        search: { placeholder: '查询凭证或往来方', value: (r) => r.ref + ' ' + r.payer },
        cols: [
          { label: '类型', view: (r) => r.kind },
          { label: '凭证号', view: (r) => r.ref },
          { label: '往来方', view: (r) => r.payer },
          { label: '方式', view: (r) => r.method },
          { label: '发生额', view: (r) => r.amount },
          { label: '操作', view: (r) => link(ctx, '查看凭证', r.open) },
        ],
      }),
    );
  }
  picker.onchange = draw;
  draw();
  return node('div', 'fx-profile', [node('label', 'desk-filter', ['结算日期', picker]), content]);
}
