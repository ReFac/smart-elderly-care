import { openLinkedBedCard } from './features/med-rounds.js';
import { chatLauncher, openChat, toggleChat, clearChat, checkChatUser } from './features/assistant-chat.js';
import { hasNewNotice, quickDestinations, staffNotices, supplyOrders } from './features/assistant-actions.js';
import { loginScreen } from './features/access.js';
import { redeemPasswordReset } from './features/identity.js';
import * as ui from './lib/ui.js';
import { changePreview, confirmChange } from './lib/change-review.js';

import { detail, formDialog } from './lib/dialogs.js';

import { routes } from './lib/navigation.js';

import { dashboard, operationalOverview } from './dashboard.js';

import { renderFeature } from './features/index.js';

import { selectTab, resetSelectedTabs } from './features/shared.js';

import { profile, renewalReminders, reopenBedFilter } from './features/residency.js';
import { dueMedicationCount } from './features/medication-rules.js';
import { pendingLeadCalls } from './features/leads.js';
import { residentLabel, residentHref, staffLabel } from './features/people-labels.js';
import { openDossier, residentWorkspaceTab } from './features/dossier.js';
import { canOpenPermissionRequests, openPermissionRequests, pendingPermissionRequests } from './features/permission-requests.js';
import { colorModeControl, setColorModeAccount } from './lib/color-mode.js';

import { restoreCarePlanTab } from './features/care-plan-editor.js';
import { WorkspaceTabs } from './lib/workspace-tabs.js';
import { menuFor, deskPath, viewIcon } from './lib/desk-navigation.js';
import { officeHome } from './features/office-home.js';

const desk = new WorkspaceTabs();
const expandedGroups = new Set();
let deskMenu = [], sidebarScroll = 0, compact = false, largeText = false;
let lastMenuGroup, restoredTabsFor;
const { el, icon, button, toast } = ui;

const root = document.getElementById('app');

let state, revision, route;
let branding = {};
let epoch = 0,
  refreshing = false;
let deferredRefresh = null;
const seenAlerts = new Set();
let historyScope = {};
let focusIds = [];
let reviewing = false;
let residentOverlay = null;
function openChanges(filters = {}) {
  if (!available('history')) return;
  historyScope = { ...filters };
  const historyPage = desk.pages.get('#history');
  if (historyPage) historyPage.node = null;
  document.querySelectorAll('dialog[open]').forEach((d) => d.close());
  if (route === 'history') render();
  else go('history');
}
function available(id) {
  const canonical = {rooms:'beds',intake:'residents'}[id] || id;
  return state?.user.routes.includes(canonical) && !state.uiSettings.hiddenRoutes.includes(canonical);
}
function landing() {
  return available('overview') ? 'overview' : state.user.routes.find((id) => routes.has(id) && available(id));
}
function permitted(permission) {
  return state?.user.kind === 'owner' || state?.user.permissions.includes(permission);
}
function signedOut() {
  epoch++;
  deferredRefresh = null;
  state = null;
  resetDesk();
  root.classList.remove("desk-shell");
  residentOverlay = null;
  clearChat();
  revision = null;
  route = null;
  seenAlerts.clear();
  historyScope = {};
  focusIds = [];
  closeMenu();
  document.querySelectorAll('dialog[open]').forEach((d) => d.close());
  document.documentElement.removeAttribute('data-theme');
  setColorModeAccount();
  document.title = '登录 · ' + (branding.brandName || '医养管理平台');
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
    }, branding, async () => {
      await readState();
      render();
    }),
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
function visibilityChanged(snapshot) {
  if (!state) return false;
  if (state.actorStamp !== snapshot.actorStamp ||
      JSON.stringify(state.uiSettings.hiddenRoutes) !== JSON.stringify(snapshot.data.uiSettings.hiddenRoutes)) return true;
  const visible = new Set(snapshot.data.residents.map(person => person.id));
  return state.residents.some(person => !visible.has(person.id));
}

function applySnapshot(snapshot) {
  deferredRefresh = null;
  if (visibilityChanged(snapshot)) {
    document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
    residentOverlay = null;
    historyScope = {};
    focusIds = [];
    clearChat();
    resetDesk();
  } else desk.invalidate();
  state = {
    ...snapshot.data,
    actorStamp: snapshot.actorStamp,
    today: snapshot.today,
    audit: snapshot.audit,
    revision: snapshot.revision,
  };
  for (const [key,page] of desk.pages) {
    const work = new URLSearchParams(key.split('?')[1]).get('work');
    if (work && page.render) {
      const current = restoreWorkspaceDocument(page.route,work);
      if (!current) desk.pages.delete(key);
      else page.title = current.title;
    }
  }
  checkChatUser(context());
  revision = snapshot.revision;
  branding = state.uiSettings;
  document.documentElement.dataset.theme = state.uiSettings.theme;
  setColorModeAccount(state.user.id);
  const bucket = 'nh-alerts:' + state.user.id;
  if (!seenAlerts.size) {
    try {
      for (const id of JSON.parse(sessionStorage.getItem(bucket) || '[]')) seenAlerts.add(id);
    } catch {}
  }
  const pending = (state.gatewayAlerts || []).filter(
    (r) => r.status === '待复核' && !seenAlerts.has(r.id),
  );
  const trialAlerts = unresolvedTrials().filter(row => !seenAlerts.has('trial-expiry:' + row.id));
  const familyMessage = state.familyRoundInbox?.messages.find((m) => m.day === state.today && !m.readAt);
  const roundsId = familyMessage ? 'family-round:' + familyMessage.id :
    state.roundsNoticeCount && available('inbox') ? 'staff-round:' + state.today + ':' + state.roundsNoticeCount : '';
  if (pending.length && permitted('alerts')) {
    pending.forEach((r) => seenAlerts.add(r.id));
    try {
      sessionStorage.setItem(bucket, JSON.stringify([...seenAlerts].slice(-500)));
    } catch {}
    toast(
      pending.length === 1
        ? '待核实预警 · ' + pending[0].room
        : '有 ' + pending.length + ' 条新设备预警待核实',
    );
  } else if (trialAlerts.length) {
    for (const row of trialAlerts) seenAlerts.add('trial-expiry:' + row.id);
    try {
      sessionStorage.setItem(bucket, JSON.stringify([...seenAlerts].slice(-500)));
    } catch {}
    toast('有 ' + trialAlerts.length + ' 位长辈试住期满，床位已释放。请在待处理事项中确认或取消入住。');
  } else if (roundsId && !seenAlerts.has(roundsId)) {
    seenAlerts.add(roundsId);
    try {
      sessionStorage.setItem(bucket, JSON.stringify([...seenAlerts].slice(-500)));
    } catch {}
    toast(familyMessage ? '今日照护简报已送达，可在家属服务中查看。' : '有 ' + state.roundsNoticeCount + ' 位长辈的巡查事项待跟进，请查看右上角铃铛。');
  }
}

