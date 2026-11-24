// The renderer supplies an order number. The signed, unexpired destination is read
// from the institution using the current finance session, then rechecked here.
function merchantAddress(channel, value) {
  if (typeof value !== 'string' || value.length > 1024 || /[\s\\\p{C}]/u.test(value)) return null;
  const url = new URL(value);
  if (url.username || url.password || url.port || url.hash) return null;
  if (channel === '微信支付' && url.protocol === 'weixin:' && url.hostname === 'wxpay' &&
      url.pathname === '/bizpayurl' && url.searchParams.size === 1 && url.searchParams.get('pr')) return url.href;
  if (channel === '支付宝' && url.origin === 'https://qr.alipay.com' && url.pathname.length > 1) return url.href;
  return null;
}

function registerPaymentLinks(contents, origin, openExternal) {
  contents.ipc.handle('payments:open-checkout', async (event, orderId) => {
    const frame = event.senderFrame;
    const current = () => {
      if (contents.isDestroyed() || !frame || frame !== contents.mainFrame || frame.origin !== origin) return false;
      const page = new URL(frame.url);
      return page.origin === origin && ['/', '/index.html'].includes(page.pathname);
    };
    try {
      if (!current() || typeof orderId !== 'string' || !/^NH-[a-f0-9]{16}$/.test(orderId) || orderId.length !== 19) return false;
      const status = await contents.session.fetch(origin + '/api/payments/checkout/orders/' + orderId,
        { credentials: 'include', redirect: 'error', cache: 'no-store' });
      if (!status.ok) return false;
      const order = await status.json();
      if (order.orderId !== orderId || order.status !== '待支付' || !(order.expiresAt * 1000 > Date.now())) return false;
      const link = merchantAddress(order.channel, order.checkoutUrl);
      if (!current() || !link) return false;
      await openExternal(link);
      return true;
    } catch {
      return false;
    }
  });
}

module.exports = { registerPaymentLinks };
