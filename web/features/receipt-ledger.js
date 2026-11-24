import { facts, kpis, link, money, named, node, residentName, table, today } from './shared.js';
import { residentAnchor } from './people-labels.js';

const directMethods = new Set(['线下登记', '线下刷卡登记', '微信支付', '支付宝']);
const cents = (amount) => Math.round(Number(amount) * 100);
const currency = (amount) => amount == null ? '手续费待核对' : money(amount / 100);
export const isDirectReceipt = (row) => directMethods.has(row.method);

export function receiptRows(state) {
  const channelReceipts = new Map((state.channelReceipts || []).map((r) => [r.id, r]));
  const vouchers = new Map();
  function append(row, advance) {
    const id = row.receiptId || row.id;
    const channelRow = channelReceipts.get(id);
    let voucher = vouchers.get(id);
    if (!voucher) {
      voucher = {
        id, date: row.date, residentId: row.residentId,
        billId: row.originBillId || row.billId || channelRow?.billId || '',
        method: row.method || channelRow?.channel || '', channel: row.channel || channelRow?.channel || '',
        merchantOrder: row.merchantOrder || channelRow?.merchantOrder || '',
        transactionId: row.transactionId || channelRow?.transactionId || '',
        applied: 0, advance: 0, gross: 0, fee: 0, net: 0,
      };
      vouchers.set(id, voucher);
    }
    const amount = cents(row.amount);
    voucher.gross += amount;
    voucher[advance ? 'advance' : 'applied'] += amount;
    if (row.feeAmount == null || voucher.fee == null) {
      voucher.fee = null;
      voucher.net = null;
    } else {
      voucher.fee += cents(row.feeAmount);
      voucher.net = voucher.gross - voucher.fee;
    }
  }
  for (const row of state.payments || []) if (isDirectReceipt(row)) append(row, false);
  for (const row of state.depositEntries || []) append(row, true);
  return [...vouchers.values()].sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id));
}

function tender(row) {
  if (row.method && row.channel && row.channel !== row.method) return row.method + '（' + row.channel + '）';
  return row.method || row.channel || '历史凭证未记载';
}

export function receiptFacts(row) {
  return facts([
    ['凭证编号', row.id], ['到账日期', row.date], ['收款方式', tender(row)],
    ['实收总额', currency(row.gross)], ['核销本单', currency(row.applied)], ['转入预缴', currency(row.advance)],
    ['机构承担手续费', currency(row.fee)], ['净入账', currency(row.net)],
    ...(row.billId ? [['账单号', row.billId]] : []),
    ...(row.merchantOrder ? [['商户订单号', row.merchantOrder]] : []),
    ...(row.transactionId ? [['渠道交易流水号', row.transactionId]] : []),
  ]);
}

export function openReceipts(ctx, period = 'month') {
  ctx.go('billing', 'receipts', () => {
    const input = document.querySelector('[data-receipt-period]');
    if (!input) return;
    input.value = period;
    input.dispatchEvent(new Event('change'));
  });
}

export function receiptLedger(ctx) {
  const rows = receiptRows(ctx.state);
  const day = today(ctx);
  const monthStart = day.slice(0, 7) + '-01';
  const picker = node('select', 'fx-input');
  picker.dataset.receiptPeriod = '';
  for (const [value, label] of [['month', '本月至今'], ['today', '今日'], ['all', '全部日期'], ['custom', '自选时段']])
    picker.add(new Option(label, value));
  const dateInput = (label, value) => {
    const input = node('input', 'fx-input');
    input.type = 'date';
    input.value = value;
    input.max = day;
    return { input, label: node('label', '', [label + ' ', input]) };
  };
  const start = dateInput('从', monthStart);
  const end = dateInput('至', day);
  const controls = node('div', 'fx-actions', [node('label', '', ['到账日期 ', picker]), start.label, end.label]);
  const list = node('div', 'fx-profile');
  function draw() {
    const custom = picker.value === 'custom';
    start.label.hidden = end.label.hidden = !custom;
    const first = custom ? start.input.value : picker.value === 'today' ? day : picker.value === 'month' ? monthStart : '';
    const last = custom ? end.input.value : day;
    if (custom && (!first || !last || first > last || last > day)) {
      list.replaceChildren(node('p', 'form-error', '请选择截至今日的有效起止日期。'));
      return;
    }
    const visible = rows.filter((r) => first <= r.date && r.date <= last);
    const totals = visible.reduce((s, r) => {
      s.gross += r.gross;
      if (r.fee == null) s.unknown += 1;
      else s.fee += r.fee;
      return s;
    }, { gross: 0, fee: 0, unknown: 0 });
    list.replaceChildren(kpis([
      ['期间实收（含预缴）', currency(totals.gross)],
      ['机构承担手续费', totals.unknown ? totals.unknown + ' 笔待核对' : currency(totals.fee)],
      ['期间净入账', currency(totals.unknown ? null : totals.gross - totals.fee)],
    ]), table(ctx, {
      title: '实收流水', rows: visible, empty: '此时段尚无到账凭证。',
      search: { placeholder: '搜索长者、凭证或流水号', value: (r) => [residentName(ctx, r.residentId), r.id, r.billId, r.transactionId, r.merchantOrder].join(' ') },
      cols: [
        { label: '到账日期', view: (r) => r.date },
        { label: '长者', view: (r) => residentAnchor(ctx, r.residentId) },
        { label: '实收金额', view: (r) => named(currency(r.gross), tender(r)) },
        { label: '核销账单', view: (r) => currency(r.applied) },
        { label: '转入预缴', view: (r) => currency(r.advance) },
        { label: '机构手续费', view: (r) => currency(r.fee) },
        { label: '净入账', view: (r) => currency(r.net) },
        { label: '操作', view: (r) => link(ctx, '查看凭证', () => ctx.detail('实收凭证', receiptFacts(r))) },
      ],
    }));
  }
  for (const input of [picker, start.input, end.input]) input.addEventListener('change', draw);
  draw();
  return node('div', 'fx-profile', [controls, list]);
}
