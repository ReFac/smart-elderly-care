import { auditActorLabel, residentLabel, residentAnchor, staffLabel } from './people-labels.js';
import { btn, node, page } from './shared.js';
import { openDossier } from './dossier.js';
import { goToRoom } from './rooms.js';
import { openBackupPoint } from './backups.js';
import { actionTitle, fieldLabel } from '../lib/change-review.js';

const collections = {
  tasks: '照护工单',
  residents: '长辈',
  beds: '床位',
  inquiries: '接待记录',
  assessments: '能力评估',
  plans: '照护计划',
  qualityChecks: '服务抽检',
  handovers: '交班',
  medications: '医嘱',
  resident_medication_reports: '体检用药自报及更正',
  medication_round_receipts: '床旁服药核对凭证',
  followups: '随访',
  referrals: '转介',
  vitals: '体征',
  inventory: '物资',
  stockMoves: '库存流水',
  shifts: '排班',
  bills: '账单',
  suggestions: '专项建议',
  accounts: '账号',
  facility_rooms: '房间',
  facility_campuses: '分院',
  facility_buildings: '楼栋',
  audit: '操作记录',
  dossier_documents: '医疗文书',
  workspace: '机构数据',
  ui_settings: '工作台设置',
  care_timeline_settings: '时间线设置',
};

const displayTime = (at) => String(at || '').slice(11, 19);
const displayDate = (at) => String(at || '').slice(0, 10);
const recordTitle = (row) => row.summary || actionTitle(row.action);
function renderValue(value) {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value !== 'object') return String(value) || '（空）';
  if (Array.isArray(value)) return value.map(renderValue).join('、') || '无';
  return (
    Object.entries(value)
      .map(([k, v]) => fieldLabel(k) + ' ' + renderValue(v))
      .join('\n') || '无'
  );
}

function displayField(ctx, collection, key, value, embedded) {
  const list = {
    campusId: ctx.state.campusOptions,
    residentId: ctx.state.residents,
    bedId: ctx.state.beds,
    taskId: ctx.state.tasks,
    assigneeId: ctx.state.accounts,
  }[key];
  const match = list?.find((row) => row.id === value);
  if (match && key === 'residentId')
    return [fieldLabel(key), embedded ? residentLabel(ctx, match) : residentAnchor(ctx, match)];
  if (match && key === 'assigneeId') return [fieldLabel(key), staffLabel(ctx, match)];
  const display =
    match?.name || match?.label || match?.title || match?.displayName || renderValue(value);
  let label = fieldLabel(key);
  if (key === 'name' && ['inquiries', 'residents'].includes(collection)) label = '长辈姓名';
  if (key === 'note' && collection === 'inquiries') label = '入住需求';
  const text = node('span', '', display);
  if (match) text.title = String(value);
  return [label, text];
}

function comparison(ctx, change, embedded) {
  const complete =
    change.kind === 'add' ? change.after : change.kind === 'remove' ? change.before : null;
  if (!change.field && complete && typeof complete === 'object' && !Array.isArray(complete)) {
    const list = node('dl', 'history-record-values');
    for (const [key, value] of Object.entries(complete)) {
      if (key === 'id' && value === change.entityId) continue;
      const [name, text] = displayField(ctx, change.collection, key, value, embedded);
      list.append(node('div', '', [node('dt', '', name), node('dd', '', text)]));
    }
    return node('section', 'history-record history-record-' + change.kind, [
      node('h4', '', change.kind === 'add' ? '新增内容' : '移除的内容'),
      list,
    ]);
  }
  const item = node('div', 'history-field');
  const label = change.field ? change.field.split('/').map(fieldLabel).join(' / ') : '整条记录';
  item.append(node('strong', 'history-field-label', label));
  for (const [title, key] of [
    ['改动前', 'before'],
    ['改动后', 'after'],
  ]) {
    const value = node('div', 'history-value history-' + key, [
      node('span', 'history-side-label', title),
      displayField(ctx, change.collection, change.field?.split('/').at(-1), change[key], embedded)[1],
    ]);
    item.append(value);
  }
  return item;
}

