import { icon } from '../lib/ui.js';
import {
  node,
  page,
  table,
  choose,
  btn,
  link,
  badge,
  named,
  section,
  facts,
} from './shared.js';
import { routes } from '../lib/navigation.js';

function inputField(label, name, value = '', options = {}) {
  const control = node('input');
  control.name = name;
  control.type = options.type || 'text';
  control.value = value;
  control.required = options.required !== false;
  control.maxLength = options.max || 128;
  if (options.min) control.minLength = options.min;
  if (options.autocomplete) control.autocomplete = options.autocomplete;
  if (options.placeholder) control.placeholder = options.placeholder;
  return [node('label', 'field', [node('span', '', label), control]), control];
}

function selectField(label, items, current) {
  const control = node('select');
  for (const [value, text] of items) control.add(new Option(text, value));
  if (current) control.value = current;
  return [node('label', 'field', [node('span', '', label), control]), control];
}

function checkboxes(items, current) {
  const choices = new Map();
  const grid = node('div', 'access-choices');
  for (const [value, label] of items) {
    const input = node('input');
    input.type = 'checkbox';
    input.checked = current.includes(value);
    choices.set(value, input);
    grid.append(node('label', 'access-check', [input, node('span', '', label)]));
  }
  return {
    element: grid,
    read: () => [...choices].filter(([, box]) => box.checked).map(([value]) => value),
    write: (values) =>
      choices.forEach((input, key) => {
        input.checked = values.includes(key);
      }),
    choices,
  };
}

function saveForm(form, label, submit) {
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const button = node('button', 'btn btn-primary', label);
  button.type = 'submit';
  form.append(error, node('div', 'dialog-actions', button));
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    error.textContent = '';
    try {
      const success = await submit();
      if (success === false)
        error.textContent =
          document.getElementById('announcer')?.textContent || '未能保存，请检查输入。';
    } catch (cause) {
      error.textContent = cause.message;
    } finally {
      button.disabled = false;
    }
  });
}

function careFlowFigure() {
  const figure = node('figure', 'access-flow');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 480 225');
  svg.setAttribute('aria-hidden', 'true');
  // An isometric record, plan and receipt share a line of evidence.
  svg.innerHTML = `<defs>
    <linearGradient id="sheetTop" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#649cff"/><stop offset="1" stop-color="#244faa"/></linearGradient>
    <linearGradient id="sheetMid"><stop stop-color="#2351ab"/><stop offset="1" stop-color="#4385eb"/></linearGradient>
    <pattern id="careGrid" width="22" height="22" patternUnits="userSpaceOnUse" patternTransform="matrix(1 -.47 .94 .46 0 0)"><path d="M22 0H0v22" fill="none" stroke="#afcaff" opacity=".23" stroke-width="1"/></pattern>
  </defs>
  <g stroke-linejoin="round" stroke-width="1.3">
    <path d="m14 150 125-62 149 66-126 61z" fill="url(#careGrid)" stroke="#7494c7" stroke-dasharray="3 6" opacity=".65"/>
    <path d="m27 123 115-53 127 55v9l-115 54-127-55z" fill="#24468b" stroke="#6e9cd8"/>
    <path d="m27 123 115-53 127 55-115 55z" fill="#254f9d" stroke="#70a4f1"/>
    <path d="m27 97 115-53 127 55v9l-115 54-127-55z" fill="#2466b5" stroke="#91c0fb"/>
    <path d="m27 97 115-53 127 55-115 55z" fill="url(#sheetMid)" stroke="#96c2ff"/>
    <path d="m27 68 115-53 127 55v10l-115 54-127-55z" fill="#27498b" stroke="#aecfff"/>
    <path d="m27 68 115-53 127 55-115 55z" fill="url(#sheetTop)" stroke="#cfdeff"/>
    <g transform="matrix(.91,-.42,.98,.42,65,67)" fill="none" stroke="#d5e5ff" stroke-linecap="round">
      <rect x="0" y="0" width="84" height="82" rx="6" fill="#315da4" fill-opacity=".54"/>
      <path d="M11 57h60m-60 10h38" stroke-width="3.4"/>
      <path d="M36 9h13v11h11v13H49v11H36V33H25V20h11z" fill="#dcecff" stroke="none"/>
    </g>
    <g fill="none" stroke="#8db4f6"><path d="m243 58 33-19h51"/><path d="m256 104 24-12h47"/><path d="m247 143 35 15h45"/></g>
    <g fill="#eabb6e"><circle cx="243" cy="58" r="3"/><circle cx="256" cy="104" r="3"/><circle cx="247" cy="143" r="3"/></g>
  </g>
  <g fill="#edf2ff" font-size="17" font-family="sans-serif"><text x="342" y="45">长者档案</text><text x="342" y="98">照护工单</text><text x="342" y="164">执行留痕</text></g>`;
  figure.setAttribute('aria-label', '照护流程：由长者档案形成照护工单，执行后留存记录。');
  figure.append(svg);
  return figure;
}

