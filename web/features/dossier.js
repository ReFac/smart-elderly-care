import { residentLabel, staffLabel } from './people-labels.js';
import { clearFileSelection, fileControl } from '../lib/file-control.js';
import { residentInsights } from './resident-insights.js';
import { healthProfile } from './resident-health.js';
import { residentEvaluations } from './resident-evaluations.js';
import { renderMedicationReports } from './medication-reports.js';
import { dailyTimeline } from './daily-timeline.js';
import { billDetail } from './billing.js';
import { familyPortal } from './family-portal.js';
import { editResident } from './profile-editor.js';
import { credentialList, residentRoster } from './resident-roster.js';
import { register } from './admission.js';
import { openPermissionRequest } from './permission-requests.js';
import { displayAmount, loadProfileChoices, regionPicker } from './profile-controls.js';
import { contactBook } from './family-contacts.js';
import { familyRecipients } from './family-rounds.js';
import { careTimeline } from './care-timeline.js';
import { recentChanges } from './recent-changes.js';
import { previewSummary } from './dossier-summary.js';
import { asBase64, originalViewer } from './document-original.js';
import { pendingDocument, recognizeDocument, reviewReceipt } from './document-ocr.js';
import { openVisitEditor } from './medical-visit-intake.js';
import { showVisit, visitHistory, visitsFor } from './medical-visit-review.js';
import { residencyDetails } from './residency.js';
import {
  node,
  add,
  choose,
  btn,
  link,
  facts,
  recordIdentity,
  hasGrant,
  canAct,
  disclosure,
  badge,
  section,
  named,
  records,
  today
} from './shared.js';

