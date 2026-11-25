import { btn, facts, money, node } from './shared.js';

export function sendMerchantRefund(ctx, row) {
  const panel = node('div', 'fx-page');
  const actions = node('div', 'fx-actions');
  const hint = node('p', 'fx-muted', row.channelMessage || (row.channelStartedAt ?
    '原退款申请已提交。可以查询处理结果，系统也会定时核对。' :
    '请核对原收款和应退金额。提交后，商户会将钱退回原支付渠道。'));
  hint.setAttribute('role', 'status');
  panel.append(facts([['原支付渠道', row.channel], ['退款金额', money(row.amount)],
    ['原商户订单', row.merchantOrder], ['退款单号', row.id], ['申请原因', row.reason]]), hint, actions);
  const dialog = ctx.detail('原路退款', panel);
  let current = row;
  function draw() {
    actions.replaceChildren();
    if (!['待核实','渠道处理中'].includes(current.status)) return;
    if (current.channelStartedAt) actions.append(btn(ctx, '查询退款结果', () => request('query'), 'primary'));
    actions.append(btn(ctx, current.channelStartedAt ? '按原单号重试' : '提交原路退款', () => request('submit'),
      current.channelStartedAt ? 'ghost' : 'primary'));
  }
  async function request(operation) {
    for (const button of actions.querySelectorAll('button')) button.disabled = true;
    try {
      if (operation === 'submit' && !await ctx.confirmChange({
        title: '确认向' + row.channel + '发起原路退款', target: row.merchantOrder,
        fields: [['金额', money(row.amount)], ['本次退款单号', row.id]], confirmLabel: '确认原路退款',
      })) return;
      const response = await fetch('/api/payments/refunds/channel', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({refundId: row.id, operation, confirmed: true}),
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || '暂未取得渠道结果，请查询原单。');
      hint.textContent = result.message;
      current = {...current, status: result.status, channelStartedAt: true};
    } catch (error) {
      hint.textContent = error.message;
    } finally {
      try { await ctx.refreshWorkspace(); } catch { /* The signed outcome can be queried again. */ }
      if (ctx.current) {
        const fresh = ctx.current().state.refunds?.find(item => item.id === row.id);
        if (!fresh) { if (dialog.open) dialog.close(); return; }
        current = fresh;
      }
      if (dialog.open) draw();
    }
  }
  draw();
  return dialog;
}