export function loginScreen(onLogin, branding = {}) {
  const main = node('main', 'access-login');
  const hero = node('section', 'access-login-hero');
  const mark = node('img', 'access-logo');
  mark.src = '/assets/mark.svg';
  mark.alt = '';
  hero.append(
    node('div', 'access-brand', [mark, node('strong', '', branding.brandName || '安康医养平台')])
  );
  const product = node('div', 'access-product');
  product.append(
    node('span', 'access-edition', branding.institutionName || '安康家园'),
    node('h1', '', branding.brandName || '安康医养平台'),
    careFlowFigure()
  );
  hero.append(product);

  const entry = node('section', 'access-login-entry'),
    panel = node('div', 'access-login-panel');
  panel.append(
    node('span', 'access-login-icon', icon('shield', 25)),
    node('h2', '', '登录工作台'),
    node('p', 'access-login-intro', '使用机构分配的员工、亲属或总管理员账号。')
  );
  const form = node('form', 'access-form access-login-form');
  const [nameRow, name] = inputField('登录账号', 'username', '', {
    autocomplete: 'username',
    max: 40,
    placeholder: '输入登录名',
  });
  const [passwordRow, password] = inputField('密码', 'password', '', {
    type: 'password',
    autocomplete: 'current-password',
    placeholder: '输入密码',
  });
  const passwordWrap = node('span', 'access-pwd-wrap');
  const reveal = node('button', 'access-reveal', '显示');
  reveal.type = 'button';
  reveal.setAttribute('aria-label', '显示密码');
  reveal.setAttribute('aria-pressed', 'false');
  reveal.addEventListener('click', () => {
    const visible = password.type === 'password';
    password.type = visible ? 'text' : 'password';
    reveal.textContent = visible ? '隐藏' : '显示';
    reveal.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码');
    reveal.setAttribute('aria-pressed', String(visible));
  });
  password.replaceWith(passwordWrap);
  passwordWrap.append(password, reveal);
  form.append(nameRow, passwordRow);
  saveForm(form, '登录', async () => {
    const result = await onLogin(name.value.trim(), password.value);
    if (result !== false) password.value = '';
    return result;
  });
  const help = node('p', 'access-login-help', [
    icon('info', 16),
    node('span', '', '账号尚未开通或需要重设密码，请联系机构管理员。'),
  ]);
  panel.append(form, help);
  entry.append(panel);
  main.append(hero, entry);
  return main;
}

function editAccount(ctx, kind, target = null, defaultRole = '护工') {
  const state = ctx.state;
  const family = kind === 'family';
  const form = node('form', 'access-form');
  const [nameRow, name] = inputField('姓名', 'displayName', target?.displayName || '', { max: 60 });
  form.append(nameRow);
  let username, password, resident;
  if (!target) {
    let row;
    [row, username] = inputField('登录名', 'username', '', {
      min: 3,
      max: 40,
      autocomplete: 'off',
      placeholder: '3–40 位字母、数字、点、下划线或短横线',
    });
    username.pattern = '[A-Za-z0-9][A-Za-z0-9_.\\-]{2,39}';
    form.append(row);
    [row, password] = inputField('初始密码', 'password', '', {
      type: 'password',
      min: 10,
      autocomplete: 'new-password',
      placeholder: '至少 10 个字符',
    });
    form.append(row);
  }
  let role, grants;
  if (family) {
    if (!target) {
      const options = state.residents.map((r) => [r.id, r.name + ' · ' + r.id]);
      const [residentRow, select] = selectField('已获授权的长者', options);
      resident = select;
      resident.required = true;
      form.append(
        residentRow,
        node('p', 'fx-muted', '请先核验亲属身份和长者授权。绑定后，该账号只能完善自己的亲属资料。')
      );
    } else {
      form.append(
        facts([
          [
            '绑定长者',
            state.residents.find((r) => r.id === target.residentId)?.name || target.residentId,
          ],
        ])
      );
    }
  } else {
    const preset = target?.role || defaultRole;
    const [roleRow, roleSelect] = selectField(
      '岗位模板',
      Object.keys(state.rolePresets).map((x) => [x, x]),
      preset
    );
    role = roleSelect;
    grants = checkboxes(
      Object.entries(state.permissionOptions),
      target?.permissions || state.rolePresets[preset]
    );
    role.addEventListener('change', () => grants.write(state.rolePresets[role.value] || []));
    grants.choices.get('medical.write')?.addEventListener('change', (e) => {
      if (e.target.checked) grants.choices.get('medical').checked = true;
    });
    grants.choices.get('medical')?.addEventListener('change', (e) => {
      if (!e.target.checked) grants.choices.get('medical.write').checked = false;
    });
    form.append(roleRow, section('授权项目', grants.element));
  }
  saveForm(form, target ? '保存变更' : '创建账号', () => {
    const payload = { displayName: name.value };
    if (target) payload.id = target.id;
    else Object.assign(payload, { kind, username: username.value, password: password.value });
    if (!family) Object.assign(payload, { role: role.value, permissions: grants.read() });
    else if (!target) payload.residentId = resident.value;
    return ctx.command(target ? 'access.update' : 'access.create', payload);
  });
  ctx.detail(target ? '编辑账号' : family ? '绑定亲属账号' : '新增员工账号', form);
}