function go(destination, tab, onArrival, query) {
  if (!available(destination)) {
    toast('当前账号未开放此模块');
    return;
  }
  if (destination === 'rooms') { destination = 'beds'; tab = 'plan'; }
  if (destination === 'intake') destination = 'residents';
  const params = new URLSearchParams(query);
  if (tab) params.set('tab', tab);
  if (query && destination === 'beds') reopenBedFilter();
  navigateHash('#' + destination + (params.size ? '?' + params : ''), onArrival);
}

function navigateHash(hash, onArrival) {
  closeMenu();
  if (location.hash !== hash) {
    document.querySelectorAll('dialog[open]').forEach(d => d.close());
    residentOverlay = null;
    window.history.pushState(null, '', hash);
    render();
  } else if (!desk.active) render();
  onArrival?.();
}

function saveDesk() {
  if (!state || !restoredTabsFor) return;
  // Only route/view IDs belong in session storage. Never serialize a search, form, name or record.
  const keys = [...desk.pages.keys()].filter(key=>/^#[a-zA-Z]+(?:\?(?:view=cockpit|tab=[a-zA-Z0-9_-]+))?$/.test(key));
  try { sessionStorage.setItem('nh-open-views',JSON.stringify({scope:restoredTabsFor,keys})); } catch {}
}

function restoreDeskPages() {
  if (restoredTabsFor === state.actorStamp) return;
  restoredTabsFor=state.actorStamp;
  let saved;
  try { saved=JSON.parse(sessionStorage.getItem('nh-open-views')); } catch {}
  if (saved?.scope !== restoredTabsFor || !Array.isArray(saved.keys)) return;
  const visible = menuFor(context());
  for (const key of saved.keys) {
    if (typeof key!=='string' || !/^#[a-zA-Z]+(?:\?(?:view=cockpit|tab=[a-zA-Z0-9_-]+))?$/.test(key)) continue;
    const [r,query]=key.slice(1).split('?');
    if (!routes.has(r) || !available(r)) continue;
    const params = new URLSearchParams(query),tab=params.get('tab') || undefined,view=params.get('view') || undefined;
    const path=deskPath(visible,r,tab,view);
    // Views without static labels are rendered and named on first access.
    desk.ensure({key,route:r,tab,view,title:path.label || routes.get(r).label});
  }
}

function resetDesk() {
  desk.clear();
  restoredTabsFor = null;
  try { sessionStorage.removeItem('nh-open-views'); } catch {}
  expandedGroups.clear();
  resetSelectedTabs();
  lastMenuGroup = null;
  sidebarScroll = 0;
}

function openWorkspaceTab(destination, spec) {
  if (!available(destination) || !spec?.id || typeof spec.render !== 'function') return false;
  const hash = '#' + destination + '?' + new URLSearchParams({work: spec.id});
  desk.ensure({key:hash, route:destination, ...spec});
  navigateHash(hash);
  return true;
}

function closeWorkspaceTab(key = desk.active) {
  const next = desk.remove(key);
  saveDesk();
  if (next) navigateHash(next);
  else if (desk.active) updateTabStrip();
}

function updateTabStrip() {
  root.querySelector('.desk-tabbar')?.replaceWith(tabStrip());
}

function tabStrip() {
  return desk.strip({activate: navigateHash, close: closeWorkspaceTab,
    refresh: async () => {
      const here = desk.active;
      try { if (await readState()) { render(); if (desk.active === here) toast('已刷新当前页签'); } }
      catch (error) { toast(error.message); }
    },
    manage: () => {
      const box = el('div', 'desk-tab-manager');
      for (const page of desk.pages.values()) {
        const row = el('div');
        row.append(button(page.title, () => { dialog.close(); navigateHash(page.key); }, 'ghost'));
        if (!page.pinned) row.append(button('关闭', () => {
          dialog.close(); closeWorkspaceTab(page.key);
        }));
        box.append(row);
      }
      const dialog = detail('已打开的页签',box);
    }});
}

function getRoute() {
  const original=location.hash.slice(1).split('?')[0];
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const tab = params.get('tab');
  if (tab && available(original)) selectTab(original, tab);
  if (original === 'assistants') {
    const home = landing();
    window.history.replaceState(null, '', '#' + home);
    requestAnimationFrame(() => { if (state) openChat(context); });
    return home;
  }
  if (original === 'rooms' && available('beds')) {
    selectTab('beds', 'plan');
    history.replaceState(null, '', '#beds?tab=plan');
    return 'beds';
  }
  if (['residents', 'intake'].includes(original) && available('residents')) {
    if (original === 'intake') {
      if (!tab) params.set('tab', 'all');
      selectTab('residents', params.get('tab'));
      history.replaceState(null, '', '#residents?' + params);
    }
    return 'residents';
  }
  return original || landing();
}

async function readState({publicLanding = false} = {}) {
  const current = epoch;
  const response = await fetch('/api/state', { cache: 'no-store' });
  if (response.status === 401) {
    if (publicLanding) {
      location.replace('/visit');
      return false;
    }
    signedOut();
    return false;
  }
  if (!response.ok) throw new Error('无法读取机构工作台，请重试。');
  const snapshot = await response.json();
  if (epoch !== current) return false;
  if (state?.user.id !== snapshot.data.user.id || snapshot.revision >= revision)
    applySnapshot(snapshot);
  return true;
}

async function checkNavigation() {
  const current = epoch;
  const check = await get('/api/assistant/navigation-version');
  if (current !== epoch || !state) return false;
  if (check.revision === revision && check.today === state.today && check.userId === state.user.id &&
      check.actorStamp && check.actorStamp === state.actorStamp) return true;
  if (!(await readState()) || current !== epoch) return false;
  render();
  return true;
}

let saving = false;

function changesReceipt(result) {
  toast(result.summary || '改动已保存');
  if (!available('history') || !result.revision) return;
  const host = document.getElementById('announcer');
  const view = el('button', 'change-receipt-link', '查看本次改动');
  view.type = 'button';
  view.onclick = () => openChanges({ revision: result.revision });
  host.append(view);
}

async function undoRevision(change, dossierDialog) {
  return submitChange({
    action: 'history.undo',
    url: '/api/history/' + change.revision + '/undo',
    payload: {},
    dossierDialog,
    review: {
      title: '撤销这次改动',
      target: change.summary,
      confirmLabel: '确认撤销',
      fields: [
        ['原版本', 'v' + change.revision],
        ['原经办人', change.actorName],
        ['执行结果', '恢复可撤销字段，并新增一条撤销记录。'],
      ],
    },
  });
}

async function command(action, payload, options = {}) {
  return submitChange({ action, url: '/api/commands', payload, review: options });
}

async function submitChange({ action, url, payload, review = {}, dossierDialog }) {
  if (saving || reviewing) {
    toast('请先完成当前改动');
    return false;
  }
  const beforeVersion = review.expectedRevision ?? revision;
  const previousEpoch = epoch;
  const prior = state;
  function preserveDossier() {
    if (!dossierDialog?.open || !available('history')) return false;
    const residentId = dossierDialog.dataset.roundsResidentId;
    const before = prior.residents.find((r) => r.id === residentId);
    const after = state.residents.find((r) => r.id === residentId);
    return before && after && before.bedId === after.bedId && before.status === after.status &&
      JSON.stringify(prior.user) === JSON.stringify(state.user) &&
      JSON.stringify(prior.uiSettings.hiddenRoutes) === JSON.stringify(state.uiSettings.hiddenRoutes);
  }
  let choice;
  if (review.confirmed) choice = { comment: review.comment || '' };
  else {
    reviewing = true;
    try {
      choice = await confirmChange(
        changePreview(state, action, payload, { allowComment: true, ...review }),
      );
    } finally {
      reviewing = false;
    }
    if (!choice || previousEpoch !== epoch || !state) return;
  }
  saving = true;
  try {
    const envelope =
      url === '/api/commands' ? { action, payload } : action === 'history.undo' ? {} : { payload };
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...envelope, comment: choice.comment, revision: beforeVersion }),
    });
    const result = await response.json();
    if (response.status === 401) {
      signedOut();
      return false;
    }
    if (response.status === 409) {
      if (!(await readState())) return false;
      // A stale form may describe a bed, person or balance that has changed.
      if (!preserveDossier()) document.querySelectorAll('dialog[open]').forEach((d) => d.close());
      render();
    }
    if (!response.ok) throw new Error(result.error || '操作未保存');
    if (action === 'account.changePassword') {
      signedOut();
      return true;
    }
    if (!(await readState())) return true;
    const keptDossier = preserveDossier();
    if (!keptDossier) document.querySelectorAll('dialog[open]').forEach((d) => d.close());
    const effectIds = (result.affected || []).map((r) => r.entityId);
    focusIds = [
      ...new Set([...effectIds, payload.taskId, payload.residentId, payload.id].filter(Boolean)),
    ];
    let destination = null;
    if (['gw.confirm', 'care.completeTask'].includes(action) && available('care')) {
      const original = prior.voiceQueue?.find((r) => r.id === payload.proposalId);
      if (original?.taskId) focusIds.unshift(original.taskId);
      destination = ['care', 'completed'];
    } else if (action === 'history.undo' && !dossierDialog) historyScope.revision = result.revision;
    if (destination) {
      const hash = '#' + destination[0] + '?' + new URLSearchParams({tab:destination[1]});
      if (location.hash !== hash) window.history.pushState(null,'',hash);
    }
    render();
    if (!review.quiet) {
      if (keptDossier) toast(result.summary || '改动已保存');
      else changesReceipt(result);
    }
    const target = document.querySelector('.change-focus');
    if (target && !keptDossier) target.scrollIntoView({ block: 'nearest' });
    focusIds = [];
    return review.returnResult || keptDossier ? result : true;
  } catch (error) {
    toast(error.message || '连接失败，请刷新后核对记录。');
    return false;
  } finally {
    saving = false;
  }
}

