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