function resetPassword(ctx, row) {
  const fields = [];
  if (row.kind === 'owner')
    fields.push({ name: 'currentPassword', label: '当前密码', type: 'password', required: true });
  fields.push({
    name: 'password',
    label: '新密码（10–128 个字符）',
    type: 'password',
    required: true,
    maxLength: 128,
  });
  ctx.dialog({
    title: '重设 ' + row.username + ' 的密码',
    description: '保存后该账号在各端的旧会话会立即结束。',
    fields,
    submitLabel: '重设密码',
    onSubmit: (values) => ctx.command('access.password', { id: row.id, ...values }),
  });
}

function status(ctx, row) {
  ctx.dialog({
    title: row.enabled ? '停用账号' : '恢复账号',
    description: row.enabled
      ? '停用 ' + row.username + ' 后，其所有已登录设备将失去访问权限。'
      : '账号 ' + row.username + ' 将可以按现有授权重新登录。',
    fields: [],
    submitLabel: row.enabled ? '确认停用' : '确认恢复',
    onSubmit: () => ctx.command('access.update', { id: row.id, enabled: !row.enabled }),
  });
}

function roleTemplates(ctx) {
  const icons = { 院长: 'building', 护士: 'pulse', 护工: 'people', 财务: 'wallet', 自定义: 'list' };
  const panel = node('section', 'access-templates');
  panel.append(node('h2', '', '岗位模板'));
  const cards = node('div', 'access-template-list');
  for (const [role, permissions] of Object.entries(ctx.state.rolePresets)) {
    const card = node('button', 'access-template');
    card.type = 'button';
    card.append(
      node('span', 'access-template-icon', icon(icons[role] || 'people', 19)),
      node('strong', '', role),
      node('small', '', permissions.length + ' 项授权')
    );
    card.addEventListener('click', () => {
      const content = node('section', 'access-template-detail');
      if (permissions.length)
        content.append(
          node(
            'ul',
            'access-grant-list',
            permissions.map((key) => node('li', '', ctx.state.permissionOptions[key]))
          )
        );
      else content.append(node('p', 'access-login-intro', '从空权限开始勾选。'));
      content.append(
        btn(ctx, '按此模板新增员工', () => editAccount(ctx, 'staff', null, role), 'primary')
      );
      ctx.detail(role + ' · 岗位模板', content);
    });
    cards.append(card);
  }
  panel.append(cards);
  return panel;
}

function accounts(ctx) {
  const state = ctx.state;
  const management = page(
    ctx,
    '账号与权限',
    '按岗位分配员工权限，核验后绑定亲属账号。',
    choose(
      btn(ctx, '绑定亲属', () => editAccount(ctx, 'family')),
      btn(ctx, '新增员工', () => editAccount(ctx, 'staff'), 'primary')
    ),
    roleTemplates(ctx),
    table(ctx, {
      title: '机构账号',
      rows: state.accounts,
      search: {
        placeholder: '搜索姓名、岗位或账号',
        value: (r) => [r.displayName, r.username, r.role].join(' '),
      },
      filter: {
        label: '账号类别',
        all: '全部类别',
        value: (r) => ({ owner: '总管理员', staff: '员工', family: '亲属' })[r.kind],
      },
      cols: [
        { label: '姓名 / 登录名', view: (r) => named(r.displayName, r.username) },
        {
          label: '岗位',
          view: (r) =>
            node('span', r.kind === 'owner' ? 'access-role owner' : 'access-role', r.role),
        },
        {
          label: '权限',
          view: (r) =>
            r.kind === 'owner'
              ? '全部权限'
              : r.kind === 'family'
                ? '本人资料'
                : link(ctx, r.permissions.length + ' 项', () =>
                    ctx.detail(
                      r.displayName + ' 的权限',
                      node(
                        'ul',
                        'access-grant-list',
                        r.permissions.map((p) => node('li', '', state.permissionOptions[p]))
                      )
                    )
                  ),
        },
        {
          label: '状态',
          view: (r) => badge(ctx, r.enabled ? '已启用' : '已停用', r.enabled ? 'green' : 'neutral'),
        },
        {
          label: '操作',
          align: 'end',
          view: (r) =>
            choose(
              r.kind === 'owner' ? null : link(ctx, '编辑', () => editAccount(ctx, r.kind, r)),
              link(ctx, '重设密码', () => resetPassword(ctx, r)),
              r.kind === 'owner'
                ? null
                : link(ctx, r.enabled ? '停用' : '恢复', () => status(ctx, r))
            ),
        },
      ],
    })
  );
  management.classList.add('access-management');
  return management;
}