function context() {
  const page = desk.pages.get(desk.active);
  return {
    current: context,
    workspaceState: page?.state,
    openWorkspaceTab, closeWorkspaceTab,
    state,
    get: page ? async path => {
      page.pendingReads++;
      try { return await get(path); }
      finally {
        page.pendingReads--;
        if (page.key !== desk.active) page.node = null;
      }
    } : get,
    historyScope,
    openChanges,
    undoRevision,
    confirmChange,
    checkNavigation,
    focusIds,
    async refreshWorkspace(origin) {
      if (!(await readState())) return false;
      const stillHere = !origin || origin.isConnected;
      render();
      return stillHere;
    },
    available,
    startScopedAgent(place) { openChat(context, place); },
    permitted,
    go,
    command,
    proposeRoom: (payload) =>
      submitChange({ action: 'gw.propose', payload, url: '/api/agent/room-proposals' }),
    dialog: formDialog,
    detail: (title,content) => detail(title,content,{drawer:true}),
    toast,
    ui,
  };
}

function sidebar() {
  const side = el('aside', 'sidebar');
  side.id = 'sidenav';
  const brand = el('a', 'desk-brand');
  brand.href = '#' + landing();
  const mark = el('img'); mark.src = '/assets/desk-mark.svg'; mark.alt = '';
  brand.append(mark, el('strong', '', state.uiSettings.brandName));
  brand.title = state.uiSettings.brandName;
  const nav = el('nav', 'nav-list');
  nav.setAttribute('aria-label', '业务模块');
  const current = desk.pages.get(desk.active);
  const path = deskPath(deskMenu,route,current?.tab,current?.view);
  if (path.group && lastMenuGroup !== path.group) {
    expandedGroups.clear();
    expandedGroups.add(path.group);
  }
  lastMenuGroup = path.group;
  function entry(id, label, glyph, tab, view) {
    if (id === 'family' && state.user.portalSelf) label = '长辈服务';
    const active = route === id && (current?.tab || undefined) === tab && current?.view === view;
    const a = el('a', 'nav-item' + (active ? ' active' : ''));
    const params = new URLSearchParams();
    if (tab) params.set('tab',tab);
    if (view) params.set('view',view);
    a.href = '#' + id + (params.size ? '?' + params : '');
    a.title = label;
    if (active) a.setAttribute('aria-current','page');
    a.append(icon(glyph,16),el('span','',label));
    a.onclick = e => {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault(); navigateHash(a.hash);
    };
    return a;
  }
  for (const group of deskMenu) {
    if (group.route) {
      nav.append(entry(group.route,group.label,group.icon,undefined,group.view));
      continue;
    }
    const section = el('section','desk-nav-section');
    const toggle = el('button','desk-nav-group');
    toggle.type = 'button'; toggle.title = group.label;
    toggle.append(icon(group.icon,17),el('span','',group.label),icon('down',12));
    const children = el('div','desk-nav-children');
    for (const [id,label,tab] of group.children)
      children.append(entry(id,label,viewIcon(tab,routes.get(id).icon),tab));
    function expand() {
      const open = expandedGroups.has(group.label);
      toggle.setAttribute('aria-expanded',String(open));
      section.classList.toggle('current',path.group === group.label);
      children.hidden = !open;
    }
    toggle.onclick = () => {
      if (compact && !smallScreen()) { compact = false; applyDeskSize(); expandedGroups.add(group.label); }
      else if (expandedGroups.has(group.label)) expandedGroups.delete(group.label);
      else expandedGroups.add(group.label);
      expand();
    };
    expand(); section.append(toggle,children); nav.append(section);
  }
  side.append(brand,nav);
  return side;
}

