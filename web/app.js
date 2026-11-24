import { loginScreen } from './features/access.js';
import * as ui from './lib/ui.js';

import { detail, formDialog } from './lib/dialogs.js';

import { groups, routes } from './lib/navigation.js';

import { dashboard } from './dashboard.js';

import { renderFeature } from './features/index.js';

import { selectTab } from './features/shared.js';

import { profile } from './features/residency.js';

const { el, icon, button, toast } = ui;

const root = document.getElementById('app');

let state, revision, route;
let branding = {};
let agentRegion = null;
let epoch = 0,
  refreshing = false;
const seenAlerts = new Set();
function available(id) {
  return state?.user.routes.includes(id) && !state.uiSettings.hiddenRoutes.includes(id);
}
function landing() {
  return available('assistants') && state.agentCapabilities?.tools.length
    ? 'assistants'
    : state.user.routes.find(available);
}
function permitted(permission) {
  return state?.user.kind === 'owner' || state?.user.permissions.includes(permission);
}
function signedOut() {
  epoch++;
  state = null;
  agentRegion = null;
  revision = null;
  route = null;
  seenAlerts.clear();
  closeMenu();
  document.querySelectorAll('dialog[open]').forEach((d) => d.close());
  document.documentElement.removeAttribute('data-theme');
  document.title = '登录 · ' + (branding.brandName || '安康医养平台');
  root.replaceChildren(
    loginScreen(async (username, password) => {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      await readState();
      render();
      return true;
    }, branding)
  );
}
async function get(path) {
  const response = await fetch(path, { cache: 'no-store' });
  const value = await response.json();
  if (response.status === 401) {
    if (state) signedOut();
    throw new Error(value.error);
  }
  if (!response.ok) throw new Error(value.error || '无法读取记录');
  return value;
}
async function signOut() {
  try {
    const response = await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    if (!response.ok) throw new Error('退出失败，请重试。');
    signedOut();
  } catch (error) {
    toast(error.message);
  }
}
function applySnapshot(snapshot) {
  state = { ...snapshot.data, today: snapshot.today, audit: snapshot.audit };
  revision = snapshot.revision;
  branding = state.uiSettings;
  document.documentElement.dataset.theme = state.uiSettings.theme;
  const bucket = 'nh-alerts:' + state.user.id;
  if (!seenAlerts.size) {
    try {
      for (const id of JSON.parse(sessionStorage.getItem(bucket) || '[]')) seenAlerts.add(id);
    } catch {}
  }
  const pending = (state.gatewayAlerts || []).filter(
    (r) => r.status === '待复核' && !seenAlerts.has(r.id)
  );
  if (pending.length && permitted('alerts')) {
    pending.forEach((r) => seenAlerts.add(r.id));
    try {
      sessionStorage.setItem(bucket, JSON.stringify([...seenAlerts].slice(-500)));
    } catch {}
    toast(
      pending.length === 1
        ? '待核实预警 · ' + pending[0].room
        : '有 ' + pending.length + ' 条新设备预警待核实'
    );
  }
}

function go(destination, tab) {
  if (!available(destination)) {
    toast('当前账号未开放此模块');
    return;
  }
  if (tab) selectTab(destination, tab);
  if (route === destination) {
    closeMenu();
    if (tab) render();
  } else location.hash = destination;
}

function getRoute() {
  return location.hash.slice(1) || landing();
}

async function readState() {
  const current = epoch;
  const response = await fetch('/api/state', { cache: 'no-store' });
  if (response.status === 401) {
    signedOut();
    return false;
  }
  if (!response.ok) throw new Error('无法读取机构工作台，请重试。');
  const snapshot = await response.json();
  if (epoch !== current) return false;
  applySnapshot(snapshot);
  return true;
}

let saving = false;

async function command(action, payload, endpoint = '/api/commands') {
  if (saving) {
    toast('上一笔操作正在保存');
    return false;
  }
  saving = true;
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...(action ? { action } : {}),
        payload,
        revision,
      }),
    });
    const result = await response.json();
    if (response.status === 401) {
      signedOut();
      return false;
    }
    if (response.status === 409) {
      if (!(await readState())) return false;
      // A stale form may describe a bed, person or balance that has changed.
      document.querySelectorAll('dialog[open]').forEach((d) => d.close());
      render();
    }
    if (!response.ok) throw new Error(result.error || '操作未保存');
    if (!(await readState())) return true;
    document.querySelectorAll('dialog[open]').forEach((d) => d.close());
    render();
    toast(result.summary);
    return true;
  } catch (error) {
    toast(error.message || '连接失败，请刷新后核对记录。');
    return false;
  } finally {
    saving = false;
  }
}