const basicFields = [
  ['phone', '长辈本人手机号'],
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
  ['relationship', '与长辈关系', 'text', true],
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
    description: '请核对姓名、与长辈的关系和联系方式。身份证号、住址与微信可稍后补充。',
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

function label(caption, control, required = false) {
  control.required = required;
  const field = control.type === 'file'
    ? fileControl(control, { action: control.hasAttribute('capture') ? '拍摄照片' : '选择文件' })
    : control;
  return node('label', 'field', [node('span', '', caption + (required ? ' *' : '')), field]);
}

function options(items) {
  const select = node('select');
  items.forEach((value) => select.add(new Option(value, value)));
  return select;
}

export { asBase64 };

function newDocument(ctx, resident, visit, reopenVisit) {
  const form = node('form', 'fx-profile fx-document-form');
  const event = node('input');
  event.type = 'date';
  event.value = visit.fields.eventDate;
  event.max = today(ctx);
  const kind = options(categories);
  const source = node('input');
  source.maxLength = 200;
  source.placeholder = '例如医院名称、科室或既往病历来源';
  source.value = visit.fields.facility || '';
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
    if (input.files[0]) clearFileSelection([camera, pick][i]);
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
    facts([['归入就诊记录', [visit.fields.eventDate, visit.fields.facility, visit.fields.department]
      .filter(Boolean).join(' · ')]]),
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
        visitId: visit.id,
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
        target: residentLabel(ctx, resident),
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
      else if (archived) {
        if (imageHash)
          await recognizeDocument(ctx, resident.id, { imageHash }, true, reopenVisit);
        else
          reopenVisit?.();
      }
    } catch (error) {
      err.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  ctx.detail('补充本次就诊的医疗文书', form).addEventListener('close', () => inspection?.abort(), { once: true });
}

function showDocument(ctx, doc, reopenVisit) {
  if (!doc.summary && doc.ocr) return pendingDocument(ctx, doc, reopenVisit);
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
      ['核对人员', staffLabel(ctx, s.reviewedBy, s.reviewerId)],
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

function registrationDetails(ctx, resident, profile, archived, stay) {
  const content = node('div', 'fx-profile');
  const actions = choose();
  if (allowed(ctx, 'intake') || allowed(ctx, 'finance'))
    content.append(btn(ctx, '证件资料', () => credentialList(ctx, resident)));
  if (!archived && (allowed(ctx, 'intake') || canAct(ctx, 'permissionRequest.create'))) {
    actions.append(allowed(ctx, 'intake')
      ? btn(ctx, '编辑登记资料', () => editResident(ctx, resident, profile), 'primary')
      : btn(ctx, '申请编辑权限', () => openPermissionRequest(ctx, resident)));
    content.append(node('div', 'resident-dossier-actions', actions));
  }
  if (allowed(ctx, 'residents') || allowed(ctx, 'intake'))
    content.append(
      section(
        '基本资料',
        facts([
          ['姓名', residentLabel(ctx, resident)],
          ['年龄', resident.age == null ? '' : resident.age + ' 岁'],
          ['性别', resident.gender],
          ...displayed(basicFields, profile)
        ])
      )
    );
  add(content, stay.enrollment);
  if (allowed(ctx, 'relatives'))
    content.append(
      contactBook(ctx, resident, profile, archived),
      disclosure('家庭情况', facts(displayed(householdFields, profile))),
      disclosure('费用来源', facts([['费用来源', profile.fundingSources?.join('、')], ...(profile.incomeSource ? [['旧版登记原文',profile.incomeSource]] : [])])),
      disclosure('长辈养老金收入', facts([['每月收入',displayAmount(profile.pensionBand,profile.pensionAmount)]])),
      showKin(ctx, resident, archived)
    );
  if (allowed(ctx,'finance')) {
    const bills=(ctx.state.bills||[]).filter(b=>b.residentId===resident.id).sort((a,b)=>b.month.localeCompare(a.month));
    content.append(disclosure('收费', records(bills, bill => node('div', 'resident-dossier-invoice', [
      named(
        [bill.billingDate || bill.month, {monthly: '月费', security: '入住押金', trial: '试住费'}[bill.kind], bill.status].filter(Boolean).join(' · '),
        '应收 ' + bill.amount + ' 元 · 已收 ' + bill.paid + ' 元 · 待缴 ' + bill.balance + ' 元'
      ),
      btn(ctx, '查看本期收费明细', () => billDetail(ctx, bill), 'ghost'),
    ]), '暂无已出账单'), bills.length));
  }
  if (!archived && ctx.state.familyRoundRecipients) add(content, familyRecipients(ctx, resident));
  return content;
}

function medicalDetails(ctx, resident, archived, stay) {
  const content = node('div', 'fx-profile');
  add(content, residentEvaluations(ctx, resident.id));
  const reopen = live => {
    const current = live.state.residents.find(row => row.id === resident.id);
    if (!current) return;
    const existing = [...document.querySelectorAll('.resident-dossier-dialog[open], .resident-record-workspace')].find(
      dialog => dialog.dataset.roundsResidentId === resident.id
    );
    if (existing) existing.querySelector('[data-dossier-tab="medical"]')?.click();
    else openDossier(live, current, undefined, 'medical');
  };
  if (allowed(ctx, 'medical')) {
    content.append(visitHistory(ctx, resident, archived ? null : openVisitEditor, {
      open: showDocument,
      add: !archived ? newDocument : null,
      reopen,
    }));
  }
  if (resident.status === '在住' && ctx.state.allowedActions.includes('dossier.signSummary'))
    content.append(node('div', 'resident-dossier-actions',
      btn(ctx, '核对动态档案摘要', () => previewSummary(ctx, resident, showDocument))));
  if (allowed(ctx, 'clinical') || allowed(ctx, 'medical')) {
    if (resident.summary)
      content.append(section('当前档案摘要', node('p', '', resident.summary)));
    if (resident.allergies || resident.risk) {
      const values = [
        ['已登记过敏史', resident.allergies],
        ['高危要点', resident.risk]
      ];
      const rows = node('div', 'fx-profile');
      for (const [label, value] of values.filter((entry) => entry[1]))
        rows.append(node('div', '', [badge(ctx, label, 'amber'), ' ' + value]));
      content.append(section('过敏与高危提示', rows));
    }
    const updates = (ctx.state.archives || [])
      .filter((r) => r.residentId === resident.id)
      .reverse();
    if (updates.length)
      content.append(
        disclosure(
          '护理复核与历史摘要',
          records(updates, (r) =>
            r.evidence
              ? disclosure(
                  r.source + ' · ' + r.date,
                  node('div', 'fx-profile', [
                    named(r.summary, staffLabel(ctx, r.reviewer)),
                    facts(r.evidence.map((e) => [e.label, e.value]))
                  ]),
                  r.evidence.length
                )
              : named(
                  r.summary,
                  [r.source || '档案摘要复核', r.observedAt || r.date, r.room, staffLabel(ctx, r.reviewer)]
                    .filter(Boolean)
                    .join(' · ')
                )
          ),
          updates.length
        )
      );
  }
  if (resident.status !== '归档到期' && hasGrant(ctx, 'care', 'clinical', 'medical'))
    content.append(healthProfile(ctx, resident), renderMedicationReports(ctx, resident.id));
  add(content, stay.clinical);
  return content;
}

function wellnessTimeline(ctx, resident, archived, stay, lifeEvent) {
  const content = node('div', 'fx-profile');
  if (resident.status !== '归档到期' && hasGrant(ctx, 'care', 'clinical', 'care.groupConfirm', 'residents', 'medical'))
    content.append(dailyTimeline(ctx, resident, lifeEvent));
  if (resident.status === '在住' && hasGrant(ctx, 'care', 'clinical'))
    content.append(residentInsights(ctx, resident.id));
  if (!archived && allowed(ctx, 'care'))
    content.append(careTimeline(ctx, 'resident', resident.id));
  add(content, stay.history);
  return content;
}

let nextDossierPanel = 0;

function dossierViews(ctx, views, requested) {
  const key = 'resident-dossier-' + ++nextDossierPanel;
  const nav = node('div', 'resident-dossier-nav');
  nav.setAttribute('role', 'tablist');
  nav.setAttribute('aria-label', '长辈详细档案栏目');
  nav.setAttribute('aria-orientation', 'vertical');
  const contents = node('div', 'resident-dossier-content');
  const entries = views.map(([id, title, icon, render]) => {
    const button = node('button', '', [ctx.ui.icon(icon, 18), node('span', '', title)]);
    button.type = 'button';
    button.id = key + '-tab-' + id;
    button.dataset.dossierTab = id;
    const panel = node('div', 'resident-dossier-panel');
    panel.id = key + '-panel-' + id;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', panel.id);
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', button.id);
    panel.tabIndex = 0;
    nav.append(button);
    contents.append(panel);
    return { id, button, panel, render };
  });
  function show(selected) {
    for (const entry of entries) {
      const active = entry === selected;
      entry.button.tabIndex = active ? 0 : -1;
      entry.button.setAttribute('aria-selected', String(active));
      entry.panel.hidden = !active;
    }
    if (!selected.panel.firstElementChild) selected.panel.append(selected.render());
    selected.panel.scrollTop = 0;
    contents.closest('dialog')?.scrollTo({top: 0});
    selected.button.dispatchEvent(new CustomEvent('dossier-section', {bubbles:true, detail:selected.id}));
  }
  for (const [index, entry] of entries.entries()) {
    entry.button.addEventListener('click', () => show(entry));
    entry.button.addEventListener('keydown', event => {
      const target = {
        ArrowUp: (index - 1 + entries.length) % entries.length,
        ArrowDown: (index + 1) % entries.length,
        Home: 0,
        End: entries.length - 1,
      }[event.key];
      if (target == null) return;
      event.preventDefault();
      show(entries[target]);
      entries[target].button.focus();
    });
  }
  show(entries.find(entry => entry.id === requested) || entries[0]);
  return node('div', 'resident-dossier-grid', [nav, contents]);
}

function dossierSections(ctx, resident, lifeEvent, initialSection) {
  const profile = (ctx.state.dossierProfiles || []).find((p) => p.residentId === resident.id) || {};
  const archived = ['已退住', '归档', '已归档', '已出院', '归档到期'].includes(resident.status);
  const stay = residencyDetails(ctx, resident);
  const views = [];
  if (stay.enrollment || hasGrant(ctx, 'residents', 'intake', 'relatives', 'finance') ||
      ctx.state.familyRoundRecipients || (!archived && canAct(ctx, 'permissionRequest.create')))
    views.push(['registration', '登记资料', 'file', () => registrationDetails(ctx, resident, profile, archived, stay)]);
  if (hasGrant(ctx, 'care', 'clinical', 'medical') || !archived && allowed(ctx, 'medical.write'))
    views.push(['medical', '医疗资料', 'heart', () => medicalDetails(ctx, resident, archived, stay)]);
  if (stay.history || resident.status !== '归档到期' && hasGrant(ctx, 'care', 'clinical', 'care.groupConfirm', 'residents', 'medical'))
    views.push(['timeline', '疗养院时间线', 'calendar', () => wellnessTimeline(ctx, resident, archived, stay, lifeEvent)]);
  return views.length
    ? dossierViews(ctx, views, initialSection)
    : node('p', 'fx-muted', '当前岗位没有可查阅的详细资料。');
}

function dossierContent(ctx, resident, lifeEvent, initialSection) {
  const sections = node('div', '', dossierSections(ctx, resident, lifeEvent, initialSection || (lifeEvent ? 'timeline' : undefined)));
  const history = node('section', 'resident-dossier-history');
  history.id = 'resident-dossier-' + ++nextDossierPanel + '-history';
  history.hidden = true;
  const identity = recordIdentity(ctx, resident, resident.level);
  const toggle = ctx.available('history') && ctx.state.user.kind !== 'family'
    ? btn(ctx, '最近改动', () => {
      const open = history.hidden;
      history.hidden = !open;
      sections.hidden = open;
      toggle.textContent = open ? '返回档案' : '最近改动';
      toggle.setAttribute('aria-expanded', String(open));
      if (open) {
        history.replaceChildren(recentChanges(ctx.current?.() || ctx, {
          residentId: resident.id,
          onUndo: () => {
            const current = ctx.current();
            const latest = current.state.residents.find(row => row.id === resident.id);
            if (!latest) return;
            const previous = sections.querySelector('[aria-selected=true]')?.dataset.dossierTab;
            header.firstElementChild.replaceWith(recordIdentity(current, latest, latest.level));
            sections.replaceChildren(dossierSections(current, latest, lifeEvent, previous));
          },
        }));
      } else {
        history.replaceChildren();
      }
      history.closest('dialog')?.scrollTo({ top: 0 });
    })
    : null;
  if (toggle) {
    toggle.setAttribute('aria-controls', history.id);
    toggle.setAttribute('aria-expanded', 'false');
  }
  const header = node('header', 'fx-dossier-head', [identity, toggle]);
  const body = node('div', 'fx-profile fx-dossier', [
    header,
    sections,
    history,
  ]);
  body.dataset.roundsResidentId = resident.id;
  return body;
}

export function residentWorkspaceTab(ctx, id, initialSection, lifeEvent) {
  if (typeof id !== 'string' || !id.startsWith('resident-') || ctx.state.user.kind === 'family') return null;
  const rid = id.slice('resident-'.length);
  const person = ctx.state.residents?.find(r => r.id === rid);
  if (!person) return null;
  return {
    id, title: residentLabel(ctx, person),
    render(live) {
      const current = live.state.residents.find(r => r.id === rid);
      if (!current || live.state.user.kind === 'family') return live.ui.empty('当前档案已不在可查阅范围内。');
      const state = live.workspaceState || {};
      if (lifeEvent && !state.dossierEvent) state.dossierEvent = lifeEvent;
      const body = node('section','resident-record-workspace');
      body.dataset.roundsResidentId = rid;
      function repaint() {
        body.replaceChildren(dossierContent(live, current, state.dossierEvent, state.dossierSection || initialSection));
      }
      body.addEventListener('dossier-section', event => { state.dossierSection = event.detail; });
      body.addEventListener('dossier-open', event => {
        const { section, target } = event.detail;
        const changed = target && (target.eventId !== state.dossierEvent?.eventId || target.day !== state.dossierEvent?.day);
        if (changed || body.querySelector('.resident-dossier-history:not([hidden])')) {
          if (target) state.dossierEvent = target;
          state.dossierSection = section;
          repaint();
        } else {
          const tab = [...body.querySelectorAll('[data-dossier-tab]')].find(b => b.dataset.dossierTab === section);
          tab?.click();
        }
      });
      repaint();
      return body;
    },
  };
}

export function openDossier(ctx, resident, lifeEvent, initialSection) {
  const tab = ctx.openWorkspaceTab && residentWorkspaceTab(ctx, 'resident-' + resident.id, initialSection, lifeEvent);
  if (tab) {
    const route = ['dossier', 'residents', 'billing', 'longCare'].find(id => ctx.available(id));
    if (route) {
      const current = ctx.openWorkspaceTab(route, tab);
      if (initialSection || lifeEvent) {
        const section = lifeEvent ? 'timeline' : initialSection;
        const panel = [...document.querySelectorAll('.resident-record-workspace')].find(el => el.dataset.roundsResidentId === resident.id);
        panel?.dispatchEvent(new CustomEvent('dossier-open', {detail:{section,target:lifeEvent}}));
      }
      return current;
    }
  }
  const dialog = ctx.detail('长辈详细档案', dossierContent(ctx, resident, lifeEvent, initialSection));
  dialog.classList.add('resident-dossier-dialog');
  dialog.dataset.roundsResidentId = resident.id;
  return dialog;
}

export function openRecordedVisit(ctx, residentId, visitId) {
  const live = ctx.current?.() || ctx;
  if (!live.available('dossier') || !allowed(live, 'medical')) return;
  const person = live.state.residents.find(row => row.id === residentId);
  const visit = person && visitsFor(live, residentId).find(row => row.id === visitId);
  if (!visit) return live.toast('这份就诊病例已不在当前可查阅范围内。');
  const archived = person.status === '已退住' || person.status === '归档到期';
  const reopen = current => openDossier(current, person, undefined, 'medical');
  if (reopen(live) === false) return;
  return showVisit(live, person, visit, archived ? null : openVisitEditor,
    { open: showDocument, add: archived ? null : newDocument, reopen });
}

export function renderDossier(route, ctx) {
  if (route === 'family') return familyPortal(ctx, relativeFields, relativeForm);
  const create = canAct(ctx, 'care.register') ? () => register(ctx) : null;
  return residentRoster(ctx, {
    mode:'dossier', create,
    detail: resident => openDossier(ctx, resident),
    medical: resident => openDossier(ctx, resident, undefined, 'medical'),
    edit: resident => editResident(ctx, resident, (ctx.state.dossierProfiles || []).find(p => p.residentId === resident.id) || {}),
  });
}
