// Mini-program JS runtimes do not consistently provide the browser URL constructor.
const entries = Object.freeze({workspace: '/?workspace=1', visit: '/visit', tour: '/roomtour', faq: '/faq'});

function institutionOrigin(address) {
  if (typeof address !== 'string') return '';
  const match = /^https:\/\/([a-z0-9.-]+)(?::(\d{1,5}))?\/?$/i.exec(address.trim());
  if (!match || match[1].length > 253 || match[2] && (!Number(match[2]) || Number(match[2]) > 65535)) return '';
  const labels = match[1].split('.');
  if (labels.length < 2 || !labels.every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))) return '';
  return 'https://' + match[1].toLowerCase() + (match[2] ? ':' + match[2] : '');
}

function entryUrl(address, entry) {
  const origin = institutionOrigin(address);
  if (!origin) return '';
  return origin + (Object.prototype.hasOwnProperty.call(entries, entry) ? entries[entry] : entries.workspace);
}

module.exports = {institutionOrigin, entryUrl};
