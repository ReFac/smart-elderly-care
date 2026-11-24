import { btn, choose, field, money, node, options, residentField, residentName, select, today } from './shared.js';
import { showCheckout } from './payment-qr.js';

const rateChannels = ['微信支付', '支付宝', '银联刷卡', '银行转账'];
const methods = [
  ['线下登记', '现金'], ['线下登记', '银行转账'], ['线下登记', '微信支付'],
  ['线下登记', '支付宝'], ['线下刷卡登记', '银联刷卡'],
];
const cents = (amount) => Math.round(Number(amount || 0) * 100);
const rates = (ctx) => ctx.state.paymentFeeSettings?.[0]?.rates || {};
const rateText = (bps) => (bps / 100).toFixed(2) + '%';
const paymentRef = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) => n.toString(16).padStart(2, '0')).join('');

export function receiptDescription(row) {
  const tender = [row.method, row.channel && row.channel !== row.method ? row.channel : ''].filter(Boolean).join(' · ');
  return [row.date, tender, ...(row.feeAmount == null ? [] : [
    '手续费 ' + money(row.feeAmount), '净入账 ' + money(row.netAmount),
  ])].filter(Boolean).join(' ｜ ');
}

export function feeSettings(ctx) {
  const current = rates(ctx);
  ctx.dialog({
    title: '收款手续费设置', description: '填写机构签约费率。按整笔实收费计算手续费，四舍五入到分。现金费率为零。',
    fields: rateChannels.map((channel) => field(channel, channel + '手续费率（%）', {
      type: 'number', min: 0, max: 100, step: '0.01', value: (current[channel] || 0) / 100,
    })),
    onSubmit(values) {
      const updated = Object.fromEntries(rateChannels.map((c) => [c, cents(values[c])]));
      return ctx.command('ops.paymentFees', { rates: updated }, {
        title: '确认机构手续费率', fields: rateChannels.map((c) => [c, rateText(updated[c])]),
      });
    },
  });
}

export function recordCash(ctx, { bill, residentId } = {}) {
  const ref = paymentRef();
  const target = bill?.residentId || residentId;
  const preview = node('p', 'fx-muted');
  preview.setAttribute('aria-live', 'polite');
  const methodField = select('tender', '登记方式与实际支付渠道',
    methods.map(([mode, channel], i) => ({ value: String(i), label: mode + '（' + channel + '）' })));
  function breakdown(values) {
    const [method, channel] = methods[Number(values.tender)];
    const gross = cents(values.amount);
    const order = (ctx.state.paymentOrders || []).find((r) => r.channel === channel && r.id === values.merchantOrder);
    const bps = order?.feeRateBps ?? (rates(ctx)[channel] || 0);
    const fee = Math.round(gross * bps / 10000);
    const surplus = bill ? Math.max(0, gross - cents(bill.balance)) : gross;
    return { method, channel, fields: [
      ['实收金额', money(gross / 100)], ['登记方式', method + '（' + channel + '）'],
      ['机构承担手续费（' + rateText(bps) + '）', money(fee / 100)], ['净入账', money((gross - fee) / 100)],
      ...(bill ? [['本单核销', money((gross - surplus) / 100)]] : []),
      ['转入预缴金', money(surplus / 100)],
    ] };
  }
  const dialog = ctx.dialog({
    title: bill ? '登记收款' : '登记预缴金',
    description: (target ? residentName(ctx, target) + ' · ' : '') + (bill
      ? '待缴 ' + money(bill.balance) + '。请核实已实际收款，超出部分存入长者账户。'
      : '到账后优先冲抵已有欠款，结余用于以后账期。'),
    content: preview,
    fields: [
      ...(!target ? [residentField(ctx)] : []),
      field('amount', '实收金额（元）', { type: 'number', min: '0.01', max: 99999999, step: '0.01', value: bill?.balance }), methodField,
      field('merchantOrder', '商户订单号', { maxLength: 100 }), field('transactionId', '渠道交易流水号', { maxLength: 100 }),
      field('paidDate', '实际到账日期', { type: 'date', max: today(ctx), value: today(ctx) }),
    ],
    submitLabel: '核对已交费金额',
    onSubmit(values) {
      const { method, channel, fields } = breakdown(values);
      const action = bill ? 'ops.pay' : 'ops.deposit';
      const { merchantOrder, transactionId, paidDate } = values;
      const payload = { amount: values.amount, paymentRef: ref, method, channel,
        ...(merchantOrder ? { merchantOrder, transactionId, paidDate } : {}),
        ...(bill ? { billId: bill.id, carrySurplus: true } : { residentId: target || values.residentId }) };
      return ctx.command(action, payload, { title: '确认已收到此款', target: residentName(ctx, target || values.residentId), fields });
    },
  });
  const form = dialog.querySelector('form');
  const sync = () => {
    const channel = methods[Number(form.elements.tender.value)][1];
    const merchant = ['微信支付', '支付宝'].includes(channel);
    for (const name of ['merchantOrder', 'transactionId', 'paidDate']) {
      const input = form.elements[name];
      input.disabled = !merchant;
      input.closest('label').hidden = !merchant;
    }
    const { fields } = breakdown(Object.fromEntries(new FormData(form)));
    preview.textContent = fields.slice(2).map(([k,v]) => k + ' ' + v).join(' ｜ ');
  };
  form.addEventListener('input', sync);
  sync();
}

export async function collectCode(ctx, bill) {
  let channels;
  try {
    channels = (await ctx.get('/api/payments/checkout/channels')).channels;
  } catch (error) {
    return ctx.toast(error.message || '无法读取收款渠道');
  }
  if (!channels.length) {
    return ctx.detail('收款二维码', node('p', '', '本机构尚未开通微信或支付宝商户收款码。财务可登记已经核实的线下到款。'));
  }
  return ctx.dialog({
    title: '收款二维码', description: residentName(ctx, bill.residentId) + ' · 待缴 ' + money(bill.balance),
    fields: [select('channel', '收款渠道', options(channels)), field('amount', '扫码付款金额（元）', {
      type: 'number', min: '0.01', max: 99999999, step: '0.01', value: bill.balance,
    })],
    submitLabel: '申请收款码',
    async onSubmit({ channel, amount }) {
      const payload = { channel, amount, billId: bill.id, carrySurplus: true };
      const done = await ctx.command('ops.paymentOrder', payload, {
        title: '确认申请收款码', target: residentName(ctx, bill.residentId),
        fields: [['渠道', channel], ['扫码实付', money(amount)], ['超额转预缴', money(Math.max(0, cents(amount) - cents(bill.balance)) / 100)]],
      });
      if (!done) return done;
      const fresh = ctx.current();
      const order = fresh.state.paymentOrders.find((r) => r.billId === bill.id && r.channel === channel &&
        cents(r.amount) === cents(amount) && r.status === '待支付');
      if (order) await showCheckout(fresh, order, true);
      else fresh.toast('订单状态已改变，请重新打开账单核对。');
      return true;
    },
  });
}

export function cashierActions(ctx, bill, admission = false) {
  const allowed = ctx.state.allowedActions;
  return choose(
    allowed.includes('ops.pay') && btn(ctx, admission ? '已交费 · 登记收款' : '登记收款', () => recordCash(ctx, { bill })),
    allowed.includes('ops.paymentOrder') && btn(ctx, '收款二维码', () => collectCode(ctx, bill), 'primary')
  );
}