const smallScreen = () => matchMedia('(max-width: 760px)').matches;
function applyDeskSize() {
  root.classList.toggle('desk-compact',compact);
  document.documentElement.classList.toggle('desk-large-text',largeText);
  root.querySelector('.menu-trigger')?.setAttribute('aria-expanded',
    String(smallScreen() ? root.classList.contains('menu-open') : !compact));
}
function closeMenu() {
  const menu = root.querySelector('.menu-trigger');
  root.classList.remove('menu-open');
  menu?.setAttribute('aria-expanded', String(!smallScreen() && !compact));
}

function searchDialog() {
  const content = el('div', 'search-dialog');
  const input = el('input', 'search-input');
  input.type = 'search';
  input.placeholder = '搜索模块、长辈姓名或档案号';
  input.setAttribute('aria-label', input.placeholder);
  const list = el('div', 'search-results');
  content.append(input, list);
  const modal = detail('全局搜索', content);
  const directory = deskMenu.flatMap(group => group.children
    ? group.children.map(([route,label,tab])=>({label,keywords:group.label + ' ' + label,
        icon:viewIcon(tab,routes.get(route).icon),meta:group.label,open:()=>go(route,tab)}))
    : [{label:group.label,keywords:group.label,icon:group.icon,meta:'业务页面',
        open:()=>go(group.route,undefined,undefined,group.view ? {view:group.view} : undefined)}]);
  const data = [
    ...directory,
    ...quickDestinations.filter(r => available(r.route) && (!r.grant || state.allowedActions.includes(r.grant))).map(r => ({
      label: r.label, keywords: r.words, icon: routes.get(r.route).icon, meta: routes.get(r.route).label,
      open: () => go(r.route, r.tab),
    })),
    ...[...routes]
      .filter(([id]) => !['rooms','intake'].includes(id) && available(id))
      .map(([id, r]) => ({
        label: r.label,
        keywords: id + ' ' + r.group + (id === 'faq' ? ' 帮助中心 使用指南' : ''),
        icon: r.icon,
        meta: r.group,
        open: () => go(id),
      })),
    ...state.residents.filter(r => residentHref(context(), r)).map((r) => ({
      label: residentLabel(context(), r),
      keywords: r.id,
      href: residentHref(context(), r),
      icon: 'people',
      meta: '长辈档案 · ' + r.id,
      open: () => profile(context(), r),
    })),
  ];
  function update() {
    const q = input.value.trim().normalize('NFKC').toLowerCase();
    const subset = [], matched = new Set();
    for (const row of data) {
      const key = row.href || row.label;
      if (matched.has(key) || !(row.label + ' ' + row.keywords).normalize('NFKC').toLowerCase().includes(q)) continue;
      matched.add(key); subset.push(row);
      if (subset.length === 12) break;
    }
    list.replaceChildren(
      ...subset.map((r) => {
        const b = el(r.href ? 'a' : 'button', 'result');
        if (r.href) {
          b.href = r.href;
          b.classList.add('resident-profile-link');
        }
        else b.type = 'button';
        b.append(icon(r.icon), el('span', '', r.label), el('small', '', r.meta));
        if (!r.href) b.addEventListener('click', () => {
          modal.close();
          r.open();
        });
        return b;
      }),
    );
    if (!subset.length) list.append(ui.empty('没有找到匹配的模块或长辈'));
  }
  input.addEventListener('input', update);
  update();
  input.focus();
}

