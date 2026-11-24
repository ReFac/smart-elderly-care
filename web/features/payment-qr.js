import { facts, link, money, node } from './shared.js';

function bitmap(matrix) {
  const canvas = node('canvas');
  canvas.setAttribute('aria-label', '使用对应支付应用扫描的机构收款码');
  const scale = Math.max(2, Math.min(8, Math.floor(288 / matrix.length)));
  canvas.width = canvas.height = scale * matrix.length;
  const paint = canvas.getContext('2d');
  paint.fillStyle = '#fff';
  paint.fillRect(0, 0, canvas.width, canvas.height);
  paint.fillStyle = '#000';
  matrix.forEach((row, y) =>
    Array.from(row).forEach((value, x) => {
      if (value === '1') paint.fillRect(x * scale, y * scale, scale, scale);
    })
  );
  return canvas;
}

async function show(ctx, order) {
  if (
    !(await ctx.confirmChange({
      title: '申请渠道收款码',
      target: order.channel + ' · ' + order.id,
      fields: [['金额', money(order.amount)]],
      confirmLabel: '确认申请',
    }))
  )
    return;
  const body = node('div', 'fx-page');
  const message = node('p', 'fx-muted', '正在向机构签约渠道申请收款码…');
  message.setAttribute('role', 'status');
  const image = node('div');
  image.style.textAlign = 'center';
  body.append(facts([['商户订单', order.id], ['金额', money(order.amount)]]), image, message);
  const dialog = ctx.detail(order.channel + '收款码', body);
  dialog.style.maxWidth = '32rem';
  let timer;
  dialog.addEventListener('close', () => clearTimeout(timer), { once: true });
  try {
    const response = await fetch('/api/payments/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ orderId: order.id }),
    });
    const code = await response.json();
    if (!response.ok) throw new Error(code.error || '暂时无法获取收款码');
    await ctx.refreshWorkspace();
    if (!dialog.open) return;
    image.append(bitmap(code.matrix));
    message.textContent = '请使用' + order.channel + '扫码并核对收款方和金额，正在等待到账通知。';
    async function check() {
      if (!dialog.open) return;
      if (Date.now() >= code.expiresAt * 1000) {
        image.replaceChildren();
        message.textContent = '付款码已过期，请重新打开订单。';
        return;
      }
      try {
        const status = await ctx.get('/api/payments/checkout/orders/' + encodeURIComponent(order.id));
        if (!dialog.open) return;
        if (status.status !== '待支付') {
          image.replaceChildren();
          await ctx.refreshWorkspace();
          message.textContent = '该笔订单' + status.status + '，可在「实收对账」查看凭证。';
          return;
        }
      } catch (error) {
        image.replaceChildren();
        message.textContent = error.message + '。请重新打开订单核对状态。';
        return;
      }
      if (dialog.open) timer = setTimeout(check, 4000);
    }
    timer = setTimeout(check, 4000);
  } catch (error) {
    message.textContent = error.message || '收款渠道暂时不可用';
  }
}

export function checkoutAction(ctx, order, channels) {
  const slot = node('span');
  channels.then((available) => {
    if (available.includes(order.channel)) {
      slot.append(link(ctx, '显示收款码', () => show(ctx, order)));
    }
  });
  return slot;
}
