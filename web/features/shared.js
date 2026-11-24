import { routes } from '../lib/navigation.js';
export function node(tag, cls, content) {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  add(element, content);
  return element;
}

export function add(parent, ...items) {
  for (const item of items.flat(Infinity)) {
    if (item !== null && item !== undefined && item !== false) {
      parent.append(item instanceof Node ? item : document.createTextNode(String(item)));
    }
  }
  return parent;
}

export function today(ctx) {
  return (
    ctx.today ||
    ctx.state.today ||
    new Intl.DateTimeFormat('sv-SE', {
      timeZone: 'Asia/Shanghai'
    }).format(new Date())
  );
}

export function nextDay(value) {
  const d = new Date(value + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

export const options = (values) =>
  values.map((value) => ({
    value,
    label: value
  }));

export const field = (name, label, extra = {}) => ({
  name,
  label,
  required: true,
  ...extra
});

export const select = (name, label, choices, extra = {}) =>
  field(name, label, {
    type: 'select',
    options: choices,
    ...extra
  });

export const memo = (name, label, required = false, extra = {}) =>
  field(name, label, {
    type: 'textarea',
    required,
    ...extra
  });

export const residentName = (ctx, id) =>
  ctx.state.residents.find((row) => row.id === id)?.name || '—';

export const bedName = (ctx, id) => ctx.state.beds.find((row) => row.id === id)?.label || '—';

export const active = (ctx) => ctx.state.residents.filter((row) => row.status === '在住');

export const residentField = (ctx, extra = {}) =>
  select(
    'residentId',
    '长者',
    active(ctx).map((row) => ({
      value: row.id,
      label: row.name + ' · ' + bedName(ctx, row.bedId)
    })),
    extra
  );

export const money = (value) =>
  Number(value || 0).toLocaleString('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    maximumFractionDigits: 2
  });

export const byRecent = (rows) => [...rows].reverse();

export const hasGrant = (ctx, ...permissions) =>
  ctx.state.user?.kind === 'owner' ||
  permissions.some((permission) => ctx.state.user?.permissions?.includes(permission));
export const canAct = (ctx, action) => ctx.state.allowedActions?.includes(action) === true;

export const choose = (...items) => node('div', 'fx-actions', items);

export const btn = (ctx, label, fn, variant = 'secondary') => ctx.ui.button(label, fn, variant);

export const link = (ctx, label, fn) => ctx.ui.button(label, fn, 'ghost');

export const named = (title, detail) =>
  node('div', 'fx-named', [node('strong', '', title), detail ? node('small', '', detail) : null]);

export function badge(ctx, value, tone) {
  const good = [
    '在住',
    '已入住',
    '已完成',
    '已执行',
    '已记录',
    '已处理',
    '已结清',
    '已校验',
    '已采纳',
    '已派发',
    '入库'
  ];
  const waiting = ['待复核', '待审核', '待跟进', '部分缴费', '待缴费', '待补正', '出库'];
  return ctx.ui.badge(
    value,
    tone ||
      (good.includes(value)
        ? 'green'
        : waiting.includes(value)
          ? 'amber'
          : value === '待执行'
            ? 'blue'
            : 'neutral')
  );
}

export function page(ctx, title, description, actions, ...content) {
  const meta =
    routes.get(location.hash.slice(1)) || [...routes.values()].find((r) => r.label === title);
  const identity = node('div', 'fx-module-mark', ctx.ui.icon(meta?.icon || 'file', 25));
  const titleBlock = node('div', 'fx-module-title', [
    meta?.group ? node('div', 'fx-module-group', meta.group) : null,
    node('h1', '', title)
  ]);
  const header = node('header', 'fx-module-head', [
    node('div', 'fx-module-identity', [identity, titleBlock]),
    actions ? node('div', 'fx-module-actions', actions) : null,
    description ? node('p', 'fx-module-description', description) : null
  ]);
  return node('section', 'fx-page', [header, ...content]);
}

export function facts(entries) {
  const list = node('dl', 'fx-facts');
  for (const [key, value] of entries)
    add(list, node('div', '', [node('dt', '', key), node('dd', '', value || '—')]));
  return list;
}

export function recordIdentity(ctx, resident, detail) {
  const meta = [resident.id, detail].filter(Boolean).join(' · ');
  return node('header', 'fx-identity', [
    node('span', 'fx-initial', ctx.ui.icon('people', 22)),
    node('div', '', [node('h3', '', resident.name), node('small', 'fx-muted', meta)]),
    resident.status ? badge(ctx, resident.status) : null
  ]);
}

export function disclosure(title, child, count) {
  const header = node('summary', 'fx-disclosure-head', [
    node('strong', '', title),
    typeof count === 'number' ? node('span', 'fx-count', count + ' 条') : null
  ]);
  return node('details', 'fx-disclosure', [header, node('div', 'fx-disclosure-body', child)]);
}

export function section(title, child) {
  return node('section', 'fx-section', [node('h3', '', title), child]);
}

export function records(items, render, empty = '暂无记录') {
  return items.length
    ? node(
        'ul',
        'fx-records',
        items.map((item) => node('li', '', render(item)))
      )
    : node('p', 'fx-muted', empty);
}

export function runForm(
  ctx,
  {
    title,
    action,
    fields: fields = [],
    submitLabel: submitLabel = '保存',
    description,
    defaults: defaults = {},
    map
  }
) {
  if (!canAct(ctx, action)) {
    ctx.toast('当前账号没有此项操作权限');
    return;
  }
  const dataFields = fields.map((item) =>
    Object.hasOwn(defaults, item.name)
      ? {
          ...item,
          value: defaults[item.name]
        }
      : item
  );
  if (dataFields.some((item) => item.required && item.type === 'select' && !item.options?.length)) {
    ctx.toast('当前没有可选记录，请先补充相关业务数据。');
    return;
  }
  ctx.dialog({
    title,
    description: [description, '提交人 ' + ctx.state.user.displayName].filter(Boolean).join(' · '),
    fields: dataFields,
    submitLabel,
    onSubmit: (values) => {
      const clean = Object.fromEntries(Object.entries(values).filter(([, value]) => value !== ''));
      return ctx.command(action, map ? map(clean) : clean, { title });
    }
  });
}

export function kpis(items) {
  return node(
    'div',
    'fx-kpis',
    items.map(([label, value]) =>
      node('div', 'fx-kpi', [node('span', '', label), node('strong', '', value)])
    )
  );
}

export function table(
  ctx,
  { title, rows, cols, search, filter, action, empty: empty = '暂无记录' }
) {
  const panel = node('section', 'fx-panel');
  const toolbar = node('div', 'fx-toolbar');
  const heading = node('div', 'fx-panel-title', [
    node('span', 'fx-ledger-icon', ctx.ui.icon('list', 17)),
    node('h2', '', title)
  ]);
  const count = node('span', 'fx-count');
  heading.append(count);
  const tools = node('div', 'fx-table-tools');
  const input = node('input', 'fx-input');
  input.type = 'search';
  input.placeholder = search?.placeholder || '搜索记录';
  input.setAttribute('aria-label', input.placeholder);
  const picker = node('select', 'fx-input');
  if (filter) {
    picker.setAttribute('aria-label', filter.label || '筛选状态');
    const values = filter.options || [...new Set(rows.map(filter.value).filter(Boolean))];
    ['', ...values].forEach((value) => {
      const opt = node('option', '', value || filter.all || '全部状态');
      opt.value = value;
      picker.append(opt);
    });
    picker.value = filter.initial || '';
  }
  const searchBox = node('label', 'fx-table-search', [ctx.ui.icon('search', 16), input]);
  add(tools, search ? searchBox : null, filter ? picker : null);
  add(toolbar, heading, action);
  const wrap = node('div', 'fx-table-wrap');
  const grid = node('table', 'fx-table');
  const head = node('tr');
  for (const col of cols) {
    const th = node('th', col.align === 'end' ? 'fx-end' : '', col.label);
    th.scope = 'col';
    head.append(th);
  }
  const body = node('tbody');
  add(grid, node('thead', '', head), body);
  wrap.append(grid);
  const blank = node('div', 'fx-empty');
  let currentPage = 0;
  const pageSize = 12;
  const pagination = node('div', 'fx-pagination');
  const pageInfo = node('span', 'fx-muted');
  const previous = btn(ctx, '上一页', () => {
    currentPage -= 1;
    update();
  });
  const next = btn(ctx, '下一页', () => {
    currentPage += 1;
    update();
  });
  add(pagination, pageInfo, previous, next);
  const update = () => {
    const needle = input.value.trim().toLocaleLowerCase();
    const subset = rows.filter(
      (row) =>
        (!needle ||
          String(search?.value(row) || '')
            .toLocaleLowerCase()
            .includes(needle)) &&
        (!filter ||
          !picker.value ||
          (filter.matches ? filter.matches(row, picker.value) : filter.value(row) === picker.value))
    );
    count.textContent = subset.length + ' 条';
    const pages = Math.max(1, Math.ceil(subset.length / pageSize));
    currentPage = Math.min(Math.max(0, currentPage), pages - 1);
    const focus = (ctx.focusIds || []).find((id) => subset.some((row) => row.id === id));
    if (focus && !panel.isConnected)
      currentPage = Math.floor(subset.findIndex((row) => row.id === focus) / pageSize);
    const start = currentPage * pageSize;
    pagination.hidden = pages === 1;
    pageInfo.textContent = '第 ' + (currentPage + 1) + ' 页 / 共 ' + pages + ' 页';
    previous.disabled = currentPage === 0;
    next.disabled = currentPage === pages - 1;
    body.replaceChildren(
      ...subset.slice(start, start + pageSize).map((row) =>
        node(
          'tr',
          focus && row.id === focus ? 'change-focus' : '',
          cols.map((col) => {
            const cell = node('td', col.align === 'end' ? 'fx-end' : '', col.view(row) ?? '—');
            cell.dataset.label = col.label;
            return cell;
          })
        )
      )
    );
    blank.hidden = Boolean(subset.length);
    blank.textContent = rows.length ? '没有匹配的记录' : empty;
  };
  function resetPage() {
    currentPage = 0;
    update();
  }
  input.addEventListener('input', resetPage);
  picker.addEventListener('change', resetPage);
  add(panel, toolbar, tools.childElementCount ? tools : null, wrap, blank, pagination);
  update();
  return panel;
}

const selectedTabs = new Map();

export function selectTab(route, key) {
  selectedTabs.set(route, key);
}

export function tabs(route, choices) {
  let selected = selectedTabs.get(route);
  if (!choices.some((item) => item[0] === selected)) selected = choices[0][0];
  const buttons = node('div', 'fx-tabs');
  buttons.setAttribute('aria-label', '工作视图');
  const body = node('div', 'fx-tab-body');
  buttons.setAttribute('role', 'tablist');
  body.setAttribute('role', 'tabpanel');
  function show(key) {
    selectedTabs.set(route, key);
    for (const button of buttons.children) {
      const active = button.dataset.key === key;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      if (active) body.setAttribute('aria-label', button.textContent);
    }
    body.replaceChildren(choices.find((item) => item[0] === key)[2]());
  }
  for (const [key, label] of choices) {
    const button = node('button', '', label);
    button.type = 'button';
    button.dataset.key = key;
    button.setAttribute('role', 'tab');
    button.addEventListener('keydown', (event) => {
      const items = Array.from(buttons.children),
        position = items.indexOf(button);
      const destination = {
        ArrowLeft: (position + items.length - 1) % items.length,
        ArrowRight: (position + 1) % items.length,
        Home: 0,
        End: items.length - 1
      }[event.key];
      if (destination === undefined) return;
      event.preventDefault();
      items[destination].click();
      items[destination].focus();
    });
    button.addEventListener('click', () => show(key));
    buttons.append(button);
  }
  show(selected);
  return node('div', 'fx-tabset', [buttons, body]);
}