function myPendingHandovers(data = state) {
  return data.handovers.filter((r) => r.status === '待签收' && r.assigneeId === data.user.id);
}

function unresolvedTrials() {
  return available('residents') && state.allowedActions.includes('care.confirmStay')
    ? state.residents.filter(r => r.status === '试住到期待确认') : [];
}

function myTrialFollowups() {
  return (state.trialFollowups || []).filter(r => r.status === '待回访' && r.assigneeId === state.user.id);
}

function todayBillingNotices() {
  return (state.billingNotices || []).filter((row) => row.date === state.today).length;
}

function pendingRenewals() {
  return available('residents') && state.allowedActions.includes('care.renew')
    ? renewalReminders(state.residents).length : 0;
}

function notices() {
  const list = el('div', 'notice-list');
  const items = [
    ['待复核计划', state.plans.filter((p) => p.status === '待复核').length, 'assessments', 'plans'],
    ['待复核用药', state.medications.filter((p) => p.status === '待复核').length, 'medications'],
    [
      '低库存物资',
      state.inventory.filter((i) => i.quantity < i.minimum).length,
      'inventory',
      'stock',
    ],
  ];
  const renewals = pendingRenewals();
  if (renewals)
    items.unshift([
      '到期续住',
      renewals,
      'residents',
      'renew',
    ]);
  if (permitted('clinical')) {
    items.unshift(
      ['到时给药', dueMedicationCount(state.medications), 'medications', 'reminders'],
      [
        '到期随访',
        (state.followups || []).filter((r) => r.status === '待随访' && r.dueDate <= state.today)
          .length,
        'care',
        'followups',
      ],
    );
    items.unshift([
      '待复核体征',
      state.vitals.filter((v) => v.status === '待复核').length,
      'care',
      'vitals',
    ]);
  }
  if (permitted('care')) {
    const latest = new Map();
    for (const a of state.assessments)
      if (!a.historyOnly && (!latest.has(a.residentId) || latest.get(a.residentId).date <= a.date))
        latest.set(a.residentId, a);
    const due = state.residents.filter(
      (r) =>
        r.status === '在住' &&
        latest.get(r.id)?.reviewDate &&
        latest.get(r.id).reviewDate <= state.today,
    );
    items.unshift(['到期复评', due.length, 'assessments', 'review']);
  }
  if (permitted('care'))
    items.unshift(['待我签收的交班', myPendingHandovers().length, 'care', 'handover']);
  if (unresolvedTrials().length)
    items.unshift(['试住期满待确认入住', unresolvedTrials().length, 'residents', 'trials']);
  if (state.groupActivityDue)
    items.unshift(['集体活动待确认', state.groupActivityDue, 'care', 'groupLife']);
  if (myTrialFollowups().length)
    items.unshift(['待我办理的试住回访', myTrialFollowups().length, 'residents', 'followups']);
  if (available('leads') && pendingLeadCalls(state))
    items.unshift(['意向客户待电话回访', pendingLeadCalls(state), 'leads', 'contacts']);
  if (available('billing') && todayBillingNotices())
    items.unshift(['今日账务提醒', todayBillingNotices(), 'billing', 'billingNotices']);
  if (available('inbox')) {
    if (state.roundsNoticeCount)
      items.unshift(['今日巡查提醒', state.roundsNoticeCount, 'inbox', 'rounds']);
    if (permitted('alerts'))
      items.unshift([
        '待核实设备预警',
        state.gatewayAlerts.filter((x) => x.status === '待复核').length,
        'inbox',
        'alerts',
      ]);
    if (state.allowedActions.includes('gw.confirm'))
      items.unshift(['待确认变更', state.voiceQueue.length, 'inbox', 'voice']);
  }
  const d = detail('待处理事项', list);
  if (state.user.kind !== 'family') {
    const ctx = context();
    if (canOpenPermissionRequests(ctx)) {
      const count = pendingPermissionRequests(ctx);
      const entry = el('button', 'result');
      entry.type = 'button';
      entry.append(icon('shield'), el('span', '', '权限申请'), ui.badge(count + ' 项待我审批', count ? 'amber' : 'neutral'));
      entry.addEventListener('click', () => { d.close(); openPermissionRequests(context()); });
      list.append(entry);
    }
    for (const [label, panel] of [
      ['全员通知', staffNotices],
      ...((state.supplyOrders || []).some(r => r.assigneeId === state.user.id && r.status === '待执行')
        ? [['我的物资待办', ctx => supplyOrders(ctx, true)]] : []),
    ]) {
      const entry = button(label, () => { d.close(); detail(label, panel(context())); }, 'secondary', 'bell');
      list.append(entry);
    }
  }
  for (const [label, value, destination, tab] of items) {
    if (!available(destination)) continue;
    const b = el('button', 'result');
    b.type = 'button';
    b.append(
      icon(routes.get(destination).icon),
      el('span', '', label),
      ui.badge(value + ' 项', value ? 'amber' : 'neutral'),
    );
    b.addEventListener('click', () => {
      d.close();
      go(destination, tab);
    });
    list.append(b);
  }
  if (!list.childElementCount) list.append(ui.empty('当前账号没有需要处理的事项'));
}

