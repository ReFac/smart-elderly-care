const { test } = require('node:test');
const assert = require('node:assert/strict');
const { registerSourceLinks } = require('../clients/desktop/public-source.cjs');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');

const origin = 'http://127.0.0.1:8765';
const publicHost = 'https://example.org/document';
function workspace(addresses, afterLookup) {
  const mainFrame = { origin, url: origin + '/#inventory' };
  const opened = [];
  let invoke;
  const contents = { mainFrame, isDestroyed: () => false, ipc: { handle(_name, fn) { invoke = fn; } } };
  registerSourceLinks(contents, origin, url => opened.push(url), async host => {
    assert.equal(host, 'example.org');
    if (afterLookup) afterLookup(contents);
    return addresses.map(address => ({ address }));
  });
  return { invoke, contents, mainFrame, opened };
}

test('main frame opens valid public sources only after checking every DNS record', async () => {
  const ok = workspace(['8.8.8.8', '2606:4700:4700::1111']);
  assert.equal(await ok.invoke({ senderFrame: ok.mainFrame }, publicHost), true);
  assert.deepEqual(ok.opened, [publicHost]);
  for (const address of ['10.0.0.7', '::1', '192.168.77.2', '100.64.0.1',
                          'fe80::1', 'ff02::1', '0.0.0.0', '::ffff:127.0.0.1']) {
    const app = workspace(['8.8.8.8', address]);
    assert.equal(await app.invoke({ senderFrame: app.mainFrame }, publicHost), false);
    assert.deepEqual(app.opened, []);
  }
});

test('private destinations, child/withdrawn frames and changed institution are denied', async () => {
  const app = workspace(['8.8.8.8']);
  for (const address of [origin, 'file:///tmp/foo', 'mailto:foo@example.org',
                          'https://host.local', 'http://0x7f000001', 'http://[::1]',
                          'https://care:secret@example.org/', 'https://example.org\\@foo']) {
    assert.equal(await app.invoke({ senderFrame: app.mainFrame }, address), false);
  }
  assert.equal(await app.invoke({ senderFrame: { ...app.mainFrame } }, publicHost), false);
  app.mainFrame.url = 'about:blank';
  assert.equal(await app.invoke({ senderFrame: app.mainFrame }, publicHost), false);
  assert.deepEqual(app.opened, []);
  const closing = workspace(['8.8.8.8'], c => { c.isDestroyed = () => true; });
  assert.equal(await closing.invoke({ senderFrame: closing.mainFrame }, publicHost), false);
  assert.deepEqual(closing.opened, []);
});

test('preload forwards only trusted clicks on displayed assistant source links', async () => {
  const requests = [];
  let click;
  const link = { isConnected: true, origin: 'https://example.org', href: publicHost,
                 getClientRects: () => [{}] };
  runInNewContext(readFileSync(require.resolve('../clients/desktop/source-preload.cjs'), 'utf8'), {
    require: () => ({ ipcRenderer: { invoke: async (...args) => { requests.push(args); return true; } } }),
    window: { addEventListener(type, fn, capture) { assert.equal(type, 'click'); assert.equal(capture, true); click = fn; } },
    location: { origin },
  });
  function event(trusted, inSources) {
    return { isTrusted: trusted, button: 0, defaultPrevented: false, preventDefault() {},
      stopImmediatePropagation() {}, target: { closest(selector) {
        return selector === '#assistant-chat:not([hidden]) a.assistant-source-link' && inSources ? link : null;
      } } };
  }
  await click(event(false, true));
  await click(event(true, false));
  link.isConnected = false;
  await click(event(true, true));
  link.isConnected = true;
  assert.equal(requests.length, 0);
  await click(event(true, true));
  assert.deepEqual(requests, [['assistant:open-public-source', publicHost]]);
});

