import {
  node,
  add,
  page,
  table,
  choose,
  btn,
  link,
  facts,
  recordIdentity,
  disclosure,
  badge,
  section,
  named,
  records,
  today
} from './shared.js';

const basicFields = [
  ['birthDate', '出生日期', 'date'],
  ['birthplace', '出生地'],
  ['nativePlace', '籍贯'],
  ['address', '现居住址'],
  ['occupation', '原职业'],
  ['education', '文化程度'],
  ['language', '常用语言或方言'],
  ['maritalStatus', '婚姻情况']
];
const householdFields = [
  ['siblings', '兄弟姐妹及支持情况', 'textarea'],
  ['children', '子女及照护分工', 'textarea'],
  ['livingArrangement', '原居住与照料安排', 'textarea'],
  ['incomeSource', '收入与费用来源'],
  ['economicNotes', '经济情况补充', 'textarea']
];
const relativeFields = [
  ['name', '亲属姓名', 'text', true],
  ['relationship', '与长者关系', 'text', true],
  ['phone', '联系电话', 'tel', true],
  ['idNumber', '居民身份证号'],
  ['address', '联系地址'],
  ['wechat', '微信号'],
  ['email', '电子邮箱', 'email'],
  ['emergencyNote', '紧急联系说明', 'textarea']
];
const categories = [
  'CT',
  '其他影像检查',
  '诊断记录',
  '检验报告',
  '出院小结',
  '病史补录',
  '其他医疗文书'
];

function allowed(ctx, perm) {
  return ctx.state.user.kind === 'owner' || ctx.state.user.permissions.includes(perm);
}

function fields(schema, values) {
  return schema.map(([name, label, type = 'text', required = false]) => ({
    name,
    label,
    type,
    required,
    value: values[name] ?? ''
  }));
}

function displayed(schema, profile) {
  return schema.map(([name, label]) => [label, profile[name] ?? '']);
}

function editResident(ctx, resident, profile) {
  const schema = [
    ['name', '姓名', 'text', true],
    ['age', '登记年龄（出生日期未知时填写）', 'number'],
    ...basicFields
  ];
  if (allowed(ctx, 'relatives')) schema.push(...householdFields);
  const inputs = fields(schema, { ...resident, ...profile });
  inputs.find((f) => f.name === 'age').min = 0;
  inputs.find((f) => f.name === 'age').max = 125;
  inputs.find((f) => f.name === 'birthDate').max = today(ctx);
  ctx.dialog({
    title: '编辑长者登记资料',
    description: '姓名必填。已知出生日期时，系统按生日计算周岁。',
    fields: inputs,
    onSubmit: (values) => ctx.command('dossier.profile', { ...values, residentId: resident.id })
  });
}

function relativeForm(ctx, resident, accountId, profile) {
  const inputs = fields(relativeFields, profile);
  inputs.find((f) => f.name === 'idNumber').maxLength = 18;
  ctx.dialog({
    title: '完善亲属资料',
    description: '请核对姓名、与长者的关系和联系方式。身份证号、住址与微信可稍后补充。',
    fields: inputs,
    onSubmit: (values) =>
      ctx.command('dossier.relative', {
        ...values,
        residentId: resident.id,
        accountId
      })
  });
}

function myFamily(ctx) {
  const me = ctx.state.user;
  const resident = (ctx.state.residents || []).find((r) => r.id === me.residentId);
  if (!resident) return ctx.ui.empty('此账号尚未绑定有效长者，请联系机构。');
  const profile = (ctx.state.relativeProfiles || []).find((r) => r.accountId === me.id) || {};
  const body = node('article', 'fx-panel', [
    node('header', 'fx-toolbar', node('h2', '', '我的亲属资料')),
    node('div', 'fx-family-details', [
      section('身份与联系', facts(displayed(relativeFields.slice(0, 4), profile))),
      section('其他联系方式', facts(displayed(relativeFields.slice(4), profile)))
    ])
  ]);
  const services = me.familyServices ? table(ctx, {
    title: '最近完成的照护服务',
    rows: ctx.state.familyServiceHistory || [],
    search: { placeholder: '搜索服务项目', value: (r) => r.title },
    cols: [
      { label: '服务项目', view: (r) => r.title },
      { label: '完成日期', view: (r) => r.completedAt || '未登记' },
      { label: '计划日期', view: (r) => r.date },
      { label: '计划时间', view: (r) => r.time || '未登记' },
    ],
    empty: '目前没有已完成的照护服务。'
  }) : null;
  const identity = node('section', 'family-identity', [
    node('span', 'family-mark', ctx.ui.icon('people', 25)),
    node('div', '', [node('small', '', '绑定长者'), node('h2', '', resident.name)]),
    node('span', 'family-institution', [ctx.ui.icon('building', 15), ctx.state.uiSettings.institutionName])
  ]);
  return page(
    ctx,
    '家属服务',
    '',
    btn(ctx, '编辑本人资料', () => relativeForm(ctx, resident, me.id, profile), 'primary'),
    identity, services, body
  );
}

