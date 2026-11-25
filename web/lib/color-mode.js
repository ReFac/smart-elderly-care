const key = 'eldercare.display-theme';
const modes = [
  ['light', '亮色'],
  ['dark', '暗色'],
  ['system', '跟随系统'],
];
const system = window.matchMedia('(prefers-color-scheme: dark)');
let account = '';
let preference = savedMode();

function accountKey() {
  return account ? key + '.' + account : key;
}

function savedMode() {
  try {
    const value = localStorage.getItem(accountKey()) || localStorage.getItem(key);
    if (modes.some(([mode]) => mode === value)) return value;
  } catch {}
  return 'system';
}

function apply() {
  const dark = preference === 'dark' || (preference === 'system' && system.matches);
  document.documentElement.dataset.colorMode = dark ? 'dark' : 'light';
  for (const control of document.querySelectorAll('[data-color-mode-control]'))
    control.value = preference;
}

export function setColorModeAccount(id = '') {
  if (id === account) return;
  account = id;
  preference = savedMode();
  apply();
}

export function colorModeControl() {
  const label = document.createElement('label');
  label.className = 'color-mode-control';
  const caption = document.createElement('span');
  caption.textContent = '显示主题';
  const select = document.createElement('select');
  select.dataset.colorModeControl = '';
  for (const [value, name] of modes) select.add(new Option(name, value));
  select.value = preference;
  select.addEventListener('change', () => {
    preference = select.value;
    try { localStorage.setItem(accountKey(), preference); } catch {}
    apply();
  });
  label.append(caption, select);
  return label;
}

system.addEventListener('change', apply);
window.addEventListener('storage', (event) => {
  if (event.key !== null && event.key !== key && event.key !== accountKey()) return;
  preference = savedMode();
  apply();
});
apply();
