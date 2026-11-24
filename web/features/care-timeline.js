import { btn, canAct, choose, facts, node, today } from './shared.js';

function clock(stamp) {
  return stamp ? stamp.slice(11, 19) : '';
}

function entryCard(ctx, row, openProof) {
  const heading = node('div', 'ct-receipt-head', [
    node('strong', '', row.title),
    node('span', '', clock(row.at) || '完成时刻未登记'),
  ]);
  const receipt = node('article', 'ct-receipt', [
    heading,
    facts([
      ['长者', row.resident],
      ['执行人', row.operator || '未登记'],
      ['执行记录', row.note || '未填'],
      ['执行时房间', row.roomLabel || '未登记'],
      ['原始工单', row.taskId],
      ['计划执行', row.planned],
      ['床旁核验', row.scannedBed || '未登记'],
    ]),
  ]);
  if (openProof) receipt.append(btn(ctx, '工单凭证与抽检', () => openProof(row.taskId)));
  return receipt;
}

function groupCard(ctx, group, openProof, focusedIds) {
  const entries = group.entries;
  const labels = (idKey, nameKey, fallback) => {
    const people = new Map(entries.map((e) => [e[idKey] || e[nameKey], e[nameKey] || fallback]));
    const counts = new Map();
    for (const name of people.values()) counts.set(name, (counts.get(name) || 0) + 1);
    return [...people]
      .map(([id, name]) => (counts.get(name) > 1 ? name + '（' + id + '）' : name))
      .join('、');
  };
  const residents = labels('residentId', 'resident', '长者未登记');
  const staff = labels('operatorId', 'operator', '执行人未登记');
  const start = clock(group.start),
    end = clock(group.end);
  const when = start ? (start === end ? start : start + ' – ' + end) : '时刻未登记';
  const name = entries.length === 1 ? entries[0].title : group.title;
  const item = node('details', 'ct-group');
  const head = node('summary', 'ct-group-head', [
    node('div', 'ct-when', [
      node('strong', '', when),
      node('small', '', group.day || '完成日期未登记'),
    ]),
    node('div', 'ct-event', [
      node('strong', '', name),
      node('span', '', staff + ' 为 ' + residents + ' 提供服务'),
      group.roomLabel ? node('small', '', group.roomLabel) : null,
    ]),
    node('span', 'ct-count', entries.length + ' 笔'),
  ]);
  item.append(head);
  item.addEventListener('toggle', () => {
    if (item.open && item.children.length === 1)
      item.append(
        node(
          'div',
          'ct-receipts',
          entries.map((row) => entryCard(ctx, row, openProof))
        )
      );
  });
  if (entries.some((row) => focusedIds.has(row.taskId))) {
    item.open = true;
    item.classList.add('change-focus');
  }
  return item;
}

function configure(ctx, scope, id, result, reload) {
  const current = result.settings;
  const enabled = node('input');
  enabled.type = 'checkbox';
  enabled.checked = current.mergeEnabled;
  const interval = node('select', 'fx-input');
  for (const minutes of [10, 15, 30, 60])
    interval.add(new Option(minutes + ' 分钟', String(minutes)));
  interval.value = String(current.windowMinutes);
  interval.disabled = !enabled.checked;
  enabled.onchange = () => {
    interval.disabled = !enabled.checked;
  };
  const save = btn(
    ctx,
    '保存显示设置',
    async () => {
      const ok = await ctx.command('care.timelineSettings', {
        [scope + 'Id']: id,
        mergeEnabled: enabled.checked,
        windowMinutes: Number(interval.value),
      });
      if (ok) reload();
    },
    'primary'
  );
  ctx.detail(
    '照护时间线设置',
    node('div', 'fx-profile', [
      node('strong', '', result.label),
      node('label', 'ct-switch', [enabled, '合并同一房间内的饮水、用餐记录']),
      node('label', 'field', [node('span', '', '首笔至末笔的最大间隔'), interval]),
      node('p', 'fx-muted', '每笔工单保留执行人、时间和凭证，可展开查看。'),
      save,
    ])
  );
}

const focusedContexts = new WeakSet();