function inspector(ctx, change, embedded, undo) {
  const title = node('h2', '', recordTitle(change));
  const head = node('header', 'history-inspector-head', [
    node('div', 'history-version', [ctx.ui.icon('clock', 15), '版本 ' + change.revision]),
    title,
    node(
      'p',
      'fx-muted',
      [
        auditActorLabel(ctx, change),
        displayDate(change.at) + ' ' + displayTime(change.at),
        change.room,
      ]
        .filter(Boolean)
        .join(' · '),
    ),
  ]);
  const content = node('article', 'history-inspector', [head]);
  if (change.agentReview) {
    const { domain, status, text, checks } = change.agentReview;
    const detail = status === 'reviewed' ? node('p', '', 'AI 复核意见：' + text) :
      status === 'pending' ? node('small', 'fx-muted', '等待云端复核') : null;
    content.append(node('section', 'fx-section', [
      node('h3', '', '提交校验 · ' + domain),
      node('ul', '', checks.map(check => node('li', '', check))),
      detail,
    ]));
  }
  if (change.comment) content.append(node('blockquote', 'history-comment', change.comment));
  if (change.undoOf || change.undoneBy)
    content.append(
      node(
        'p',
        'history-relation',
        change.undoOf ? '本次撤销了版本 ' + change.undoOf : '已由版本 ' + change.undoneBy + ' 撤销',
      ),
    );
  const entries = change.changes || [];
  if (entries.length) {
    const groups = new Map();
    for (const c of entries) {
      const key = c.collection + ' / ' + (c.entityId || '');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(c);
    }
    for (const group of groups.values()) {
      const first = group[0];
      const block = node('details', 'history-object');
      block.open = groups.size === 1 || first === entries[0];
      block.append(
        node('summary', '', [
          node('strong', '', collections[first.collection] || first.collection),
          node('small', '', first.entityId || ''),
          node('span', 'fx-count', group.length + ' 项'),
        ]),
        ...group.map((c) => comparison(ctx, c, embedded)),
      );
      content.append(block);
    }
  } else
    content.append(
      node(
        'p',
        'history-note',
        change.source === 'legacy'
          ? '此操作早于字段追踪启用日期，保留了当时的操作摘要。'
          : '此操作有执行记录，当前可见范围内没有字段差异。',
      ),
    );
  const footer = node('div', 'history-inspector-actions');
  if (!embedded) {
    const person = ctx.state.residents?.find((row) => row.id === change.residentId);
    if (person && ctx.available('dossier'))
      footer.append(btn(ctx, '打开长辈档案', () => openDossier(ctx, person)));
    if (change.roomId && ctx.available('rooms'))
      footer.append(btn(ctx, '定位到房间', () => goToRoom(ctx, change.roomId)));
    if (change.rollbackPointId && ctx.available('settings'))
      footer.append(
        btn(ctx, '查看恢复前保护点', () => {
          ctx.go('settings', 'backups');
          openBackupPoint(ctx, change.rollbackPointId);
        }),
      );
  }
  if (change.undoable)
    footer.append(btn(ctx, '撤销这次改动', () => undo(change), 'secondary', 'undo'));
  else if (change.undoReason) footer.append(node('small', 'fx-muted', change.undoReason));
  content.append(footer);
  return content;
}

function optionPicker(label, choices, current) {
  const control = node('select', 'fx-input');
  control.setAttribute('aria-label', label);
  for (const [key, text] of choices) control.add(new Option(text, key));
  control.value = current || '';
  return control;
}