function context() {
  return {
    state,
    get,
    available,
    agentRegion,
    startScopedAgent(place) {
      if (!available('assistants')) return;
      const region = {};
      for (const key of ['buildingId', 'floorId', 'roomId'])
        if (place[key]) region[key] = place[key];
      agentRegion = { ...region, label: place.label };
      go('assistants', 'runs');
    },
    clearAgentRegion() {
      agentRegion = null;
      render();
    },
    permitted,
    go,
    command,
    proposeRoom: (payload) => command(null, payload, '/api/agent/room-proposals'),
    dialog: formDialog,
    detail,
    toast,
    ui,
  };
}

function visibleGroups() {
  return groups
    .map(([name, items]) => [name, items.filter(([id]) => available(id))])
    .filter(([, items]) => items.length);
}

function moduleLink([id, label, iconName]) {
  const active = route === id;
  const link = el('a', 'nav-item' + (active ? ' active' : ''));
  link.href = '#' + id;
  if (active) link.setAttribute('aria-current', 'page');
  link.append(icon(iconName, 18), el('span', '', label));
  if (active) link.append(icon('chevron', 13));
  link.addEventListener('click', closeMenu);
  return link;
}

function sidebar() {
  const side = el('aside', 'sidebar');
  side.id = 'sidenav';
  const groupName = routes.get(route)?.group;
  const nav = el('nav', 'nav-list');
  nav.setAttribute('aria-label', '业务模块');
  for (const [name, items] of visibleGroups()) {
    const section = el('section', 'nav-group' + (name === groupName ? ' current' : ''));
    const head = el('h2', 'nav-label', name);
    section.append(head, ...items.map(moduleLink));
    nav.append(section);
  }
  const shortcuts = ['rooms', 'inbox', 'residents', 'reports'].filter(
    (id) => available(id) && routes.get(id).group !== groupName
  );
  if (shortcuts.length) {
    const section = el('section', 'nav-shortcuts');
    section.append(
      el('h2', 'nav-label', '常用入口'),
      ...shortcuts.map((id) => {
        const { label, icon: iconName } = routes.get(id);
        return moduleLink([id, label, iconName]);
      })
    );
    nav.append(section);
  }
  const org = el('div', 'side-org');
  const orgWords = el('div');
  orgWords.append(el('small', '', '当前机构'), el('strong', '', state.uiSettings.institutionName));
  org.append(icon('building', 22), orgWords);
  side.append(nav, org);
  return side;
}

function closeMenu() {
  const menu = root.querySelector('.menu-trigger');
  root.classList.remove('menu-open');
  menu?.setAttribute('aria-expanded', 'false');
}

function searchDialog() {
  const content = el('div', 'search-dialog');
  const input = el('input', 'search-input');
  input.type = 'search';
  input.placeholder = '搜索模块、长者姓名或档案号';
  input.setAttribute('aria-label', input.placeholder);
  const list = el('div', 'search-results');
  content.append(input, list);
  const modal = detail('全局搜索', content);
  const data = [
    ...[...routes]
      .filter(([id]) => available(id))
      .map(([id, r]) => ({
        label: r.label,
        keywords: id + ' ' + r.group,
        icon: r.icon,
        meta: r.group,
        open: () => go(id),
      })),
    ...(available('residents') ? state.residents : []).map((r) => ({
      label: r.name,
      keywords: r.id,
      icon: 'people',
      meta: '长者档案 · ' + r.id,
      open: () => profile(context(), r),
    })),
  ];
  function update() {
    const q = input.value.trim().toLowerCase();
    const subset = data
      .filter((r) => (r.label + ' ' + r.keywords).toLowerCase().includes(q))
      .slice(0, 12);
    list.replaceChildren(
      ...subset.map((r) => {
        const b = el('button', 'result');
        b.type = 'button';
        b.append(icon(r.icon), el('span', '', r.label), el('small', '', r.meta));
        b.addEventListener('click', () => {
          modal.close();
          r.open();
        });
        return b;
      })
    );
    if (!subset.length) list.append(ui.empty('没有找到匹配的模块或长者'));
  }
  input.addEventListener('input', update);
  update();
  input.focus();
}

function myPendingHandovers(data = state) {
  return data.handovers.filter((r) => r.status === '待签收' && r.assigneeId === data.user.id);
}

