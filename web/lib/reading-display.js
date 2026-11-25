import { applyPersonalMode } from './color-mode.js';

export const families = {
  system: { label: '系统默认', fallback: 'system-ui' },
  sans: { label: '思源黑体 / Noto Sans', fallback: 'sans-serif',
    names: ['Source Han Sans SC', 'Noto Sans CJK SC', 'Noto Sans SC'] },
  serif: { label: '思源宋体 / Noto Serif', fallback: 'serif',
    names: ['Source Han Serif SC', 'Noto Serif CJK SC', 'Noto Serif SC'] },
};
export const defaults = { mode: 'light', family: 'system', level: 3, density: 'comfortable', motion: 'system' };
const fontCache = new Map();
let account = '', cloud = {version: 0, values: null};
const key = () => 'eldercare.display-preferences.' + account;

function device() {
  try { return JSON.parse(localStorage.getItem(key())) || {}; } catch { return {}; }
}

function legacy() {
  try {
    const old = JSON.parse(localStorage.getItem('eldercare.reading-display.' + account)) || {};
    const mode = localStorage.getItem('eldercare.display-theme.' + account);
    return {...defaults, ...(['light','dark','system'].includes(mode) && {mode}),
      ...(Number.isInteger(old.level) && old.level >= 1 && old.level <= 10 && {level: old.level}),
      ...(Object.hasOwn(families, old.family) && {family:old.family})};
  } catch { return {...defaults}; }
}

export function preferenceView() {
  const local = device();
  const following = local.follow !== false;
  const remote = cloud.values || legacy();
  return {following, version:cloud.version, remote, local:local.values || remote,
    values: following ? remote : local.values || remote};
}

export async function resolveFont(family) {
  const option = families[family] || families.system;
  if (!option.names) return {css: '', note:'当前使用系统默认字体。'};
  if (!fontCache.has(family)) fontCache.set(family, (async () => {
    for (const name of option.names) {
      try {
        await new FontFace('DeskFontCheck', 'local("' + name + '")').load();
        return {css:'"' + name + '", ' + option.fallback, note:'当前使用本机字体 ' + name + '。'};
      } catch {}
    }
    return {css:option.fallback, note:'本机未安装所选字体，当前使用系统' + (family === 'serif' ? '衬线' : '无衬线') + '字体。'};
  })());
  return fontCache.get(family);
}

let generation = 0;
function apply() {
  const serial = ++generation;
  const html = document.documentElement;
  const v = account ? preferenceView().values : defaults;
  applyPersonalMode(account ? v.mode : null);
  html.toggleAttribute('data-reading-display', Boolean(account));
  if (account) {
    html.style.setProperty('--desk-type-scale', String((11 + v.level) / 14));
    html.dataset.density = v.density;
    html.dataset.motion = v.motion;
  } else {
    html.style.removeProperty('--desk-type-scale');
    delete html.dataset.density;
    delete html.dataset.motion;
  }
  if (v.family === 'system') html.style.removeProperty('--desk-font');
  else resolveFont(v.family).then(font => {
    if (serial === generation) html.style.setProperty('--desk-font', font.css);
  });
}

export function setDisplayAccount(id = '', record) {
  const changed = account !== id;
  if (changed) { account = id; cloud = {version:0, values:null}; }
  if (record && record.version > cloud.version) { cloud = record; apply(); }
  else if (changed) apply();
}

async function request(options) {
  const response = await fetch('/api/account/display-preferences', {cache:'no-store', ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '账号设置暂时无法读取');
  return data;
}

export async function refreshPreferences() {
  if (!account) return;
  const id = account;
  const row = await request();
  if (id === account && row.accountId === id) setDisplayAccount(id, row);
}

export async function saveDisplay(follow, values, version) {
  const id = account;
  if (!id) throw new Error('请先登录');
  if (follow) {
    const row = await request({method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({version, values, expectedAccount:id})});
    if (id !== account) return false;
    cloud = row;
  }
  const saved = device();
  // A device can opt out independently of other devices using the same account.
  localStorage.setItem(key(), JSON.stringify({follow, values:follow ? saved.values : values}));
  apply();
  return true;
}

window.addEventListener('storage', event => { if (account && (event.key === key() || event.key === null)) apply(); });
window.addEventListener('focus', () => {
  if (account && device().follow !== false) refreshPreferences().catch(() => {});
});