export function recentChanges(ctx, { residentId, onUndo } = {}) {
  const embedded = Boolean(residentId);
  const scope = embedded ? { residentId } : ctx.historyScope;
  const timeline = node('div', 'history-list');
  const pane = node('div', 'history-pane');
  const more = btn(ctx, '加载更早改动', () => load(true));
  const count = node('span', 'fx-count');
  const header = node('header', 'history-list-header', [node('h2', '', '变更记录'), count]);
  const listColumn = node('section', 'history-list-column', [header, timeline, more]);
  const split = node('div', 'history-layout', [listColumn, pane]);
  let rows = [],
    cursor = null,
    sequence = 0,
    detailSeq = 0,
    roomSearchSeq = 0;
  const actors = new Map([[ctx.state.user.id, staffLabel(ctx, ctx.state.user)]]);
  for (const person of ctx.state.accounts || []) actors.set(person.id, staffLabel(ctx, person));
  const byUser = optionPicker('操作人', [['', '全部操作人'], ...actors], scope.actorId);
  const byPerson = embedded ? null : optionPicker(
    '长辈',
    [['', '全部长辈'], ...(ctx.state.residents || []).map((r) => [r.id, residentLabel(ctx, r)])],
    scope.residentId,
  );
  const roomInput = node('input', 'fx-input');
  roomInput.type = 'search';
  roomInput.placeholder = '输入房号或长辈姓名';
  roomInput.setAttribute('aria-label', '查找房间');
  const roomLabel = node('span', 'history-scope');
  const matches = node('div', 'history-room-results');
  const dayInput = node('input', 'fx-input');
  dayInput.type = 'date';
  dayInput.max = ctx.state.today;
  dayInput.value = scope.day || '';
  dayInput.setAttribute('aria-label', '变更日期');
  const search = node('input', 'fx-input');
  search.type = 'search';
  search.maxLength = 120;
  search.value = scope.q || '';
  search.placeholder = '搜索摘要、说明或版本号';
  search.setAttribute('aria-label', search.placeholder);
  const searchForm = node('form', 'history-keyword', [search]);
  const submit = node('button', 'btn btn-secondary', '搜索');
  submit.type = 'submit';
  searchForm.append(submit);
  searchForm.onsubmit = (e) => {
    e.preventDefault();
    scope.q = search.value.trim();
    scope.revision = null;
    load(false);
  };
  search.addEventListener('search', () => {
    if (!search.value && scope.q) {
      scope.q = '';
      scope.revision = null;
      load(false);
    }
  });
  dayInput.onchange = () => {
    scope.day = dayInput.value;
    scope.revision = null;
    load(false);
  };
  const filters = node('details', 'history-filters');
  const clear = btn(ctx, '清除筛选', () => {
    Object.assign(scope, {
      actorId: '',
      residentId: residentId || '',
      roomId: '',
      roomLabel: '',
      day: '',
      q: '',
      revision: null,
    });
    byUser.value = roomInput.value = dayInput.value = search.value = '';
    if (byPerson) byPerson.value = '';
    matches.replaceChildren();
    load(false);
  });
  const wrap = (name, control) => node('label', 'field', [node('span', '', name), control]);
  filters.append(
    node('summary', '', [ctx.ui.icon('search', 16), '筛选记录']),
    node('div', 'history-filter-fields', [
      wrap('操作人', byUser),
      byPerson ? wrap('长辈', byPerson) : null,
      wrap('变更日期', dayInput),
      ...(ctx.available('rooms')
        ? [node('div', 'history-room-search', [wrap('房间', roomInput), matches])]
        : []),
      clear,
    ]),
  );
  roomInput.oninput = async () => {
    const num = ++roomSearchSeq,
      term = roomInput.value.trim();
    matches.replaceChildren();
    if (!term) return;
    try {
      const res = await ctx.get(
        '/api/facility/search?' + new URLSearchParams({ q: term, limit: '12' }),
      );
      if (num !== roomSearchSeq || !filters.isConnected) return;
      for (const r of res.results) {
        const name = [r.campusName, r.buildingName, r.floorLabel, r.number + ' 房']
          .filter(Boolean)
          .join(' · ');
        matches.append(
          btn(ctx, name, () => {
            scope.roomId = r.roomId;
            scope.roomLabel = name;
            scope.revision = null;
            matches.replaceChildren();
            roomInput.value = '';
            load(false);
          }),
        );
      }
      if (!res.results.length) matches.textContent = '没有匹配房间';
    } catch (e) {
      if (num === roomSearchSeq) matches.textContent = e.message;
    }
  };
  byUser.onchange = () => {
    scope.actorId = byUser.value;
    scope.revision = null;
    load(false);
  };
  if (byPerson)
    byPerson.onchange = () => {
      scope.residentId = byPerson.value;
      scope.revision = null;
      load(false);
    };
  const my = btn(ctx, '我的改动', () => {
    scope.actorId = scope.actorId === ctx.state.user.id ? '' : ctx.state.user.id;
    byUser.value = scope.actorId;
    scope.revision = null;
    load(false);
  });
  function syncFilters() {
    my.setAttribute('aria-pressed', String(scope.actorId === ctx.state.user.id));
    const labels = [
      scope.q,
      scope.day,
      scope.actorId && (actors.get(scope.actorId) || '指定操作人'),
      !embedded && scope.residentId && residentLabel(ctx, scope.residentId),
      scope.roomId && (scope.roomLabel || '指定房间'),
    ].filter(Boolean);
    roomLabel.textContent = labels.join(' / ');
    clear.disabled = !labels.length;
  }
  function drawList() {
    timeline.replaceChildren();
    let lastDate = '';
    for (const row of rows) {
      const day = displayDate(row.at);
      if (day !== lastDate) {
        timeline.append(node('h3', 'history-day', day));
        lastDate = day;
      }
      const item = node('button', 'history-item');
      item.type = 'button';
      item.setAttribute('aria-current', String(scope.revision === row.revision));
      item.append(
        node('div', 'history-item-meta', [
          node('time', '', displayTime(row.at)),
          node('span', '', 'v' + row.revision),
        ]),
        node('strong', '', recordTitle(row)),
        node('small', '', [auditActorLabel(ctx, row), row.room].filter(Boolean).join(' · ')),
      );
      item.onclick = () => select(row.revision);
      timeline.append(item);
    }
    if (!rows.length) timeline.append(node('p', 'history-note', '没有符合条件的改动。'));
    count.textContent = rows.length + (cursor ? ' 条以上' : ' 条');
    more.hidden = !cursor;
  }
  async function select(id) {
    const focused = timeline.contains(document.activeElement);
    scope.revision = id;
    drawList();
    if (focused) timeline.querySelector('.history-item[aria-current=true]')?.focus({ preventScroll: true });
    const seq = ++detailSeq;
    pane.replaceChildren(node('p', 'history-note', '正在读取变更详情…'));
    try {
      const response = await ctx.get('/api/history/' + id);
      if (seq === detailSeq && pane.isConnected)
        pane.replaceChildren(inspector(ctx.current?.() || ctx, response, embedded, undo));
    } catch (e) {
      if (seq === detailSeq) pane.replaceChildren(node('p', 'history-note', e.message));
    }
  }
  async function undo(change) {
    const saved = await ctx.undoRevision(change, embedded ? split.closest('dialog') : undefined);
    if (!embedded || !split.isConnected) return;
    if (saved === false) return load(false);
    if (!saved) return;
    onUndo?.();
    scope.revision = saved.revision;
    await load(false);
  }
  async function load(append) {
    const seq = ++sequence,
      desired = scope.revision;
    ++detailSeq;
    syncFilters();
    more.disabled = true;
    if (!append) {
      rows = [];
      cursor = null;
      timeline.replaceChildren(node('p', 'history-note', '正在读取记录…'));
      pane.replaceChildren();
    }
    const q = new URLSearchParams({ limit: '30' });
    for (const k of ['residentId', 'actorId', 'roomId', 'q', 'day'])
      if (scope[k]) q.set(k, scope[k]);
    if (append && cursor) q.set('before', String(cursor));
    try {
      const response = await ctx.get('/api/history?' + q);
      if (seq !== sequence || !split.isConnected) return;
      rows.push(...response.rows);
      cursor = response.nextBefore;
      const chosen = rows.some((r) => r.revision === desired) ? desired : rows[0]?.revision;
      if (chosen) await select(chosen);
      else {
        scope.revision = null;
        drawList();
        pane.replaceChildren(node('p', 'history-note', '选择一条记录即可查看改动前后的内容。'));
      }
    } catch (e) {
      if (seq === sequence) timeline.replaceChildren(node('p', 'history-note', e.message));
    } finally {
      if (seq === sequence) more.disabled = false;
    }
  }
  const toolbar = node('div', 'history-toolbar', [
    node('div', 'history-tools', [my, filters, roomLabel]),
    searchForm,
  ]);
  const screen = embedded ? node('div', 'history-embedded', [
    node('header', 'history-embedded-heading', [
      node('h3', '', '最近改动'),
      node('p', 'fx-muted', '当前长辈 · 最近 60 天'),
    ]),
    toolbar,
    split,
  ]) : page(
    ctx,
    '最近改动',
    '查看最近 60 天的变更说明、经办人和修改前后的内容。',
    null,
    toolbar,
    split,
  );
  load(false);
  return screen;
}