function notices() {
  const list = el('div', 'notice-list');
  const items = [
    ['待复核体征', state.vitals.filter((v) => v.status === '待复核').length, 'care', 'vitals'],
    ['待复核计划', state.plans.filter((p) => p.status === '待复核').length, 'assessments', 'plans'],
    ['待复核用药', state.medications.filter((p) => p.status === '待复核').length, 'medications'],
    [
      '低库存物资',
      state.inventory.filter((i) => i.quantity < i.minimum).length,
      'inventory',
      'stock',
    ],
  ];
  if (permitted('care'))
    items.unshift(['待我签收的交班', myPendingHandovers().length, 'care', 'handover']);
  if (available('inbox')) {
    if (permitted('alerts'))
      items.unshift([
        '待核实设备预警',
        state.gatewayAlerts.filter((x) => x.status === '待复核').length,
        'inbox',
        'alerts',
      ]);
    if (permitted('voice.confirm'))
      items.unshift(['待确认变更', state.voiceQueue.length, 'inbox', 'voice']);
  }
  const d = detail('待处理事项', list);
  for (const [label, value, destination, tab] of items) {
    if (!available(destination)) continue;
    const b = el('button', 'result');
    b.type = 'button';
    b.append(
      icon(routes.get(destination).icon),
      el('span', '', label),
      ui.badge(value + ' 项', value ? 'amber' : 'neutral')
    );
    b.addEventListener('click', () => {
      d.close();
      go(destination, tab);
    });
    list.append(b);
  }
}

function accountMenu() {
  const info = el('div', 'account-info');
  const actor = el('div', 'account-person');
  actor.append(
    el('span', 'header-avatar', state.user.displayName.slice(0, 1)),
    el('strong', '', state.user.displayName)
  );
  info.append(actor);
  for (const [key, value] of [
    ['当前岗位', state.user.role],
    ['所属机构', state.uiSettings.institutionName],
  ]) {
    const row = el('div', 'account-row');
    row.append(el('span', '', key), el('strong', '', value));
    info.append(row);
  }
  info.append(button('退出登录', signOut));
  detail('当前账号', info);
}

function masthead() {
  const bar = el('header', 'masthead');
  const menu = button(
    '',
    () => {
      const open = root.classList.toggle('menu-open');
      menu.setAttribute('aria-expanded', String(open));
      if (open) root.querySelector('.nav-item.active')?.focus();
    },
    'icon',
    'menu'
  );
  menu.classList.add('menu-trigger');
  menu.setAttribute('aria-label', '业务导航');
  menu.setAttribute('aria-controls', 'sidenav');
  menu.setAttribute('aria-expanded', 'false');
  const brand = el('a', 'brand');
  brand.href = '#' + landing();
  const mark = el('img', 'brand-mark');
  mark.src = '/assets/mark.svg';
  mark.alt = '';
  const words = el('span', 'brand-words');
  words.append(
    el('strong', '', state.uiSettings.brandName),
    el('small', '', state.uiSettings.institutionName)
  );
  brand.append(mark, words);
  const categories = el('nav', 'primary-nav');
  categories.setAttribute('aria-label', '业务分区');
  for (const [name, items] of visibleGroups()) {
    const current = routes.get(route)?.group === name;
    const link = el('a', current ? 'current' : '', name);
    link.href = '#' + (current ? route : items[0][0]);
    if (current) link.setAttribute('aria-current', 'true');
    categories.append(link);
  }
  const controls = el('div', 'global-tools');
  if (state.user.kind !== 'family') {
    const search = el('button', 'top-search');
    search.type = 'button';
    search.setAttribute('aria-label', '全局搜索');
    search.append(
      icon('search', 17),
      el('span', '', '搜索'),
      el('kbd', '', /Mac/.test(navigator.platform) ? '⌘ K' : 'Ctrl K')
    );
    search.addEventListener('click', searchDialog);
    const bell = button('', notices, 'icon', 'bell');
    bell.setAttribute('aria-label', '待处理事项');
    if (
      (available('care') && myPendingHandovers().length) ||
      (state.gatewayAlerts || []).some((r) => r.status === '待复核') ||
      (state.voiceQueue || []).length ||
      [...state.plans, ...state.vitals, ...state.medications].some((r) => r.status === '待复核') ||
      state.inventory.some((i) => i.quantity < i.minimum)
    )
      bell.classList.add('has-notice');
    controls.append(search, bell);
  }
  const account = el('button', 'account-trigger');
  account.type = 'button';
  account.setAttribute('aria-label', '账号与退出登录');
  account.append(
    el('span', 'header-avatar', state.user.displayName.slice(0, 1)),
    el('span', 'account-name', state.user.displayName),
    icon('down', 12)
  );
  account.addEventListener('click', accountMenu);
  controls.append(account);
  bar.append(menu, brand, categories, controls);
  return bar;
}

