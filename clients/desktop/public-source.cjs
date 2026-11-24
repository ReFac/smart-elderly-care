const { lookup } = require('node:dns/promises');
const { BlockList, isIP } = require('node:net');

const excluded = new BlockList();
for (const [address, prefix] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
  ['192.88.99.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24],
  ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4],
]) excluded.addSubnet(address, prefix, 'ipv4');
const globalV6 = new BlockList();
globalV6.addSubnet('2000::', 3, 'ipv6');
for (const [address, prefix] of [['2001::', 23], ['2001:db8::', 32], ['2002::', 16], ['3fff::', 20]]) {
  excluded.addSubnet(address, prefix, 'ipv6');
}

function publicAddress({ address }) {
  if (isIP(address) === 4) return !excluded.check(address, 'ipv4');
  return isIP(address) === 6 && globalV6.check(address, 'ipv6') && !excluded.check(address, 'ipv6');
}

// Only the institution window installs this handler; print/document children have no IPC capability.
function registerSourceLinks(contents, origin, openExternal, resolve = lookup) {
  contents.ipc.handle('assistant:open-public-source', async (event, value) => {
    const frame = event.senderFrame;
    const current = () => !contents.isDestroyed() && frame && frame === contents.mainFrame
      && frame.origin === origin && new URL(frame.url).origin === origin;
    try {
      if (!current() || typeof value !== 'string' || value.length > 8192 ||
          !/^https?:\/\//i.test(value) || /[\s\\\p{C}]/u.test(value)) return false;
      const url = new URL(value);
      const host = url.hostname.toLowerCase().replace(/\.$/, '');
      if (url.username || url.password || url.origin === origin || url.port === '0' ||
          host.startsWith('[') || isIP(host) || !host.includes('.') ||
          /(?:^|\.)(?:localhost|local|internal|lan|home|test|invalid|home\.arpa)$/.test(host))
        return false;
      const records = await resolve(host, { all: true });
      if (!records.length || !records.every(publicAddress) || !current()) return false;
      await openExternal(url.href);
      return true;
    } catch {
      return false;
    }
  });
}

module.exports = { registerSourceLinks };