test('customer detail dialing accepts only canonical phone numbers in the institution leads main frame', async () => {
  const { registerLeadCalls } = require('../clients/desktop/lead-calls.cjs');
  const opened = [];
  const mainFrame = { origin, url: origin + '/#leads' };
  let invoke;
  const contents = { mainFrame, isDestroyed: () => false, ipc: { handle(name, fn) {
    assert.equal(name, 'leads:call-customer');
    invoke = fn;
  } } };
  registerLeadCalls(contents, origin, url => opened.push(url));
  const call = v => invoke({ senderFrame: mainFrame }, v);
  const dial = 'tel:15500000161';
  for (const uri of [dial, 'tel:037512345678', 'tel:+14155550111']) assert.equal(await call(uri), true);
  for (const uri of ['https://example.org', 'tel://15500000161', 'tel:15500000161;ext=9',
    'tel:15500000161%2A', 'tel:15500000161\n', 'tel:110', 'tel:*123#', 'tel:15500000161,123', null]) {
    assert.equal(await call(uri), false);
  }
  assert.equal(await invoke({ senderFrame: { ...mainFrame } }, dial), false);
  for (const page of [origin + '/#overview', origin + '/visit#leads', 'https://example.org/#leads']) {
    mainFrame.url = page;
    assert.equal(await call(dial), false);
  }
  assert.deepEqual(opened, [dial, 'tel:037512345678', 'tel:+14155550111']);
});

test('only explicit clicks in visible lead details reach the dial action', async () => {
  let handler;
  const calls = [];
  const view = { origin, hash: '#leads' };
  const phone = { isConnected: true, protocol: 'tel:', href: 'tel:15500000161', getClientRects: () => [{}] };
  runInNewContext(readFileSync(require.resolve('../clients/desktop/source-preload.cjs'), 'utf8'), {
    require: () => ({ ipcRenderer: { invoke: async (...args) => { calls.push(args); return true; } } }),
    window: { addEventListener(_type, fn) { handler = fn; } }, location: view,
  });
  const click = (trusted, hasPhone = true) => handler({ isTrusted: trusted, button: 0, defaultPrevented: false,
    preventDefault() {}, stopImmediatePropagation() {}, target: { closest: selector =>
      hasPhone && selector === 'dialog[open] .lead-detail-head a.lead-phone' ? phone : null } });
  await click(false);
  await click(true, false);
  phone.isConnected = false;
  await click(true);
  phone.isConnected = true;
  view.hash = '#overview';
  await click(true);
  view.hash = '#leads';
  await click(true);
  assert.deepEqual(calls, [['leads:call-customer', phone.href]]);
});

test('desktop medication references open from a visible self-report on trusted activation', async () => {
  const calls = [];
  let click;
  runInNewContext(readFileSync(require.resolve('../clients/desktop/source-preload.cjs'), 'utf8'), {
    require: () => ({ ipcRenderer: { async invoke(...args) { calls.push(args); return true; } } }),
    window: { addEventListener(_type, callback) { click = callback; } }, location: { origin }, URL,
  });
  function activate(href, trusted = true) {
    const node = { href, origin: new URL(href).origin, isConnected: true, getClientRects: () => [{}] };
    return click({ isTrusted: trusted, button: 0, defaultPrevented: false, preventDefault() {}, stopImmediatePropagation() {},
      target: { closest: selector => selector === '.medication-source-scope a.medication-source-link' ? node : null } });
  }
  const sources = ['https://www.wikidata.org/wiki/Q201928',
    'https://www.nhsa.gov.cn/module/download/downfile.jsp?classid=0&filename=a32f9f2f3fc046afaf08471f87456ce3.pdf#page=39',
    'https://pharm.ncmi.cn/pharm/fullText/search.do?keyWord=%E9%98%BF%E8%8E%AB'];
  for (const valid of sources) await activate(valid);
  await activate(sources[0], false);
  await activate('https://www.wikidata.org.example.org/wiki/Q201928');
  await activate('https://pharm.ncmi.cn/elsewhere');
  assert.deepEqual(calls, sources.map(href => ['assistant:open-public-source', href]));
});

