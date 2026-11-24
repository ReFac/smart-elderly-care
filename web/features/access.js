import { residentLabel, residentAnchor, staffLabel } from './people-labels.js';
import { backupPanel } from './backups.js';
import { roundsSettings } from './rounds-desk.js';
import { passwordFlow } from './identity.js';
import { openDossier } from './dossier.js';
import { openEmployment } from './staff-employment.js';
import { icon } from '../lib/ui.js';
import { node, page, table, choose, btn, link, badge, named, section, facts, tabs } from './shared.js';
import { routes } from '../lib/navigation.js';
import { capabilitySummary, draftPreview, grantPicker } from './access-grants.js';
import { trialSettings } from './trial-stays.js';

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
    node('div', 'access-brand', [mark, node('strong', '', branding.brandName || '安康医养平台')]),
  );
  const product = node('div', 'access-product');
  product.append(
    node('span', 'access-edition', branding.institutionName || '安康家园'),
    node('h1', '', branding.brandName || '安康医养平台'),
    careFlowFigure(),
  );
  hero.append(product);

  const entry = node('section', 'access-login-entry'),
    panel = node('div', 'access-login-panel');
  panel.append(
    node('span', 'access-login-icon', icon('shield', 25)),
    node('h2', '', '登录工作台'),
    node('p', 'access-login-intro', '使用机构分配的员工、亲属或总管理员账号。'),
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
    node('span', '', '账号使用已登记的邮箱或手机验证身份。'),
  ]);
  const recover = node('button','btn btn-ghost','首次设置 / 找回密码');
  recover.type='button'; recover.onclick=()=>passwordFlow({username:name.value.trim()});
  const visit = node('a', 'access-visitor-link', [icon('calendar', 18), node('strong', '', '访客咨询与预约参观'), icon('chevron', 16)]);
  visit.href = '/visit';
  panel.append(form, recover, help, visit);
  entry.append(panel);
  main.append(hero, entry);
  return main;
}