export function careTimeline(ctx, scope, id = '', openProof) {
  const focusedIds = new Set(focusedContexts.has(ctx) ? [] : ctx.focusIds || []);
  const root = node('section', 'fx-panel ct-panel');
  let ticket = 0,
    lastResult,
    offset = 0,
    version = '',
    timer;
  const title = scope === 'work' ? '已完成服务' : '照护时间线';
  const actions = choose();
  const search = node('input', 'fx-input');
  search.type = 'search';
  search.placeholder = '搜索长者、执行人或项目';
  search.maxLength = 64;
  search.setAttribute('aria-label', search.placeholder);
  const day = node('input', 'fx-input');
  day.type = 'date';
  day.max = today(ctx);
  day.setAttribute('aria-label', '按执行日期筛选');
  const dates = node('div', 'ct-dates', [
    day,
    btn(ctx, '今天', () => {
      day.value = today(ctx);
      reset();
    }),
    btn(ctx, '近 60 天', () => {
      day.value = '';
      reset();
    }),
  ]);
  const events = node('div', 'ct-groups');
  const caption = node('p', 'fx-muted');
  caption.setAttribute('role', 'status');
  const pager = node('div', 'ct-pager');
  root.append(
    node('header', 'fx-toolbar', [node('h2', '', title), actions]),
    node('div', 'ct-filter', [search, dates]),
    caption,
    events,
    pager
  );
  if (scope !== 'work' && canAct(ctx, 'care.timelineSettings')) {
    const settings = btn(
      ctx,
      '显示设置',
      () =>
        lastResult &&
        configure(ctx, scope, id, lastResult, () => {
          if (root.isConnected && !root.closest('dialog:not([open])')) reset();
          else ctx.detail(lastResult.label + ' · 照护记录', careTimeline(ctx, scope, id));
        })
    );
    actions.append(settings);
  }
  function reset() {
    offset = 0;
    version = '';
    load();
  }
  async function load() {
    const generation = ++ticket;
    const params = new URLSearchParams({ offset: String(offset) });
    if (day.value) params.set('day', day.value);
    if (search.value.trim()) params.set('q', search.value.trim());
    if (version) params.set('revision', version);
    const path =
      '/api/care-timeline/' + (scope === 'work' ? 'work' : scope + '/' + encodeURIComponent(id));
    caption.textContent = '正在读取照护记录…';
    try {
      const result = await ctx.get(path + '?' + params);
      if (generation !== ticket || !root.isConnected) return;
      lastResult = result;
      version = String(result.revision);
      caption.textContent =
        (day.value || '近 60 天') +
        ' · ' +
        result.totalEntries +
        ' 笔原始工单，' +
        result.totalGroups +
        ' 条时间线记录';
      events.replaceChildren(...result.groups.map((group) => groupCard(ctx, group, openProof, focusedIds)));
      const focus = events.querySelector('.change-focus');
      if (focus) focusedContexts.add(ctx);
      focusedIds.clear();
      if (focus && offset === 0)
        requestAnimationFrame(() => focus.scrollIntoView({ block: 'nearest' }));
      if (!result.groups.length)
        events.append(node('p', 'ct-empty', '此范围没有可查看的已完成服务。'));
      pager.replaceChildren();
      if (offset)
        pager.append(
          btn(ctx, '上一页', () => {
            offset = Math.max(0, offset - 15);
            load();
          })
        );
      if (result.nextOffset !== null)
        pager.append(
          btn(ctx, '下一页', () => {
            offset = result.nextOffset;
            load();
          })
        );
    } catch (error) {
      if (generation !== ticket || !root.isConnected) return;
      caption.textContent = error.message;
      events.replaceChildren();
      pager.replaceChildren(btn(ctx, '重新载入', reset));
    }
  }
  day.onchange = reset;
  search.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(reset, 180);
  };
  queueMicrotask(load);
  return root;
}

export function scopedHistoryButton(ctx, scope, id) {
  if (!ctx.openChanges || !ctx.available('history') || ctx.state.user.kind === 'family')
    return null;
  return btn(ctx, '最近改动', () => ctx.openChanges({ [scope + 'Id']: id }));
}