function accountMenu() {
  const info = el('div', 'account-info');
  const actor = el('div', 'account-person');
  actor.append(
    el('span', 'header-avatar', state.user.displayName.slice(0, 1)),
    el('strong', '', staffLabel(context(), state.user)),
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
  const dialog = detail('当前账号', info);
  info.append(
    colorModeControl(),
    button(
      '个人中心',
      () => {
        dialog.close();
        go('account');
      },
      'primary',
    ),
    button('退出登录', signOut),
  );
}

function viewSwitcher(rootViews) {
  if (!rootViews?.childElementCount) return null;
  const pop = el('details','desk-view-switcher');
  const summary = el('summary','','业务视图');
  summary.append(icon('down',12));
  const list = el('nav'); list.setAttribute('aria-label','当前模块的业务视图');
  for (const choice of rootViews.children) {
    const key = choice.dataset.key;
    const a = el('a','',choice.textContent);
    a.href='#' + route + '?' + new URLSearchParams({tab:key});
    if (choice.getAttribute('aria-selected')==='true') a.setAttribute('aria-current','page');
    a.onclick = event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault(); pop.open=false; go(route,key);
    };
    list.append(a);
  }
  pop.addEventListener('focusout',event=>{ if (!pop.contains(event.relatedTarget)) pop.open=false; });
  pop.addEventListener('keydown',event=>{ if(event.key==='Escape'){pop.open=false;summary.focus();} });
  pop.append(summary,list);
  return pop;
}
function masthead(rootViews) {
  const bar = el('header', 'masthead');
  const menu = button(
    '',
    () => {
      if (!smallScreen()) { compact = !compact; applyDeskSize(); return; }
      const open = root.classList.toggle('menu-open');
      menu.setAttribute('aria-expanded',String(open));
      if (open) root.querySelector('.sidebar a')?.focus();
    },
    'icon',
    'menu',
  );
  menu.classList.add('menu-trigger');
  menu.setAttribute('aria-label', '业务导航');
  menu.setAttribute('aria-controls', 'sidenav');
  menu.setAttribute('aria-expanded', 'false');
  const crumb = el('nav','desk-crumbs');
  crumb.setAttribute('aria-label','当前位置');
  const home = el('a','','首页'); home.href = '#' + landing(); crumb.append(home);
  const page = desk.pages.get(desk.active);
  const path = deskPath(deskMenu,route,page?.tab,page?.view);
  const parent = page?.render && path.label !== page.title ? path.label : '';
  for (const value of [path.group, parent, page?.title].filter(item => item && item !== '首页'))
    crumb.append(el('i','','/'),el('span','',value));
  const controls = el('div', 'global-tools');
  if (state.user.kind !== 'family') {
    const search = el('button', 'top-search');
    search.type = 'button';
    search.setAttribute('aria-label', '全局搜索');
    search.append(
      icon('search', 17),
      el('span', '', '搜索'),
      el('kbd', '', /Mac/.test(navigator.platform) ? '⌘ K' : 'Ctrl K'),
    );
    search.addEventListener('click', searchDialog);
    const bell = button('', notices, 'icon', 'bell');
    bell.setAttribute('aria-label', '待处理事项');
    if (
      hasNewNotice(context()) ||
      myTrialFollowups().length ||
      unresolvedTrials().length ||
      pendingRenewals() ||
      pendingPermissionRequests(context()) ||
      state.groupActivityDue > 0 ||
      (available('billing') && todayBillingNotices() > 0) ||
      (available('leads') && pendingLeadCalls(state)) ||
      state.supplyOrders?.some(row => row.assigneeId === state.user.id && row.status === '待执行') ||
      (available('inbox') && state.roundsNoticeCount > 0) ||
      (available('care') && myPendingHandovers().length) ||
      (state.gatewayAlerts || []).some((r) => r.status === '待复核') ||
      (state.voiceQueue || []).length ||
      [...state.plans, ...state.vitals, ...state.medications].some((r) => r.status === '待复核') ||
      state.inventory.some((i) => i.quantity < i.minimum)
    )
      bell.classList.add('has-notice');
    const fullscreen = button('', async () => {
      try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
      catch { toast('当前浏览器未开放全屏显示'); }
    }, 'icon','fullscreen');
    fullscreen.setAttribute('aria-label','切换全屏'); fullscreen.title = '切换全屏';
    const size = button('', () => {largeText = !largeText; applyDeskSize(); size.setAttribute('aria-pressed',String(largeText));}, 'icon','font');
    size.setAttribute('aria-label','放大字号'); size.title = '放大字号'; size.setAttribute('aria-pressed',String(largeText));
    controls.append(search, fullscreen, size, bell);
  }
  controls.prepend(chatLauncher(() => toggleChat(context)));
  const account = el('button', 'account-trigger');
  account.type = 'button';
  account.setAttribute('aria-label', '账号与退出登录');
  account.append(
    el('span', 'header-avatar', state.user.displayName.slice(0, 1)),
    el('span', 'account-name', staffLabel(context(), state.user)),
    icon('down', 12),
  );
  account.addEventListener('click', accountMenu);
  controls.append(account);
  bar.append(menu, crumb);
  const switcher = viewSwitcher(rootViews);
  if (switcher) bar.append(switcher);
  bar.append(controls);
  return bar;
}

let editing = false;
root.addEventListener('input', (e) => {
  if (e.target.closest('.access-settings')) editing = true;
});