function label(caption, control, required = false) {
  control.required = required;
  return node('label', 'field', [node('span', '', caption + (required ? ' *' : '')), control]);
}

function options(items) {
  const select = node('select');
  items.forEach((value) => select.add(new Option(value, value)));
  return select;
}

function asBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('读取原图失败，请重新选择。'));
    reader.readAsDataURL(file);
  });
}

function newDocument(ctx, resident) {
  const form = node('form', 'fx-profile fx-document-form');
  const event = node('input');
  event.type = 'date';
  event.value = today(ctx);
  event.max = today(ctx);
  const kind = options(categories);
  const source = node('input');
  source.maxLength = 200;
  source.placeholder = '例如医院名称、科室或既往病历来源';
  const method = options(['手工描述', '人工核对的 OCR 转录']);
  const description = node('textarea');
  description.rows = 4;
  description.maxLength = 8000;
  description.placeholder = '摘录文书原有的检查所见、诊断或病史。';
  const pending = node('textarea');
  pending.rows = 2;
  pending.maxLength = 2000;
  pending.placeholder = '如字迹不清的日期、待补充的报告页';
  const pick = node('input');
  pick.type = 'file';
  pick.accept = 'image/jpeg,image/png';
  const camera = node('input');
  camera.type = 'file';
  camera.accept = 'image/jpeg,image/png';
  camera.setAttribute('capture', 'environment');
  const chosen = node('span', 'fx-muted', '支持 JPEG、PNG，每张最多 8 MiB。');
  [pick, camera].forEach((input, i) =>
    input.addEventListener('change', () => {
      if (input.files[0]) {
        [camera, pick][i].value = '';
        chosen.textContent =
          '已选择 ' +
          input.files[0].name +
          ' · ' +
          (input.files[0].size / 1024).toFixed(0) +
          ' KiB';
      }
    })
  );
  const err = node('div', 'form-error');
  err.setAttribute('role', 'alert');
  const submit = node('button', 'btn btn-primary', '确认原文并存档');
  submit.type = 'submit';
  const key =
    globalThis.crypto?.randomUUID?.() ||
    'record-' + Date.now() + '-' + Math.random().toString(36).slice(2);
  const group = (title, ...items) =>
    node('fieldset', 'fx-form-group', [node('legend', '', title), ...items]);
  form.append(
    group(
      '文书信息',
      label('文书发生日期', event, true),
      label('文书类型', kind, true),
      label('文书来源', source, true)
    ),
    group('留存原件', label('选择原件照片', pick), label('使用相机拍照', camera), chosen),
    group(
      '存档概括',
      label('文字来源', method, true),
      label('原文事实与描述', description, true),
      label('待核实事项', pending)
    ),
    node('p', 'fx-muted', '提交后保留原图与本次概括。仅手工病史补录可以省略照片。'),
    err,
    submit
  );
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (submit.disabled) return;
    submit.disabled = true;
    err.textContent = '';
    try {
      const file = pick.files[0] || camera.files[0];
      if (!file && (kind.value !== '病史补录' || method.value !== '手工描述'))
        throw new Error('请选择原件照片或拍照。');
      if (file && file.size > 8 * 1024 * 1024) throw new Error('照片超过 8 MiB 上限。');
      const payload = {
        residentId: resident.id,
        requestId: key,
        eventDate: event.value,
        category: kind.value,
        source: source.value,
        method: method.value,
        description: description.value,
        pending: pending.value
      };
      if (file) {
        payload.filename = file.name;
        if (file.type) payload.mime = file.type;
        payload.imageBase64 = await asBase64(file);
      }
      if (!(await ctx.command('dossier.document', payload)))
        err.textContent =
          document.querySelector('#announcer')?.textContent || '存档失败，请核对后重试。';
    } catch (error) {
      err.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  ctx.detail('为' + resident.name + '存档医疗文书', form);
}

function showDocument(ctx, doc) {
  const s = doc.summary;
  const view = node('article', 'fx-document fx-profile', [
    node('header', 'fx-document-head', [
      node('span', 'fx-initial', ctx.ui.icon('file', 21)),
      named(doc.category, doc.eventDate + ' · ' + s.source)
    ])
  ]);
  const sheet = node('div', 'fx-document-sheet');
  const transcription = node('div', 'fx-profile', [
    facts([
      ['文字来源', s.method],
      ['核对人员', s.reviewedBy],
      ['存档日期', doc.recordedDate]
    ]),
    section('原文事实与描述', node('p', '', s.sourceFacts)),
    section('待核实事项', node('p', '', s.pending))
  ]);
  sheet.append(transcription);
  view.append(sheet);
  if (doc.hasImage) {
    const image = node('img');
    image.src = '/api/documents/' + encodeURIComponent(doc.id) + '/image';
    image.alt = '归档原件 · ' + doc.category;
    image.loading = 'lazy';
    const original = node('a', 'btn btn-secondary', '打开原尺寸照片');
    original.href = image.src;
    original.target = '_blank';
    original.rel = 'noopener noreferrer';
    add(
      sheet,
      section(
        '文书原件',
        node('figure', 'fx-original', [
          image,
          node('figcaption', '', [
            named(doc.filename, (doc.bytes / 1024).toFixed(0) + ' KiB'),
            original
          ])
        ])
      )
    );
  }
  ctx.detail('文书概括', view);
}

function timeline(ctx, resident) {
  const rows = (ctx.state.medicalDocuments || []).filter((d) => d.residentId === resident.id);
  const panel = node('section', 'fx-timeline');
  const title = node('h3', '', [ctx.ui.icon('calendar', 18), '医疗记录时间线']);
  const count = node('span', 'fx-count');
  const year = node('select', 'fx-input');
  year.setAttribute('aria-label', '选择文书年份');
  year.add(new Option('全部年份', ''));
  for (const y of [...new Set(rows.map((r) => r.eventDate.slice(0, 4)))].sort().reverse())
    year.add(new Option(y + ' 年', y));
  const category = node('select', 'fx-input');
  category.setAttribute('aria-label', '选择文书类别');
  category.add(new Option('全部类型', ''));
  for (const cat of [...new Set(rows.map((r) => r.category))]) category.add(new Option(cat, cat));
  const input = node('input', 'fx-input');
  input.type = 'search';
  input.placeholder = '搜索日期、类型或来源';
  input.setAttribute('aria-label', input.placeholder);
  const items = node('div', 'fx-time-list');
  const refresh = () => {
    const needle = input.value.trim().toLocaleLowerCase();
    const selected = rows.filter(
      (r) =>
        (!year.value || r.eventDate.startsWith(year.value)) &&
        (!category.value || r.category === category.value) &&
        [r.eventDate, r.category, r.source].join(' ').toLocaleLowerCase().includes(needle)
    );
    count.textContent = selected.length + ' 份';
    items.replaceChildren();
    let current = '';
    for (const r of selected) {
      const y = r.eventDate.slice(0, 4);
      if (current !== y) {
        items.append(node('h4', 'fx-time-year', y + ' 年'));
        current = y;
      }
      const date = node('time', 'fx-time-date', r.eventDate.slice(5));
      date.dateTime = r.eventDate;
      items.append(
        node('article', 'fx-time-row', [
          date,
          node(
            'div',
            'fx-time-entry',
            named(r.category, [r.source, r.recordedDate + ' 存档'].filter(Boolean).join(' · '))
          ),
          link(ctx, '查看概括', () => showDocument(ctx, r))
        ])
      );
    }
    if (!selected.length)
      items.append(node('p', 'fx-empty', rows.length ? '没有匹配的文书' : '尚无医疗文书'));
  };
  input.addEventListener('input', refresh);
  for (const picker of [year, category]) picker.addEventListener('change', refresh);
  const tools = node('div', 'fx-table-tools', [
    node('label', 'fx-table-search', [ctx.ui.icon('search', 15), input]),
    year,
    category
  ]);
  panel.append(node('header', 'fx-timeline-head', [title, count]), tools, items);
  refresh();
  return panel;
}

function showKin(ctx, resident) {
  const profiles = (ctx.state.relativeProfiles || []).filter((p) => p.residentId === resident.id);
  const list = node(
    'div',
    'fx-profile',
    records(
      profiles,
      (p) =>
        node('div', 'fx-profile', [
          named(p.name, p.relationship),
          facts(displayed(relativeFields.slice(2), p))
        ]),
      '尚无亲属提交资料。'
    )
  );
  if (ctx.state.user.kind === 'owner') {
    const accounts = (ctx.state.accounts || []).filter(
      (a) => a.kind === 'family' && a.enabled && a.residentId === resident.id
    );
    for (const a of accounts) {
      list.append(
        btn(ctx, '代录 ' + a.displayName + ' 的资料', () =>
          relativeForm(ctx, resident, a.id, profiles.find((p) => p.accountId === a.id) || {})
        )
      );
    }
  }
  return disclosure('亲属登记', list, profiles.length);
}

export function openDossier(ctx, resident) {
  const profile = (ctx.state.dossierProfiles || []).find((p) => p.residentId === resident.id) || {};
  const actions = choose();
  const side = node('div', 'fx-dossier-demographic fx-profile');
  const contents = node('div', 'fx-dossier-main fx-profile');
  const grid = node('div', 'fx-dossier-grid', [side, contents]);
  const body = node('div', 'fx-profile fx-dossier', [
    node('header', 'fx-dossier-head', [recordIdentity(ctx, resident, resident.level), actions]),
    grid
  ]);
  if (allowed(ctx, 'intake'))
    actions.append(btn(ctx, '编辑登记资料', () => editResident(ctx, resident, profile)));
  if (allowed(ctx, 'medical.write'))
    actions.append(btn(ctx, '存档医疗文书', () => newDocument(ctx, resident), 'primary'));
  if (allowed(ctx, 'medical')) contents.append(timeline(ctx, resident));
  if (allowed(ctx, 'residents') || allowed(ctx, 'intake'))
    side.append(
      section(
        '基本资料',
        facts([
          ['姓名', resident.name],
          ['年龄', resident.age == null ? '' : resident.age + ' 岁'],
          ...displayed(basicFields, profile)
        ])
      )
    );
  if (allowed(ctx, 'relatives'))
    side.append(
      disclosure('家庭与经济情况', facts(displayed(householdFields, profile))),
      showKin(ctx, resident)
    );
  if (allowed(ctx, 'clinical') || allowed(ctx, 'medical')) {
    const updates = (ctx.state.archives || [])
      .filter((r) => r.residentId === resident.id)
      .reverse();
    if (updates.length)
      contents.append(
        disclosure(
          '护理复核与历史摘要',
          records(updates, (r) =>
            named(
              r.summary,
              [r.source || '档案摘要复核', r.observedAt || r.date, r.room, r.reviewer]
                .filter(Boolean)
                .join(' · ')
            )
          ),
          updates.length
        )
      );
  }
  if (!side.childElementCount) side.remove();
  if (!contents.childElementCount) contents.remove();
  ctx.detail('长者详细档案', body);
}

export function renderDossier(route, ctx) {
  if (route === 'family') return myFamily(ctx);
  return page(
    ctx,
    '个人与医疗档案',
    '查阅长者的登记资料、亲属联系方式和按日期归档的医疗记录。',
    null,
    table(ctx, {
      title: '长者名册',
      rows: ctx.state.residents || [],
      search: {
        placeholder: '搜索姓名或档案号',
        value: (r) => r.name + ' ' + r.id
      },
      cols: [
        {
          label: '长者',
          view: (r) =>
            node('div', 'fx-person-cell', [
              node('span', 'fx-person-mark', ctx.ui.icon('people', 16)),
              named(r.name, r.id)
            ])
        },
        {
          label: '入住状态',
          view: (r) => (r.status ? badge(ctx, r.status) : '—')
        },
        {
          label: '操作',
          view: (r) => link(ctx, '打开详细档案', () => openDossier(ctx, r))
        }
      ]
    })
  );
}
