const key = 'eldercare.display-theme';
export const modes = [['light', '亮色'], ['dark', '暗色'], ['system', '跟随系统']];
const system = window.matchMedia('(prefers-color-scheme: dark)');
let personal = null;

function guestMode() {
  try {
    const stored = localStorage.getItem(key);
    if (modes.some(([value]) => stored === value)) return stored;
  } catch {}
  return 'light';
}

function apply() {
  const mode = personal || guestMode();
  document.documentElement.dataset.colorMode = mode === 'dark' || (mode === 'system' && system.matches) ? 'dark' : 'light';
  for (const control of document.querySelectorAll('[data-color-mode-control]')) control.value = mode;
}

export function applyPersonalMode(value = null) {
  personal = value;
  apply();
}

// Before login the theme belongs to the guest browser.
export function colorModeControl() {
  const label = document.createElement('label');
  label.className = 'color-mode-control';
  const caption = document.createElement('span');
  caption.textContent = '显示主题';
  const select = document.createElement('select');
  select.dataset.colorModeControl = '';
  for (const [value, name] of modes) select.add(new Option(name, value));
  select.value = guestMode();
  select.addEventListener('change', () => {
    try { localStorage.setItem(key, select.value); } catch {}
    apply();
  });
  label.append(caption, select);
  return label;
}

system.addEventListener('change', apply);
window.addEventListener('storage', e => { if (e.key === null || e.key === key) apply(); });
apply();