function contextBar() {
  const bar = el('div', 'contextbar');
  const crumbs = el('div', 'crumbs');
  const info = routes.get(route);
  crumbs.append(
    icon('location', 14),
    el('span', '', info.group),
    icon('chevron', 11),
    el('strong', '', info.label)
  );
  const date = el('time', 'business-date');
  date.dateTime = state.today;
  const [year, month, day] = state.today.split('-');
  const weekday = new Intl.DateTimeFormat('zh-CN', { weekday: 'long', timeZone: 'UTC' }).format(
    new Date(state.today + 'T12:00:00Z')
  );
  date.append(
    icon('calendar', 14),
    document.createTextNode(year + '年' + Number(month) + '月' + Number(day) + '日 · ' + weekday)
  );
  bar.append(crumbs, date);
  return bar;
}

let editing = false;
root.addEventListener('input', (e) => {
  if (e.target.closest('.agent-compose, .access-settings')) editing = true;
});

function render() {
  editing = false;
  if (!state) return;
  route = getRoute();
  if (!available(route)) {
    route = landing();
    history.replaceState(null, '', '#' + route);
  }
  closeMenu();
  document.title = (routes.get(route)?.label || '找不到页面') + ' · ' + state.uiSettings.brandName;
  const wrap = el('div', 'app-main');
  const main = el('main', 'content');
  main.id = 'content';
  main.tabIndex = -1;
  if (route === 'overview') main.append(dashboard(context()));
  else if (routes.has(route)) main.append(renderFeature(route, context()));
  else
    main.append(
      ui.heading(
        '找不到此页面',
        '请从左侧业务导航进入工作台。',
        button('返回运营总览', () => go('overview'), 'primary')
      )
    );
  wrap.append(contextBar(), main);
  const shade = el('button', 'menu-backdrop');
  shade.type = 'button';
  shade.setAttribute('aria-label', '收起业务导航');
  shade.addEventListener('click', closeMenu);
  root.replaceChildren(masthead(), sidebar(), shade, wrap);
}

function failed(error) {
  const section = el('section', 'loading');
  section.append(el('p', '', error.message), button('重新载入', load, 'primary'));
  root.replaceChildren(section);
}

async function load() {
  try {
    branding = await get('/api/branding');
    if (await readState()) render();
  } catch (error) {
    failed(error);
  }
}

window.addEventListener('hashchange', () => {
  if (state) {
    document.querySelectorAll('dialog[open]').forEach((d) => d.close());
    render();
    window.scrollTo(0, 0);
  }
});

document.querySelector('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  document.getElementById('content')?.focus();
});

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && root.classList.contains('menu-open')) {
    closeMenu();
    root.querySelector('.menu-trigger')?.focus();
  }
  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === 'k' &&
    state &&
    state.user.kind !== 'family' &&
    !document.querySelector('dialog[open]')
  ) {
    event.preventDefault();
    searchDialog();
  }
});

async function refresh() {
  if (!state || saving || refreshing || document.hidden) return;
  refreshing = true;
  const current = epoch,
    version = revision;
  try {
    const check = await get('/api/version');
    if (current !== epoch || saving || version !== revision) return;
    if (
      check.revision === revision &&
      check.userId === state.user.id &&
      check.today === state.today
    )
      return;
    const snapshot = await get('/api/state');
    if (current !== epoch || saving || version !== revision) return;
    const changedUser =
      state.user.id !== snapshot.data.user.id ||
      JSON.stringify(state.user.permissions) !== JSON.stringify(snapshot.data.user.permissions);
    const dialogs = [...document.querySelectorAll('dialog[open]')];
    if (editing && !changedUser && !dialogs.length) return;
    if (dialogs.length && !changedUser) {
      const obsolete = dialogs.some(
        (d) =>
          d.dataset.proposalId &&
          !(snapshot.data.voiceQueue || []).some((r) => r.id === d.dataset.proposalId)
      );
      const settled = dialogs.some(
        (d) =>
          d.dataset.agentRunId &&
          !(snapshot.data.agentRuns || []).some(
            (r) => r.id === d.dataset.agentRunId && r.status === 'awaiting_approval'
          )
      );
      const received = dialogs.some(
        (d) =>
          (d.dataset.handoverId &&
            !myPendingHandovers(snapshot.data).some((r) => r.id === d.dataset.handoverId)) ||
          (d.dataset.pendingHandoverId &&
            !snapshot.data.handovers.some((r) => r.id === d.dataset.pendingHandoverId && r.status === '待签收'))
      );
      if (!obsolete && !settled && !received) return;
    }
    dialogs.forEach((d) => d.close());
    applySnapshot(snapshot);
    render();
  } catch {
    /* Offline clients keep their form, and submit checks the revision. */
  } finally {
    refreshing = false;
  }
}
window.addEventListener('focus', refresh);
document.addEventListener('visibilitychange', refresh);
setInterval(refresh, 4000);
load();