function settings(ctx) {
  const visual = ctx.state.uiSettings,
    config = ctx.state.settings;
  const appearance = node('form', 'access-settings');
  const [brandRow, brand] = inputField('平台名称', 'brandName', visual.brandName, { max: 30 });
  const [orgRow, org] = inputField('机构名称', 'institutionName', visual.institutionName, {
    max: 30,
  });
  const [themeRow, theme] = selectField(
    '界面配色',
    [
      ['forest', '海军蓝 · 暖金'],
      ['ocean', '海蓝'],
      ['plum', '紫蓝'],
    ],
    visual.theme
  );
  const orgTitle = node('strong'),
    brandTitle = node('span');
  const preview = node('div', 'access-appearance-preview', [
    icon('building', 26),
    node('div', '', [brandTitle, orgTitle]),
  ]);
  const updatePreview = () => {
    orgTitle.textContent = org.value || visual.institutionName;
    brandTitle.textContent = brand.value || visual.brandName;
    preview.dataset.theme = theme.value;
  };
  [brand, org, theme].forEach((control) => control.addEventListener('input', updatePreview));
  updatePreview();
  const routeChoices = ctx.state.user.routes
    .filter((r) => !['overview', 'access', 'settings', 'family'].includes(r))
    .map((r) => [r, routes.get(r)?.label || r]);
  const visible = checkboxes(
    routeChoices,
    routeChoices.map((x) => x[0]).filter((r) => !visual.hiddenRoutes.includes(r))
  );
  appearance.append(
    node('h2', 'access-settings-heading', [icon('layers', 21), '机构界面']),
    preview,
    node('div', 'access-field-pair', [brandRow, orgRow]),
    themeRow,
    section('导航可见模块', visible.element)
  );
  saveForm(appearance, '保存界面设置', () =>
    ctx.command('access.settings', {
      brandName: brand.value,
      institutionName: org.value,
      theme: theme.value,
      hiddenRoutes: routeChoices.map((x) => x[0]).filter((r) => !visible.read().includes(r)),
    })
  );
  const deep = node('form', 'access-settings access-provider');
  const [enableRow, enabled] = selectField(
    '接口开关',
    [
      ['off', '关闭'],
      ['on', '启用预留接口'],
    ],
    config.deepseekEnabled ? 'on' : 'off'
  );
  const [modelRow, model] = inputField('模型标识', 'model', config.deepseekModel, { max: 80 });
  const credential = node('div', 'access-credential', [
    node('span', '', [icon('shield', 17), '服务端凭据']),
    node('strong', '', config.deepseekKeyPresent ? '已配置' : '待配置'),
  ]);
  deep.append(
    node('h2', 'access-settings-heading', [icon('spark', 21), 'DeepSeek 接口']),
    credential,
    node('p', 'fx-muted', '服务端读取 DEEPSEEK_API_KEY。当前阶段保留模型接口。'),
    enableRow,
    modelRow
  );
  saveForm(deep, '保存接口设置', () =>
    ctx.command('access.settings', {
      deepseekEnabled: enabled.value === 'on',
      deepseekModel: model.value,
    })
  );
  const result = page(
    ctx,
    '机构设置',
    '调整工作台外观与总管理员专属的模型接入设置。',
    null,
    node('div', 'access-settings-grid', [appearance, deep])
  );
  result.classList.add('access-management');
  return result;
}

export function renderAccess(route, ctx) {
  if (ctx.state.user?.kind !== 'owner') return ctx.ui.empty('此页面仅供总管理员使用');
  return route === 'settings' ? settings(ctx) : accounts(ctx);
}