function editAccount(ctx, kind, target = null, defaultRole = '护工') {
  const state = ctx.state;
  const family = kind === 'family';
  const form = node('form', 'access-form');
  const [nameRow, name] = inputField('姓名', 'displayName', target?.displayName || '', { max: 60 });
  const identity = node('div', 'access-field-pair', nameRow);
  form.append(identity);
  let username, inviteChannel, inviteAddress, duties, resident, familyServices, portalIdentity;
  const scopeControls = new Map();
  if (!target) {
    let row;
    [row, username] = inputField('登录名', 'username', '', {
      min: 3,
      max: 40,
      autocomplete: 'off',
      placeholder: '3–40 位字母、数字、点、下划线或短横线',
    });
    username.pattern = '[A-Za-z0-9][A-Za-z0-9_.\\-]{2,39}';
    identity.append(row);
  }
  if (!target || target.activationPending) {
    let row,channelRow;
    [channelRow, inviteChannel] = selectField('本人验证渠道', [['email','邮箱'],['sms','手机']]);
    [row, inviteAddress] = inputField('激活联系方式','destination','',{type:'email',max:254});
    inviteAddress.required = !target;
    if(target) inviteAddress.placeholder='如需更正首次邀请，请填写新地址';
    const adapt = () => {inviteAddress.type=inviteChannel.value==='email'?'email':'tel';};
    inviteChannel.onchange=adapt;
    form.append(channelRow,row,node('p','fx-muted','请本人核对联系方式。创建后，由本人在登录页接收验证码并设置密码。未接通的渠道须待机构完成配置后使用。'));
  }
  if(target)
    identity.append(
      node('div', 'access-fixed-login', [
        node('span', '', '登录名'),
        node('strong', '', target.username),
      ]),
    );
  let role, grants, campus;
  if (family) {
    if (!target) {
      const options = state.residents.map((r) => [r.id, residentLabel(ctx, r) + ' · ' + r.id]);
      options.unshift(['', '请选择已核验授权的长者']);
      const [residentRow, select] = selectField('已获授权的长者', options);
      resident = select;
      resident.required = true;
      const [typeRow, typeControl] = selectField('使用人', [
        ['family', '已授权亲属'],
        ['self', '长者本人'],
      ]);
      portalIdentity = typeControl;
      form.append(
        typeRow,
        residentRow,
        node('p', 'fx-muted', '请核对使用人身份、绑定长者和查阅授权。'),
      );
    } else {
      form.append(
        facts([
          [
            '绑定长者',
            residentLabel(ctx, target.residentId),
          ],
        ]),
      );
    }
    familyServices = node('input');
    familyServices.type = 'checkbox';
    familyServices.name = 'familyServices';
    familyServices.checked = target?.familyServices === true;
    const scopeRows = [
      ['careSchedule', '查看照护工单与执行进度'],
      ['medication', '查看已复核医嘱和给药时间'],
    ].map(([key, label]) => {
      const control = node('input');
      control.type = 'checkbox';
      control.name = key;
      control.checked = target?.portalScopes?.includes(key) || false;
      scopeControls.set(key, control);
      return node('label', 'access-check', [control, node('span', '', label)]);
    });
    form.append(
      section(
        '绑定账号查阅授权',
        node('div', 'access-family-grant', [
          node('label', 'access-check', [familyServices, node('span', '', '查看已完成的照护服务')]),
          ...scopeRows,
          node('p', 'fx-muted', '每项授权只适用于此账号和绑定长者，可随时收回。'),
        ]),
      ),
    );
  } else {
    const preset = target?.role || defaultRole;
    const [roleRow, roleSelect] = selectField(
      '岗位模板',
      Object.keys(state.rolePresets).map((x) => [x, x]),
      preset,
    );
    const campusOptions = (state.campusOptions || []).map((item) => [item.id, item.name]);
    if (!state.user.facilityScope?.campusIds) campusOptions.unshift(['', '全机构']);
    const [campusRow, campusSelect] = selectField(
      '工作分院',
      campusOptions,
      target?.facilityScope?.campusIds?.[0] || campusOptions[0]?.[0] || '',
    );
    campus = campusSelect;
    campus.name = 'campusId';
    role = roleSelect;
    role.name = 'role';
    grants = grantPicker(
      state.permissionOptions,
      target?.permissions || state.rolePresets[preset] || [],
    );
    role.addEventListener('change', () => grants.write(state.rolePresets[role.value] || []));
    duties = checkboxes(state.accessManagement.staffDuties.map(v=>[v,v]),target?.staffDuties||[]);
    form.append(
      roleRow,
      campusRow,
      section('岗位职责', duties.element),
      section('授权项目', grants.element),
      draftPreview(ctx, form, () => ({
        ...(target ? { id: target.id } : {}),
        kind: 'staff',
        campusId: campus.value,
        role: role.value,
        permissions: grants.read(),
      })),
    );
  }
  saveForm(form, target ? '保存变更' : '创建账号', () => {
    const payload = { displayName: name.value };
    if (target) {
      payload.id = target.id;
      if(target.activationPending && inviteAddress.value.trim()) payload.invitation={channel:inviteChannel.value,destination:inviteAddress.value.trim()};
    }
    else Object.assign(payload, { kind, username: username.value, invitation:{channel:inviteChannel.value,destination:inviteAddress.value.trim()} });
    if (!family)
      Object.assign(payload, { staffDuties:duties.read(), role: role.value, permissions: grants.read(), campusId: campus.value });
    else {
      payload.familyServices = familyServices.checked;
      payload.portalScopes = [...scopeControls]
        .filter(([, control]) => control.checked)
        .map(([key]) => key);
      if (!target)
        Object.assign(payload, {
          residentId: resident.value,
          portalSelf: portalIdentity.value === 'self',
        });
    }
    return ctx.command(target ? 'access.update' : 'access.create', payload);
  });
  const dialog = ctx.detail(target ? '编辑账号' : family ? '绑定亲属账号' : '新增员工账号', form);
  if (target) dialog.dataset.managedAccountId = target.id;
}

function status(ctx, row) {
  const dialog = ctx.dialog({
    title: row.enabled ? '停用账号' : '恢复账号',
    description: row.enabled
      ? '停用 ' + row.username + ' 后，其所有已登录设备将失去访问权限。'
      : '账号 ' + row.username + ' 将可以按现有授权重新登录。',
    fields: [],
    submitLabel: row.enabled ? '确认停用' : '确认恢复',
    onSubmit: () => ctx.command('access.update', { id: row.id, enabled: !row.enabled }),
  });
  dialog.dataset.managedAccountId = row.id;
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
      node('small', '', permissions.length + ' 项授权'),
    );
    card.addEventListener('click', () => {
      const content = node('section', 'access-template-detail');
      if (permissions.length)
        content.append(
          node(
            'ul',
            'access-grant-list',
            permissions.map((key) => node('li', '', ctx.state.permissionOptions[key])),
          ),
        );
      else content.append(node('p', 'access-login-intro', '从空权限开始勾选。'));
      const detail = ctx.detail(role + ' · 岗位模板', content);
      content.append(
        btn(
          ctx,
          '按此模板新增员工',
          () => {
            detail.close();
            editAccount(ctx, 'staff', null, role);
          },
          'primary',
        ),
      );
    });
    cards.append(card);
  }
  panel.append(cards);
  return panel;
}

