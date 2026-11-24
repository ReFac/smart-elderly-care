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
        assert.equal(selector, '#assistant-chat:not([hidden]) a.assistant-source-link');
        return inSources ? link : null;
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