function render() {
  editing = false;
  if (!state) return;
  route = getRoute();
  if (!available(route)) {
    route = landing();
    history.replaceState(null, '', '#' + route);
  }
  deskMenu = menuFor(context());
  const home = landing();
  const homeKey = '#' + home;
  desk.ensure({key:homeKey,route:home,title:home === 'overview' ? '首页' : routes.get(home).label,pinned:true});
  restoreDeskPages();
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const tab = params.get('tab') || undefined, view = params.get('view') || undefined;
  let key = location.hash || homeKey;
  if (params.has('resident') || params.has('bedcard')) key = '#' + route;
  if (params.has('work') && !desk.pages.has(key)) {
    const restored = restoreWorkspaceDocument(route,params.get('work'));
    if (restored) desk.ensure({key,route,...restored});
    else {
      key = '#' + route;
      toast('此工作页已关闭或当前账号无权访问');
      history.replaceState(null,'',key);
    }
  }
  const path = deskPath(deskMenu,route,tab,view);
  const page = desk.ensure({key,route,tab,view,title:path.label || routes.get(route).label});
  const previous = desk.pages.get(desk.active);
  const switching = page !== previous;
  if (previous && switching) {
    previous.scroll = window.scrollY;
    // Detached views can discard late responses. Rebuild them when they are opened again.
    if (previous.pendingReads) previous.node = null;
  }
  sidebarScroll = root.querySelector('.nav-list')?.scrollTop ?? sidebarScroll;
  desk.active = key;
  if (page.tab) selectTab(route,page.tab);
  else if (!page.render && !page.node) selectTab(route,undefined);
  root.classList.add('desk-shell');
  closeMenu();
  const wrap = el('div', 'app-main');
  let main = page.node;
  if (!main || !switching) {
    main = el('main','content'); main.id = 'content'; main.tabIndex = -1;
    main.dataset.route = route;
    if (page.view === 'cockpit' && !page.render) main.classList.add('desk-cockpit');
    if (page.render) main.append(page.render(context()));
    else if (route === 'overview') main.append(page.view === 'cockpit' ? dashboard(context()) : officeHome(context()));
    else main.append(renderFeature(route, context()));
    page.node = main;
    if (tab && !page.render) {
      const choice = main.querySelector('.fx-tabs > [aria-selected="true"]');
      if (choice?.dataset.key === tab && (!path.label || !deskMenu.some(g => g.children?.some(([r,,k]) => r === route && k === tab))))
        page.title = choice.textContent;
    }
  }
  document.title = page.title + ' · ' + state.uiSettings.brandName;
  wrap.append(tabStrip(),main);
  const shade = el('button','menu-backdrop'); shade.type = 'button';
  shade.setAttribute('aria-label','收起业务导航'); shade.onclick = closeMenu;
  const rootViews = page.render ? null : main.querySelector('.fx-tabs[data-route="' + CSS.escape(route) + '"]');
  if (rootViews) rootViews.hidden = true;
  const assistant = el('button', 'desk-assistant-float');
  assistant.type = 'button';
  assistant.title = '询问健康助理';
  assistant.setAttribute('aria-label', assistant.title);
  assistant.setAttribute('aria-haspopup', 'dialog');
  assistant.setAttribute('aria-controls', 'assistant-chat');
  assistant.append(icon('spark', 23));
  assistant.onclick = () => openChat(context);
  root.replaceChildren(sidebar(),masthead(rootViews),shade,wrap,assistant);
  root.querySelector('.nav-list').scrollTop = sidebarScroll;
  applyDeskSize();
  if (switching) window.scrollTo(0,page.scroll);
  saveDesk();
  openLinkedResident();
  openLinkedBedCard(context());
}

function restoreWorkspaceDocument(route,id) {
  if (!available(route)) return null;
  if (route === 'overview' && id === 'operations-detail') return {id, view:'cockpit', title:'日常运营明细', render:operationalOverview};
  if (route === 'assessments') return restoreCarePlanTab(context(),id);
  if (['dossier','residents','billing','longCare'].includes(route)) return residentWorkspaceTab(context(),id);
  return null;
}

function openLinkedResident() {
  const destination = location.hash.slice(1).split('?')[0];
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const id = params.get('resident');
  if (!id || !['residents', 'dossier', 'billing', 'longCare', 'family'].includes(destination) || !available(destination)) return;
  const row = state.residents.find(person => person.id === id);
  if (!row) {
    history.replaceState(null, '', '#' + destination);
    toast('该长辈档案未开放或已失效');
    return;
  }
  if (destination === 'family' || document.querySelector('dialog[open][data-linked-resident]')) return;
  const eventId = params.get('lifeEvent');
  const day = params.get('lifeDay');
  const lifeEvent = /^[a-f0-9]{32}$/.test(eventId || '') && /^\d{4}-\d{2}-\d{2}$/.test(day || '')
    ? {eventId, day} : undefined;
  const modal = destination === 'residents'
    ? profile(context(), row, lifeEvent)
    : openDossier(context(), row, lifeEvent, destination === 'dossier' ? 'medical' : undefined);
  if (!(modal instanceof HTMLDialogElement)) { residentOverlay = null; return; }
  modal.dataset.linkedResident = id;
  const target = location.hash;
  modal.addEventListener('close', () => {
    if (!state || location.hash !== target || document.querySelector('dialog[open][data-linked-resident]')) return;
    if (history.state?.residentFrom !== undefined) history.back();
    else history.replaceState(null, '', target.split('?')[0]);
  }, { once: true });
}

function failed(error) {
  const section = el('section', 'loading');
  section.append(el('p', '', error.message), button('重新载入', load, 'primary'));
  root.replaceChildren(section);
}

function openResetFromLocation() {
  const reset = /^#reset=([A-Za-z0-9_-]{43})$/.exec(location.hash);
  if (!reset) return false;
  history.replaceState(null, '', '/?workspace=1');
  signedOut();
  redeemPasswordReset(reset[1], (username) => {
    root.querySelector('input[name=username]').value = username;
  });
  return true;
}

async function load() {
  try {
    branding = await get('/api/branding');
    if (openResetFromLocation()) return;
    const publicLanding = location.pathname === '/' && !location.hash && !location.search;
    if (await readState({ publicLanding })) render();
  } catch (error) {
    failed(error);
  }
}