function accounts(ctx) {
  const state = ctx.state;
  const isOwner = state.accessManagement.scope === 'institution';
  const identityLabel = r => r.kind==='family' ? (r.portalSelf?'入住长者':'亲属') : (r.kind==='owner'?'总管理员':'员工');
  const boundPerson = r => state.residents.find(p=>p.id===r.residentId);
  function showPermissions(account) {
    const grants =
      account.kind === 'staff'
        ? node('details', 'access-capability-section', [
            node('summary', '', '岗位授权 · ' + account.permissions.length),
            account.permissions.length
              ? node(
                  'ul',
                  'access-grant-list',
                  account.permissions.map((key) =>
                    node('li', '', state.permissionOptions[key] || key),
                  ),
                )
              : node('p', 'fx-muted', '当前账号未分配业务权限。'),
          ])
        : null;
    const body = node('div', 'access-permission-detail', [
      node('div', 'access-account-identity', [
        node(
          'span',
          'access-person-icon',
          icon(account.kind === 'owner' ? 'shield' : 'people', 22),
        ),
        named(staffLabel(ctx, account), account.username + ' · ' + account.role),
        badge(ctx, account.enabled ? '已启用' : '已停用', account.enabled ? 'green' : 'neutral'),
      ]),
      account.enabled ? null : node('p', 'fx-muted', '以下为账号恢复启用后的权限。'),
      account.kind === 'family'
        ? facts([
            [
              '绑定长者',
              residentLabel(ctx, account.residentId),
            ],
            ['已完成照护服务', account.familyServices ? '可查阅近期服务日期和项目' : '未开通查阅'],
            ['照护工单', account.portalScopes.includes('careSchedule') ? '可查阅' : '未开通查阅'],
            ['医嘱与给药', account.portalScopes.includes('medication') ? '可查阅' : '未开通查阅'],
          ])
        : null,
      account.kind==='staff' ? facts([['岗位职责',account.staffDuties.join('、') || '待登记']]) : null,
      account.kind==='family' && boundPerson(account) && ctx.available('dossier') ? link(ctx,'查看绑定长者档案',()=>openDossier(ctx,boundPerson(account))) : null,
      capabilitySummary(ctx, account),
      grants,
    ]);
    const dialog = ctx.detail('权限详情', body);
    dialog.dataset.managedAccountId = account.id;
  }
  const management = page(
    ctx,
    '账号与权限',
    isOwner
      ? '管理机构账号、岗位授权及亲属绑定。'
      : '可管理员工的现有权限和新分配的权限均限于你的业务授权。',
    choose(
      state.accessManagement.canBindFamily
        ? btn(ctx, '绑定亲属或长者', () => editAccount(ctx, 'family'))
        : null,
      btn(ctx, '新增员工', () => editAccount(ctx, 'staff'), 'primary'),
    ),
    table(ctx, {
      title: isOwner ? '机构账号' : '可管理员工',
      rows: state.accounts,
      empty: '没有符合条件的账号',
      search: {
        placeholder: '搜索姓名、登录名、职责或绑定长者',
        value: (r) => [r.displayName, r.username, r.role, ...(r.staffDuties||[]), boundPerson(r)?.name].join(' '),
      },
      filter: {
        label: '账号筛选',
        all: '全部账号',
        options: [...(isOwner ? ['总管理员','员工','入住长者','亲属'] : []), '已启用', '已停用', '待激活'],
        matches: (r, key) => identityLabel(r) === key || (key==='待激活' && r.activationPending && r.enabled) || (r.enabled ? '已启用' : '已停用') === key,
      },
      cols: [
        { label: '姓名 / 登录名', view: (r) => named(staffLabel(ctx, r), r.username) },
        {
          label: '岗位',
          view: (r) =>
            node('div', 'access-account-roles', [
              node('span', r.kind === 'owner' ? 'access-role owner' : 'access-role', r.role),
              r.payday ? node('small', 'fx-muted', '工资日：每月 ' + r.payday + ' 日') : null,
              r.kind === 'staff' && r.permissions.includes('staff.manage')
                ? node('span', 'access-staff-manager', '受托管理')
                : null,
            ]),
        },
        {
          label: '工作分院',
          view: (row) =>
            row.kind === 'family'
              ? (boundPerson(row) ? residentAnchor(ctx, boundPerson(row)) : '随绑定长者')
              : (state.campusOptions || []).find((c) => c.id === row.facilityScope?.campusIds?.[0])?.name || '全机构',
        },
        {
          label: '工作台权限',
          view: (r) =>
            link(
              ctx,
              r.kind === 'owner'
                ? '全部权限'
                : r.kind === 'family'
                  ? '门户权限'
                  : r.permissions.length + ' 项授权',
              () => showPermissions(r),
            ),
        },
        {
          label: '状态',
          view: (r) => badge(ctx, !r.enabled ? '已停用' : r.activationPending ? '待激活':'已启用', r.enabled ? (r.activationPending?'amber':'green') : 'neutral'),
        },
        {
          label: '操作',
          align: 'end',
          view: (r) =>
            choose(
              r.kind === 'owner' ? null : link(ctx, '编辑', () => editAccount(ctx, r.kind, r)),
              r.kind === 'staff' ? link(ctx, '合同与工资日', () => openEmployment(ctx, r)) : null,

              r.kind === 'owner'
                ? null
                : link(ctx, r.enabled ? '停用' : '恢复', () => status(ctx, r)),
            ),
        },
      ],
    }),
    roleTemplates(ctx),
  );
  management.classList.add('access-management');
  return management;
}

