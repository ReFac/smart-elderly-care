import { residentLabel, staffLabel } from './people-labels.js';
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

export const residentName = residentLabel;

export const bedName = (ctx, id) => ctx.state.beds.find((row) => row.id === id)?.label || '—';

export const active = (ctx) => ctx.state.residents.filter((row) => row.status === '在住');

export function staffField(ctx, name, label, extra = {}) {
  const accounts = new Map([ctx.state.user, ...(ctx.state.accounts || [])]
    .filter(a => a && a.kind !== 'family' && a.enabled !== false).map(a => [a.id, a]));
  const labels = new Set([
    ...[...accounts.values()].map(a => a.displayName),
    ...(ctx.state.shifts || []).map(row=>row.staff),
    extra.value,
  ].filter(Boolean));
  return select(name, label, [
    {value:'',label:extra.required===false?'按业务默认安排':'请选择人员'},
    ...[...labels].sort((a,b)=>a.localeCompare(b,'zh-CN')).map(value => {
      const matches = [...accounts.values()].filter(a => a.displayName === value);
      return { value, label: staffLabel(ctx, matches.length === 1 ? matches[0] : value) };
    }),
  ], {...extra, allowCustom:true});
}

export const residentField = (ctx, extra = {}) =>
  select(
    'residentId',
    '长辈',
    active(ctx).map((row) => ({
      value: row.id,
      label: residentLabel(ctx, row)
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
          : ['待执行', '试住中'].includes(value)
            ? 'blue'
            : 'neutral')
  );
}

export function page(ctx, title, description, actions, ...content) {
  const header = node('header', 'fx-module-head', [
    node('h1', '', title), actions ? node('div', 'fx-module-actions', actions) : null
  ]);
  if (description) {
    const info = node('details', 'desk-page-help');
    add(info, node('summary', '', '说明'), node('p','',description));
    header.append(info);
  }
  return node('section', 'fx-page', [header, ...content]);
}

export function facts(entries) {
  const list = node('dl', 'fx-facts');
  for (const [key, value] of entries)
    add(list, node('div', '', [node('dt', '', key), node('dd', '', value == null || value === '' ? '—' : value)]));
  return list;
}

export function recordIdentity(ctx, resident, detail) {
  const meta = [resident.id, detail].filter(Boolean).join(' · ');
  return node('header', 'fx-identity', [
    node('span', 'fx-initial', ctx.ui.icon('people', 22)),
    node('div', '', [node('h3', '', residentLabel(ctx, resident)), node('small', 'fx-muted', meta)]),
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
    description: [description, '提交人 ' + staffLabel(ctx, ctx.state.user)].filter(Boolean).join(' · '),
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
  const panel = node('section','fx-panel');
  const saved = ctx.workspaceState ? (ctx.workspaceState.tables ||= Object.create(null)) : {};
  const prefs = saved[title] ||= { q:'', filter:filter?.initial || '', page:0, size:20 };
  const heading = node('div','fx-panel-title',[node('h2','',title)]);
  const count = node('span','fx-count'); heading.append(count);
  const toolbar = node('div','fx-toolbar',[heading,action]);
  const tools = node('form','fx-table-tools');
  tools.setAttribute('role','search');
  const input = node('input','fx-input'); input.type='search';
  input.placeholder = search?.placeholder || '搜索记录';
  input.setAttribute('aria-label',input.placeholder);
  input.value = prefs.q;
  const picker = node('select','fx-input');
  if (filter) {
    const values = filter.options || [...new Set(rows.map(filter.value).filter(Boolean))];
    for (const value of ['',...values]) picker.add(new Option(value || filter.all || '全部状态',value));
    picker.value = prefs.filter;
  }
  if (search) tools.append(node('label','desk-filter',['关键字',input]));
  if (filter) tools.append(node('label','desk-filter',[filter.label || '状态',picker]));
  if (search || filter) {
    const submit = node('button','btn btn-primary',[ctx.ui.icon('search',14),'搜索']); submit.type='submit';
    const reset = ctx.ui.button('重置',() => {
      input.value=''; picker.value=''; prefs.q=''; prefs.filter=''; prefs.page=0; update();
    },'secondary','refresh');
    add(tools,submit,reset);
  }
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
  const pagination = node('div','fx-pagination');
  const pageInfo = node('span','fx-muted');
  const size = node('select','desk-page-size');
  size.setAttribute('aria-label','每页条数');
  for (const n of [20,50,100]) size.add(new Option(n + '条/页',String(n)));
  size.value = String(prefs.size);
  size.onchange = () => {prefs.size=Number(size.value); prefs.page=0; update();};
  const previous = ctx.ui.button('',()=>{prefs.page--; update();},'secondary','left');
  previous.setAttribute('aria-label','上一页');
  const next = ctx.ui.button('',()=>{prefs.page++; update();},'secondary','chevron');
  next.setAttribute('aria-label','下一页');
  const pageNumber = node('b','desk-page-number');
  const jump = node('input','desk-page-jump'); jump.type='number'; jump.min=1;
  jump.setAttribute('aria-label','前往页码');
  jump.onchange=()=>{prefs.page=(Number(jump.value)||1)-1; update();};
  add(pagination,pageInfo,size,previous,pageNumber,next,node('label','desk-page-to',['前往',jump,'页']));
  const update = () => {
    const needle = prefs.q.trim().normalize('NFKC').toLocaleLowerCase();
    const subset = rows.filter(
      (row) =>
        (!needle ||
          String(search?.value(row) || '')
            .normalize('NFKC').toLocaleLowerCase()
            .includes(needle)) &&
        (!filter ||
          !prefs.filter ||
          (filter.matches ? filter.matches(row, prefs.filter) : filter.value(row) === prefs.filter))
    );
    count.textContent = subset.length + ' 条';
    const pages = Math.max(1,Math.ceil(subset.length/prefs.size));
    prefs.page = Math.min(Math.max(0,Math.trunc(prefs.page)),pages-1);
    const focus = (ctx.focusIds || []).find((id) => subset.some((row) => row.id === id));
    if (focus && !panel.isConnected) prefs.page = Math.floor(subset.findIndex(row=>row.id === focus)/prefs.size);
    const start = prefs.page * prefs.size;
    pagination.hidden = !rows.length;
    pageInfo.textContent='共 ' + subset.length + ' 条';
    pageNumber.textContent=String(prefs.page+1);
    pageNumber.title='共 ' + pages + ' 页';
    jump.max=pages; jump.value=String(prefs.page+1);
    previous.disabled=prefs.page===0; next.disabled=prefs.page===pages-1;
    body.replaceChildren(
      ...subset.slice(start, start + prefs.size).map((row) =>
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
  tools.onsubmit = (event) => {
    event.preventDefault(); prefs.page=0; prefs.q=input.value.trim();
    prefs.filter=picker.value; update();
  };
  add(panel, tools.childElementCount ? tools : null, toolbar, wrap, blank, pagination);
  update();
  return panel;
}

const selectedTabs = new Map();

export function resetSelectedTabs() { selectedTabs.clear(); }

export function selectTab(route, key) {
  selectedTabs.set(route, key);
}

export function currentTab(route) {
  return selectedTabs.get(route);
}

export function tabs(route, choices) {
  let selected = selectedTabs.get(route);
  if (!choices.some((item) => item[0] === selected)) selected = choices[0][0];
  const buttons = node('div', 'fx-tabs');
  buttons.dataset.route = route;
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
    button.dataset.label = label;
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
    button.addEventListener('click', () => {
      const nav = new CustomEvent('desk:view', {bubbles:true,cancelable:true,detail:{route,key,label}});
      if (button.dispatchEvent(nav)) show(key);
    });
    buttons.append(button);
  }
  show(selected);
  return node('div', 'fx-tabset', [buttons, body]);
}
