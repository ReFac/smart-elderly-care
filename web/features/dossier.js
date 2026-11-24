import { residentInsights } from './resident-insights.js';
import { billDetail } from './billing.js';
import { editResident } from './profile-editor.js';
import { displayAmount, loadProfileChoices, regionPicker } from './profile-controls.js';
import { contactBook } from './family-contacts.js';
import { familyInbox, familyRecipients } from './family-rounds.js';
import { careTimeline, scopedHistoryButton } from './care-timeline.js';
import { previewSummary } from './dossier-summary.js';
import { originalViewer } from './document-original.js';
import { pendingDocument, recognizeDocument, reviewReceipt } from './document-ocr.js';
import {
  node,
  add,
  page,
  table,
  tabs,
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
  ['phone', '长者本人手机号'],
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

async function relativeForm(ctx, resident, accountId, profile) {
  let catalog;
  try { catalog = await loadProfileChoices(); } catch(e) {ctx.toast(e.message);return;}
  const location = regionPicker(catalog.regions,'联系地址',profile.addressRegion,profile.address);
  const inputs = fields(relativeFields.filter(([key])=>key!=='address'), profile);
  const relation = inputs.find(f=>f.name==='relationship');
  relation.type='select';
  relation.options=['',...new Set([...catalog.choices.relationship,...(profile.relationship?[profile.relationship]:[])])];
  inputs.find((f) => f.name === 'idNumber').maxLength = 18;
  ctx.dialog({
    title: '完善亲属资料',
    content:location.element,
    description: '请核对姓名、与长者的关系和联系方式。身份证号、住址与微信可稍后补充。',
    fields: inputs,
    onSubmit: (values) =>
      ctx.command('dossier.relative', {
        ...values,
        ...(location.read()===undefined?{}:{addressRegion:location.read()}),
        residentId: resident.id,
        accountId
      })
  });
}

function portalTable(ctx, scope, config) {
  const total = ctx.state.portalTotals[scope];
  if (total <= config.rows.length) return table(ctx, config);
  const root = node('div', 'fx-profile');
  async function load(offset) {
    if (!root.isConnected) return;
    try {
      const next = await ctx.get(
        '/api/portal/history/' + scope + '?offset=' + offset + '&revision=' + ctx.state.revision
      );
      if (root.isConnected) render(next.rows, next.offset);
    } catch (error) {
      ctx.toast(error.message);
    }
  }
  function render(rows, offset) {
    const actions = choose(
      offset ? btn(ctx, '上一组', () => load(Math.max(0, offset - 30))) : null,
      node('span', 'fx-muted', offset + 1 + '–' + (offset + rows.length) + ' / ' + total),
      offset + rows.length < total ? btn(ctx, '更早记录', () => load(offset + rows.length)) : null
    );
    root.replaceChildren(table(ctx, { ...config, rows, action: actions }));
  }
  render(config.rows, 0);
  return root;
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
  const services = me.familyServices
    ? table(ctx, {
        title: '最近完成的照护服务',
        rows: ctx.state.familyServiceHistory || [],
        search: { placeholder: '搜索服务项目', value: (r) => r.title },
        cols: [
          { label: '服务项目', view: (r) => r.title },
          { label: '完成日期', view: (r) => r.completedAt || '未登记' },
          { label: '计划日期', view: (r) => r.date },
          { label: '计划时间', view: (r) => r.time || '未登记' }
        ],
        empty: '目前没有已完成的照护服务。'
      })
    : null;
  const identity = node('section', 'family-identity', [
    node('span', 'family-mark', ctx.ui.icon('people', 25)),
    node('div', '', [
      node('small', '', me.portalSelf ? '我的入住档案' : '绑定长者'),
      node('h2', '', resident.name)
    ]),
    node('span', 'family-institution', [
      ctx.ui.icon('building', 15),
      ctx.state.uiSettings.institutionName
    ])
  ]);
  const panels = [];
  if (services) panels.push(['completed', '已完成服务', () => services]);
  if (ctx.state.portalTasks)
    panels.push([
      'tasks',
      '照护工单进度',
      () =>
        portalTable(ctx, 'careSchedule', {
          title: '照护工单进度',
          rows: ctx.state.portalTasks,
          cols: [
            { label: '服务项目', view: (r) => r.title },
            { label: '计划时间', view: (r) => [r.date, r.time].filter(Boolean).join(' ') },
            { label: '状态', view: (r) => r.status },
            { label: '完成日期', view: (r) => r.completedAt || '—' },
            {
              label: '服务评价',
              view: (r) =>
                r.rating
                  ? r.rating + ' 分'
                  : r.status === '已完成'
                    ? link(ctx, '评价', () =>
                        ctx.dialog({
                          title: '评价本次服务',
                          description: r.title,
                          fields: [
                            {
                              name: 'rating',
                              label: '满意度（1 至 5 分）',
                              type: 'number',
                              min: 1,
                              max: 5,
                              required: true
                            },
                            {
                              name: 'note',
                              label: '评价意见',
                              type: 'textarea',
                              maxLength: 500,
                              required: false
                            }
                          ],
                          onSubmit: (v) =>
                            ctx.command('portal.feedback', {
                              taskId: r.id,
                              rating: Number(v.rating),
                              note: v.note
                            })
                        })
                      )
                    : '—'
            }
          ],
          empty: '暂无照护工单。'
        })
    ]);
  if (ctx.state.portalMedication)
    panels.push([
      'medication',
      '医嘱与给药记录',
      () =>
        portalTable(ctx, 'medication', {
          title: '医嘱与给药记录',
          rows: ctx.state.portalMedication,
          cols: [
            { label: '药品', view: (r) => r.name },
            { label: '已复核医嘱', view: (r) => r.instruction },
            { label: '计划时间', view: (r) => r.scheduledAt?.replace('T', ' ') || '未登记' },
            { label: '状态', view: (r) => r.status },
            {
              label: '实际执行',
              view: (r) => (r.executedTime || r.executedAt || '—').replace('T', ' ')
            }
          ],
          empty: '暂无已复核的医嘱。'
        })
    ]);
  if (ctx.state.familyRoundInbox) {
    const unread = ctx.state.familyRoundInbox.messages.filter((m) => !m.readAt).length;
    panels.push(['briefs', unread ? '巡查简报 · ' + unread + ' 未读' : '巡查简报', () => familyInbox(ctx, resident)]);
  }
  if (me.portalSelf && ctx.state.familyRoundRecipients)
    panels.push(['sharing', '分享授权', () => familyRecipients(ctx, resident)]);
  if (!me.portalSelf) panels.push(['relative', '我的亲属资料', () => body]);
  const content =
    panels.length > 1
      ? tabs('family', panels)
      : panels.length
        ? panels.map(([, , render]) => render())
        : ctx.ui.empty('目前没有开通服务记录查阅，可在环境导览中参观院区。');
  return page(
    ctx,
    me.portalSelf ? '长者服务' : '家属服务',
    '',
    me.portalSelf
      ? null
      : btn(ctx, '编辑本人资料', () => relativeForm(ctx, resident, me.id, profile), 'primary'),
    identity,
    content
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

export function asBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('读取原件失败，请重新选择。'));
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
  const inpatient=resident.status==='在住';
  const method = options(inpatient ? ['手工描述','DeepSeek OCR','人工核对的 OCR 转录'] : ['手工描述']);
  const consent = node('input');
  consent.type = 'checkbox';
  const consentField = node('label', 'access-check', [
    consent,
    '同意将本次原件发送至 DeepSeek 识别，使用机构 OCR 页数额度。'
  ]);
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
  pick.accept = 'image/jpeg,image/png,application/pdf,.pdf';
  const camera = node('input');
  camera.type = 'file';
  camera.accept = 'image/jpeg,image/png';
  camera.setAttribute('capture', 'environment');
  const chosen = node('span', 'fx-muted', '支持 PDF、JPEG 和 PNG，每份最多 8 MiB。');
  chosen.setAttribute('aria-live', 'polite');
  let inspected = null, inspection;
  const isPdf = (file) => file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
  async function inspect(file) {
    inspection?.abort();
    inspection = new AbortController();
    inspected = null;
    if (!file) { chosen.textContent = '请选择 PDF 或原件照片。'; return; }
    if (!file.size || file.size > 8 * 1024 * 1024) {
      chosen.textContent = '请选择 8 MiB 以内的非空原件。';
      return;
    }
    const signal = inspection.signal;
    try {
      let pages = 1;
      if (isPdf(file)) {
        chosen.textContent = '正在本机核对 PDF 页数…';
        const res = await fetch('/api/residents/' + encodeURIComponent(resident.id) + '/document-pages', {
          method: 'POST', headers: { 'Content-Type': 'application/pdf' }, body: file, signal,
        });
        const info = await res.json();
        if (!res.ok) throw Error(info.error || '无法核实 PDF 页数');
        pages = info.pageCount;
      }
      if (!signal.aborted) { inspected = { file, pages }; updateMethod(); }
    } catch (error) {
      if (!signal.aborted) chosen.textContent = error.message;
    }
  }
  [pick, camera].forEach((input, i) => input.addEventListener('change', () => {
    if (input.files[0]) [camera, pick][i].value = '';
    inspect(pick.files[0] || camera.files[0]);
  }));
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
    group('留存原件', label('选择 PDF 或原件照片', pick), label('使用相机拍照', camera), chosen),
    group(
      '存档概括',
      label('文字来源', method, true),
      consentField,
      label('原文事实与描述', description, true),
      label('待核实事项', pending)
    ),
    node('p', 'fx-muted', '提交后保留原件与本次概括。手工补录病史时可省略原件。'),
    err,
    submit
  );
  const updateMethod = () => {
    const local = method.value === 'DeepSeek OCR';
    for (const field of [description, pending]) {
      field.disabled = local;
      field.closest('label').hidden = local;
    }
    consentField.hidden = !local;
    consent.required = local;
    if (inspected) chosen.textContent = inspected.file.name + ' · ' + inspected.pages + ' 页'
      + (local ? ' · 预计使用 ' + inspected.pages + ' 页 OCR 额度' : '');
    submit.textContent = local ? '留存原件并提交 DeepSeek OCR' : '确认原文并存档';
  };
  updateMethod();
  method.addEventListener('change', updateMethod);
  kind.addEventListener('change', () => {
    if (kind.value === '出院小结' && inpatient) method.value = 'DeepSeek OCR';
    if (kind.value === '病史补录') method.value = '手工描述';
    updateMethod();
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (submit.disabled) return;
    submit.disabled = true;
    err.textContent = '';
    try {
      const file = pick.files[0] || camera.files[0];
      if (!file && (kind.value !== '病史补录' || method.value !== '手工描述'))
        throw new Error('请选择 PDF、原件照片或拍照。');
      if (file && inspected?.file !== file) throw new Error('请先完成原件页数核对。');
      const pages = inspected?.pages;
      const payload = {
        residentId: resident.id,
        requestId: key,
        eventDate: event.value,
        category: kind.value,
        source: source.value,
        method: method.value,
        description: description.disabled ? '' : description.value,
        pending: pending.disabled ? '' : pending.value
      };
      if (file) {
        payload.filename = file.name;
        if (isPdf(file)) payload.mime = 'application/pdf';
        else if (file.type) payload.mime = file.type;
        payload.imageBase64 = await asBase64(file);
      }
      const imageHash =
        file && method.value === 'DeepSeek OCR'
          ? Array.from(
              new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())),
              (x) => x.toString(16).padStart(2, '0')
            ).join('')
          : '';
      const archived = await ctx.command('dossier.document', payload, {
        title: imageHash ? '存档并提交 DeepSeek OCR' : '存档医疗文书',
        target: resident.name,
        fields: [
          ['文书', kind.value],
          ['日期', event.value],
          ['原件', file?.name || '手工补录'],
          ['来源', source.value],
          [
            '处理方式',
            imageHash ? '先加密保留完整原件，再发送至 DeepSeek 识别，预计使用 ' + pages + ' 页 OCR 额度。' : description.value,
          ],
        ],
        quiet: Boolean(imageHash),
      });
      if (archived === false)
        err.textContent =
          document.querySelector('#announcer')?.textContent || '存档失败，请核对后重试。';
      else if (archived && imageHash)
        await recognizeDocument(ctx, resident.id, { imageHash }, true);
    } catch (error) {
      err.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  ctx.detail('为' + resident.name + '存档医疗文书', form).addEventListener('close', () => inspection?.abort(), { once: true });
}

function showDocument(ctx, doc) {
  if (!doc.summary && doc.ocr) return pendingDocument(ctx, doc);
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
  if (doc.reviewChanges && Object.keys(doc.reviewChanges).length)
    transcription.append(reviewReceipt(doc));
  view.append(sheet);
  if (doc.hasImage) add(sheet, section('文书原件', originalViewer(doc).element));
  if (doc.reviewedPages?.length) add(transcription, facts([['逐页核对', '已核对全部 ' + doc.reviewedPages.length + ' 页']]));
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
          link(ctx, r.summary ? '查看概括' : '查看待核对原件', () => showDocument(ctx, r))
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

function showKin(ctx, resident, readOnly=false) {
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
  if (!readOnly && ctx.state.user.kind === 'owner') {
    const accounts = (ctx.state.accounts || []).filter(
      (a) => a.kind === 'family' && !a.portalSelf && a.enabled && a.residentId === resident.id
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
  const archived = ['已退住','归档','已归档','已出院'].includes(resident.status);
  const actions = choose();
  const side = node('div', 'fx-dossier-demographic fx-profile');
  const contents = node('div', 'fx-dossier-main fx-profile');
  const grid = node('div', 'fx-dossier-grid', [side, contents]);
  const body = node('div', 'fx-profile fx-dossier', [
    node('header', 'fx-dossier-head', [recordIdentity(ctx, resident, resident.level), actions]),
    grid
  ]);
  if (!archived && allowed(ctx, 'intake'))
    actions.append(btn(ctx, '编辑登记资料', () => editResident(ctx, resident, profile)));
  if (!archived && allowed(ctx, 'medical.write'))
    actions.append(btn(ctx, '存档医疗文书', () => newDocument(ctx, resident), 'primary'));
  if (resident.status==='在住' && ctx.state.allowedActions.includes('dossier.signSummary'))
    actions.append(btn(ctx, '核对动态档案摘要', () => previewSummary(ctx, resident, showDocument)));
  const recentChanges = scopedHistoryButton(ctx, 'resident', resident.id);
  if (recentChanges) actions.append(recentChanges);
  if (!archived && allowed(ctx, 'care')) contents.append(careTimeline(ctx, 'resident', resident.id));
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
      disclosure('家庭情况', facts(displayed(householdFields, profile))),
      disclosure('费用来源', facts([['费用来源', profile.fundingSources?.join('、')], ...(profile.incomeSource ? [['旧版登记原文',profile.incomeSource]] : [])])),
      disclosure('长者养老金收入', facts([['每月收入',displayAmount(profile.pensionBand,profile.pensionAmount)]])),
      showKin(ctx, resident, archived)
    );
  if (allowed(ctx,'finance')) {
    const bills=(ctx.state.bills||[]).filter(b=>b.residentId===resident.id).sort((a,b)=>b.month.localeCompare(a.month));
    side.append(disclosure('收费', node('div','fx-profile',[records(bills,b=>node('div','fx-profile',[named(b.month+' · '+b.status,'应收 '+b.amount+' 元 · 已收 '+b.paid+' 元 · 待缴 '+b.balance+' 元'),btn(ctx,'查看本期收费明细',()=>billDetail(ctx,b),'ghost')]),'暂无已出账单')]), bills.length));
  }
  if (allowed(ctx, 'clinical') || allowed(ctx, 'medical')) {
    if (resident.summary)
      contents.prepend(section('当前档案摘要', node('p', '', resident.summary)));
    if (resident.allergies || resident.risk) {
      const values = [
        ['已登记过敏史', resident.allergies],
        ['高危要点', resident.risk]
      ];
      const rows = node('div', 'fx-profile');
      for (const [label, value] of values.filter((entry) => entry[1]))
        rows.append(node('div', '', [badge(ctx, label, 'amber'), ' ' + value]));
      contents.prepend(section('过敏与高危提示', rows));
    }
    const updates = (ctx.state.archives || [])
      .filter((r) => r.residentId === resident.id)
      .reverse();
    if (updates.length)
      contents.append(
        disclosure(
          '护理复核与历史摘要',
          records(updates, (r) =>
            r.evidence
              ? disclosure(
                  r.source + ' · ' + r.date,
                  node('div', 'fx-profile', [
                    named(r.summary, r.reviewer),
                    facts(r.evidence.map((e) => [e.label, e.value]))
                  ]),
                  r.evidence.length
                )
              : named(
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
  if (allowed(ctx, 'relatives')) contents.append(contactBook(ctx, resident, profile, archived));
  if (!archived && ctx.state.familyRoundRecipients) contents.append(familyRecipients(ctx, resident));
  if (resident.status==='在住' && (allowed(ctx, 'care') || allowed(ctx, 'clinical'))) contents.prepend(residentInsights(ctx, resident.id));
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
