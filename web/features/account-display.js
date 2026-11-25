import { defaults, families, preferenceView, refreshPreferences, resolveFont, saveDisplay } from '../lib/reading-display.js';
import { modes } from '../lib/color-mode.js';
import { btn, node } from './shared.js';

export function accountDisplay(ctx) {
  const panel = node('form', 'fx-panel personal-display');
  const select = (text, name, options) => {
    const input = node('select');
    input.name = name;
    for (const [value, label] of options) input.add(new Option(label, value));
    return node('label', 'personal-choice', [node('span', '', text), input]);
  };
  const size = node('input');
  size.type = 'range'; size.name = 'level'; size.min = 1; size.max = 10; size.step = 1;
  const output = node('output');
  const preview = node('div', 'personal-type-sample', '今日照护记录 · 08:30 完成晨间巡查');
  const fontNote = node('p', 'reading-font-note');
  const status = node('p', 'personal-save-status');
  status.setAttribute('role', 'status');
  const save = node('button', 'btn btn-primary', '保存显示设置');
  save.type = 'submit';
  const reload = btn(ctx, '重新载入', load);
  let version;
  panel.append(node('h2','personal-panel-title','外观与显示'),
    select('设置保存位置','source',[['account','跟随账号 · 跨设备同步'],['device','仅此设备']]),
    select('显示主题','mode',modes),
    select('界面密度','density',[['comfortable','舒适'],['compact','紧凑']]),
    select('界面动效','motion',[['system','跟随系统'],['reduced','减少动态效果']]),
    select('界面字体','family',Object.entries(families).map(([key,font])=>[key,font.label])),
    node('label','personal-choice',[node('span','','正文字号'), node('span','personal-size',[size, output])]),
    preview, fontNote,
    node('div','personal-display-actions',[save, reload, btn(ctx,'恢复默认',()=>{ fill(defaults); markDirty(true); })]), status);
  const f = panel.elements;

  function sample() {
    const level = Number(size.value), family = f.family.value;
    output.textContent = level + ' / 10 档 · ' + (11 + level) + ' px';
    size.setAttribute('aria-valuetext', output.textContent);
    preview.style.fontSize = (11 + level) + 'px';
    resolveFont(family).then(font => {
      if (family !== f.family.value) return;
      preview.style.fontFamily = font.css || 'system-ui';
      fontNote.textContent = font.note;
    });
  }

  function fill(v) {
    for (const key of Object.keys(defaults)) f[key].value = v[key];
    sample();
  }

  function markDirty(value) {
    if (ctx.workspaceState) ctx.workspaceState.unsaved = value;
  }

  function reset() {
    markDirty(false);
    const state = preferenceView();
    version = state.version;
    f.source.value = state.following ? 'account' : 'device';
    fill(state.values);
  }

  async function load() {
    try { await refreshPreferences(); reset(); status.textContent = '已载入当前设置。'; }
    catch (error) { status.textContent = error.message; }
  }

  f.source.onchange = () => {
    markDirty(true);
    const state = preferenceView();
    version = state.version;
    fill(f.source.value === 'account' ? state.remote : state.local);
  };
  panel.oninput = () => { markDirty(true); sample(); };
  panel.addEventListener('submit', async event => {
    event.preventDefault();
    const values = Object.fromEntries(Object.keys(defaults).map(key => [key, f[key].value]));
    values.level = Number(values.level);
    const follow = f.source.value === 'account';
    save.disabled = true;
    try {
      if (await saveDisplay(follow, values, version)) {
        markDirty(false);
        version = preferenceView().version;
        status.textContent = follow ? '已保存到账号，其他设备可同步。' : '已保存在此设备。';
      }
    } catch (error) { status.textContent = error.message; }
    finally { save.disabled = false; }
  });
  reset();
  return panel;
}