function rememberResidentOrigin(hash) {
  residentOverlay = { hash, main: document.getElementById('content'), dialogs: new Set(document.querySelectorAll('dialog[open]')) };
}

document.addEventListener('click', (event) => {
  const link = event.target.closest?.('a.resident-profile-link');
  if (!link || !state || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
      event.shiftKey || event.altKey || (link.target && link.target !== '_self') || residentOverlay ||
      link.hash.startsWith('#family?') || location.hash.includes('?resident=')) return;
  event.preventDefault();
  rememberResidentOrigin(location.hash);
  history.pushState({ residentFrom: location.hash }, '', link.href);
  openLinkedResident();
});

root.addEventListener('desk:view',event => {
  const target = event.detail;
  if (!state || target.route !== route || !available(target.route) || event.target.closest('dialog')) return;
  event.preventDefault();
  go(target.route,target.key);
});

window.addEventListener('hashchange', (event) => {
  if (openResetFromLocation()) return;
  if (state) {
    const origin = residentOverlay;
    residentOverlay = null;
    if (origin?.hash === location.hash && origin.main?.isConnected) {
      document.querySelectorAll('dialog[open]').forEach(d => { if (!origin.dialogs.has(d)) d.close(); });
      return;
    }
    if (history.state?.residentFrom === new URL(event.oldURL).hash) {
      rememberResidentOrigin(history.state.residentFrom);
      openLinkedResident();
      return;
    }
    document.querySelectorAll('dialog[open]').forEach((d) => d.close());
    render();
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

function sameRefreshVersion(check, version) {
  return check.revision === version.revision && check.userId === version.userId &&
    check.actorStamp === version.actorStamp && check.today === version.today &&
    check.groupActivityDue === version.groupActivityDue;
}

function dialogRefreshTarget(dialog) {
  const data = dialog.dataset;
  return [data.proposalId, data.agentRunId, data.handoverId, data.pendingHandoverId,
    data.managedAccountId, data.roundsResidentId, data.linkedResident].join('\0');
}

function deferRefresh(snapshot, dialogs) {
  deferredRefresh = {
    revision: snapshot.revision,
    userId: snapshot.data.user.id,
    actorStamp: snapshot.actorStamp,
    today: snapshot.today,
    groupActivityDue: snapshot.data.groupActivityDue,
    route: location.hash,
    dialogCount: dialogs.length,
    dialogs: new WeakMap(dialogs.map(dialog => [dialog, dialogRefreshTarget(dialog)])),
  };
}

async function refresh() {
  if (!state || saving || refreshing || document.hidden) return;
  refreshing = true;
  const current = epoch,
    version = revision;
  try {
    const check = await get('/api/version');
    if (current !== epoch || saving || version !== revision) return;
    if (sameRefreshVersion(check, {
      revision, userId: state.user.id, actorStamp: state.actorStamp,
      today: state.today, groupActivityDue: state.groupActivityDue,
    })) return;
    if (check.actorStamp && deferredRefresh && deferredRefresh.route === location.hash &&
        sameRefreshVersion(check, deferredRefresh)) {
      const dialogs = [...document.querySelectorAll('dialog[open]')];
      if (dialogs.length === deferredRefresh.dialogCount &&
          (dialogs.length || editing) &&
          dialogs.every(dialog => deferredRefresh.dialogs.get(dialog) === dialogRefreshTarget(dialog))) return;
    }
    const snapshot = await get('/api/state');
    if (current !== epoch || saving || version !== revision) return;
    const inbox = snapshot.data.familyRoundInbox;
    const lostFamilyAccess = state.familyRoundInbox?.messages.some(
      (message) => !inbox?.messages.some((m) => m.id === message.id),
    );
    const visibleResidents = new Map(snapshot.data.residents.map(person => [person.id, person]));
    const movedResident = [...document.querySelectorAll('[data-rounds-resident-id], [data-linked-resident]')].some((el) => {
      const id = el.dataset.roundsResidentId || el.dataset.linkedResident;
      const before = state.residents.find((r) => r.id === id);
      const after = visibleResidents.get(id);
      return before && (!after || before.bedId !== after.bedId || before.status !== after.status);
    });
    const changedUser =
      visibilityChanged(snapshot) || movedResident ||
      lostFamilyAccess ||
      JSON.stringify(state.user) !== JSON.stringify(snapshot.data.user);
    const dialogs = [...document.querySelectorAll('dialog[open]')];
    if (editing && !changedUser && !dialogs.length) {
      deferRefresh(snapshot, dialogs);
      return;
    }
    if (dialogs.length && !changedUser) {
      const obsolete = dialogs.some(
        (d) =>
          d.dataset.proposalId &&
          !(snapshot.data.voiceQueue || []).some((r) => r.id === d.dataset.proposalId),
      );
      const settled = dialogs.some(
        (d) =>
          d.dataset.agentRunId &&
          !(snapshot.data.agentRuns || []).some(
            (r) => r.id === d.dataset.agentRunId && r.status === 'awaiting_approval',
          ),
      );
      const received = dialogs.some(
        (d) =>
          (d.dataset.handoverId &&
            !myPendingHandovers(snapshot.data).some((r) => r.id === d.dataset.handoverId)) ||
          (d.dataset.pendingHandoverId &&
            !snapshot.data.handovers.some(
              (r) => r.id === d.dataset.pendingHandoverId && r.status === '待签收',
            )),
      );
      const lostTarget = dialogs.some(
        (d) =>
          d.dataset.managedAccountId &&
          !snapshot.data.accounts?.some((a) => a.id === d.dataset.managedAccountId),
      );
      if (!obsolete && !settled && !received && !lostTarget) {
        deferRefresh(snapshot, dialogs);
        return;
      }
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
document.addEventListener('close', event => {
  if (deferredRefresh?.dialogs.has(event.target)) refresh();
}, true);
setInterval(refresh, 4000);
load();