test('desktop checkout opens only an active institutional order in its signed payment application', async () => {
  const { registerPaymentLinks } = require('../clients/desktop/payment-links.cjs');
  const orderId = 'NH-0123456789abcdef';
  const frame = { origin, url: origin + '/#residents' };
  const opened = [];
  const requests = [];
  const receipt = { orderId, status: '待支付', expiresAt: Date.now() / 1000 + 60 };
  let invoke, afterResponse;
  const contents = { mainFrame: frame, isDestroyed: () => false,
    ipc: { handle(name, cb) { assert.equal(name, 'payments:open-checkout'); invoke = cb; } },
    session: { async fetch(url, options) { requests.push({url, options}); afterResponse?.();
      return { ok: true, json: async () => receipt };
    } },
  };
  registerPaymentLinks(contents, origin, (url) => opened.push(url));
  const click = (id = orderId) => invoke({ senderFrame: frame }, id);
  const ali = 'https://qr.alipay.com/realistic-order';
  const wx = 'weixin://wxpay/bizpayurl?pr=realistic-token';
  for (const [channel, checkoutUrl] of [['支付宝', ali], ['微信支付', wx]]) {
    Object.assign(receipt, { channel, checkoutUrl });
    assert.equal(await click(), true);
    assert.equal(opened.at(-1), checkoutUrl);
  }
  assert.equal(requests[0].url, origin + '/api/payments/checkout/orders/' + orderId);
  assert.equal(requests[0].options.credentials, 'include');
  assert.equal(requests[0].options.redirect, 'error');
  assert.equal(await click(ali), false);
  assert.equal(await invoke({ senderFrame: { ...frame } }, orderId), false);
  for (const [channel, url] of [
    ['微信支付', ali], ['支付宝', wx], ['支付宝', 'https://example.org/pay'],
    ['支付宝', 'http://qr.alipay.com/order'], ['支付宝', 'https://user@qr.alipay.com/order'],
    ['微信支付', 'weixin://wxpay/other?pr=order'], ['微信支付', 'weixin://wxpay/bizpayurl?pr=one&op=two'],
    ['微信支付', 'other://wxpay/bizpayurl?pr=token'],
  ]) {
    Object.assign(receipt, { channel, checkoutUrl: url });
    assert.equal(await click(), false);
  }
  Object.assign(receipt, { channel: '支付宝', checkoutUrl: ali, status: '已到账' });
  assert.equal(await click(), false);
  Object.assign(receipt, { status: '待支付', expiresAt: 100 });
  assert.equal(await click(), false);
  Object.assign(receipt, { expiresAt: Date.now() / 1000 + 60 });
  afterResponse = () => { frame.url = origin + '/public'; };
  assert.equal(await click(), false);
  assert.deepEqual(opened, [ali, wx]);
});

test('checkout preload forwards a visible user-activated order number without trusting its href', async () => {
  const orderId = 'NH-0123456789abcdef';
  let click, visible = true, inDialog = true;
  const calls = [];
  const dialog = { dataset: { paymentOrder: orderId } };
  const anchor = { href: 'https://example.org/ignored', isConnected: true,
    matches: (s) => s === 'a.merchant-checkout-link', getClientRects: () => visible ? [{}] : [],
    closest: (s) => inDialog && s === 'dialog[open][data-payment-order]' ? dialog : null };
  runInNewContext(readFileSync(require.resolve('../clients/desktop/source-preload.cjs'), 'utf8'), {
    require: () => ({ ipcRenderer: { invoke: async (...args) => { calls.push(args); return true; } } }),
    window: { addEventListener(type, fn) { click = fn; } }, location: { origin, hash: '#billing' },
  });
  const event = (trusted) => ({ isTrusted: trusted, button: 0, defaultPrevented: false,
    target: anchor, preventDefault() {}, stopImmediatePropagation() {} });
  await click(event(false)); visible = false;
  await click(event(true)); visible = true; inDialog = false;
  await click(event(true)); inDialog = true;
  await click(event(true));
  assert.deepEqual(calls, [['payments:open-checkout', orderId]]);
});