function settings(ctx) {
  const visual = ctx.state.uiSettings,
    config = ctx.state.agentCapabilities?.plan || {};
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
    visual.theme,
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
    .filter((r) => !['overview', 'access', 'settings', 'family','rooms','intake','assistants'].includes(r))
    .map((r) => [r, routes.get(r)?.label || r]);
  const visible = checkboxes(
    routeChoices,
    routeChoices.map((x) => x[0]).filter((r) => !visual.hiddenRoutes.includes(r)),
  );
  appearance.append(
    node('h2', 'access-settings-heading', [icon('layers', 21), '机构界面']),
    preview,
    node('div', 'access-field-pair', [brandRow, orgRow]),
    themeRow,
    section('导航可见模块', visible.element),
  );
  saveForm(appearance, '保存界面设置', () =>
    ctx.command('access.settings', {
      brandName: brand.value,
      institutionName: org.value,
      theme: theme.value,
      hiddenRoutes: routeChoices.map((x) => x[0]).filter((r) => !visible.read().includes(r)),
    }),
  );
  const states = {
    available: '已开通',
    inactive: '未开通或已到期',
    exhausted: '本期额度已用完',
    unconfigured: '等待平台配置',
    no_scope: '岗位未授权',
  };
  const deep = node('section', 'access-settings access-provider', [
    node('h2', 'access-settings-heading', [icon('spark', 21), '平台 AI 套餐']),
    node('div', 'access-credential', [
      node('span', '', config.planName || '机构订阅'),
      node('strong', '', states[config.state] || '待配置'),
    ]),
    facts([
      ['服务模型', config.model || 'deepseek-flash'],
      ['本期额度', String(config.tokenLimit || 0) + ' tokens'],
      ['已用 / 预留', String(config.tokensUsed || 0) + ' / ' + String(config.tokensReserved || 0)],
      ['公开搜索', `已计费 ${config.webSearch?.calls || 0} 次，待核对 ${config.webSearch?.pending || 0} 次`],
      ['有效期至', config.expiresOn || '—'],
    ]),
    node('p', 'fx-muted', '云端规划按机构另购套餐启用。开通、续期与额度调整由平台运营方办理。'),
  ]);
  if (config.media) {
    const fields = {};
    const form = node('form', 'fx-profile');
    for (const [kind, title] of [['ocr', '医疗文书 OCR'], ['asr', '语音 ASR']]) {
      const meter = config.media[kind];
      const check = node('input');
      check.type = 'checkbox';
      check.checked = meter.enabled;
      fields[kind] = check;
      form.append(
        node('label', 'access-check', [check, title]),
        node('small', 'fx-muted', `已用 ${meter.used} / ${meter.limit} ${meter.unit}，在途 ${meter.held} ${meter.unit}`),
      );
    }
    saveForm(form, '保存识别开关', () =>
      ctx.command('access.mediaSettings', { ocr: fields.ocr.checked, asr: fields.asr.checked }),
    );
    deep.append(section('DeepSeek 识别工具', form));
  }
  const result = page(
    ctx,
    '机构设置',
    '管理界面、AI 套餐和机构数据备份。',
    null,
    tabs('settings', [
      ['general', '界面与 AI 套餐', () => node('div', 'access-settings-grid', [appearance, deep])],
      ['trials', '试住约定', () => trialSettings(ctx)],
      ['rounds', '定时巡查', () => roundsSettings(ctx)],
      ['backups', '备份与恢复', () => backupPanel(ctx)],
    ]),
  );
  result.classList.add('access-management');
  return result;
}

export function renderAccess(route, ctx) {
  if (route === 'settings')
    return ctx.state.user?.kind === 'owner'
      ? settings(ctx)
      : ctx.ui.empty('机构设置需要总管理员权限');
  return ctx.state.accessManagement ? accounts(ctx) : ctx.ui.empty('当前账号未获人员管理权限');
}
