import { residentLabel } from './people-labels.js';
import { btn, facts, hasGrant, node, section } from './shared.js';
import { originalViewer } from './document-original.js';

const fields = { summary: '病史摘要', allergies: '过敏史', risk: '高危要点' };
const names = { name: '原件姓名', ...fields };

function input(label, control) {
  return node('label', 'field', [node('span', '', label), control]);
}

export async function reviewOcr(ctx, doc, reopenVisit) {
  try {
    doc = { ...doc, ocr: await ctx.get('/api/documents/' + encodeURIComponent(doc.id) + '/ocr') };
  } catch (error) {
    ctx.toast(error.message);
    return;
  }
  const resident = ctx.state.residents.find((r) => r.id === doc.residentId);
  const recognized = doc.ocr.state === 'recognized';
  const manual = doc.ocr.manualReportReview;
  const form = node('form', 'fx-profile fx-document');
  const totalPages = doc.pageCount || 1;
  const checked = new Set();
  const pageCheck = node('input');
  pageCheck.type = 'checkbox';
  const pageLabel = node('span');
  const count = node('p', 'fx-muted');
  const lines = node('ol', 'fx-profile');
  const provenance = node('p', 'fx-muted');
  const byPage = new Map();
  for (const line of doc.ocr.lines) {
    if (!byPage.has(line.page)) byPage.set(line.page, []);
    byPage.get(line.page).push(line);
  }
  const issues = new Map((doc.ocr.pages || []).map(p => [p.page, p.state]));
  function showPage(page) {
    pageCheck.checked = checked.has(page);
    pageLabel.textContent = '已核对原件第 ' + page + ' 页';
    count.textContent = '已核对 ' + checked.size + ' / ' + totalPages + ' 页';
    const state = issues.get(page);
    provenance.textContent = state === 'partial' ? '本页识别内容不完整，请对照原件补录。'
      : state === 'blank' ? '本页未识别到文字。' : '';
    lines.replaceChildren(...(byPage.get(page) || []).map(line => node('li', '', [
      btn(ctx, line.text, () => viewer.highlight(line), 'text'),
      node('small', 'fx-muted', ' 第 ' + line.page + ' 页 · 第 ' + line.line + ' 行'
        + (line.confidence == null ? '' : ' · 置信度 ' + line.confidence + '%'
          + (line.confidence < 80 ? ' · 请重点核对' : ''))),
    ])));
  }
  const viewer = originalViewer(doc, showPage);
  const pageRecheck = node('label', 'access-check', [pageCheck, pageLabel]);
  pageCheck.addEventListener('change', () => {
    if (pageCheck.checked) checked.add(viewer.page);
    else checked.delete(viewer.page);
    showPage(viewer.page);
  });
  form.append(node('div', 'fx-document-sheet', [
    viewer.element,
    node('div', 'fx-profile', [
      recognized ? node('details', '', [node('summary', '', '核对当前页识别原文'), lines])
        : node('p', 'fx-muted', doc.ocr.error || '原件已保存，可以手工核对。'),
      provenance,
      totalPages > 1 ? pageRecheck : null, totalPages > 1 ? count : null,
    ]),
  ]));
  for (const warning of doc.ocr.reviewWarnings || [])
    form.append(node('p', 'medical-visit-warning', warning));
  const identity = node('input');
  identity.required = true;
  identity.maxLength = 60;
  const observed = doc.ocr.candidates.filter((c) => c.field === 'name').map((c) => c.value);
  const mismatch = observed.some((name) => name !== resident.name);
  form.append(
    facts([
      ['当前长辈', residentLabel(ctx, resident)],
      ['原件识别姓名', observed.join('、') || '请核对原件']
    ]),
    input('对照原件后输入长辈姓名', identity)
  );
  const factsText = node('textarea');
  factsText.required = true;
  factsText.maxLength = 8000;
  factsText.rows = 4;
  const completeLines = doc.ocr.lines.filter(line => !issues.has(line.page) || issues.get(line.page) === 'complete');
  if (recognized && !manual)
    factsText.value = completeLines
      .map((l) => l.text)
      .join('\n')
      .slice(0, 8000);
  if (recognized && !manual && completeLines.map((line) => line.text).join('\n').length > 8000)
    form.append(
      node(
        'p',
        'fx-muted',
        '文书原文较长，概括框预填前 8,000 字。请核对完整识别行并选取要保留的内容。'
      )
    );
  const pending = node('textarea');
  pending.maxLength = 2000;
  form.append(
    input(recognized && !manual ? '核对并修订原文事实' : '手工摘录原文事实', factsText),
    input('待核实事项', pending)
  );
  const controls = [];
  if (mismatch)
    form.append(
      node(
        'p',
        'form-error',
        '原件识别姓名与档案不同，请核对身份。本次可留存概括，档案字段需另行核查。'
      )
    );
  if (!mismatch && hasGrant(ctx, 'clinical')) {
    const box = node('fieldset', 'fx-form-group', [node('legend', '', '逐项确认档案回填')]);
    for (const [key, title] of Object.entries(fields)) {
      const candidates = manual ? [] : doc.ocr.candidates.filter((c) => c.field === key);
      const check = node('input');
      check.type = 'checkbox';
      check.name = key;
      const value = node('textarea');
      value.rows = 2;
      value.maxLength = 1000;
      value.disabled = true;
      const origin = node('select');
      origin.disabled = true;
      for (const c of candidates)
        origin.add(new Option('第 ' + (c.page || 1) + ' 页 · 第 ' + c.line + ' 行 · ' + c.value, (c.page || 1) + ':' + c.line));
      for (let page = 1; page <= totalPages; page++)
        origin.add(new Option('人工摘录原件第 ' + page + ' 页', page + ':'));
      const setValue = () => {
        value.value = candidates.find((c) => (c.page || 1) + ':' + c.line === origin.value)?.value || '';
      };
      origin.addEventListener('change', () => {
        setValue();
        const [page, line] = origin.value.split(':');
        viewer.selectPage(Number(page));
        viewer.highlight((byPage.get(Number(page)) || []).find((l) => l.line === Number(line)));
      });
      setValue();
      check.addEventListener('change', () => {
        value.disabled = origin.disabled = !check.checked;
        value.required = check.checked;
      });
      const titleRow = node('label', 'access-check', [
        check,
        node('strong', '', '确认回填' + title)
      ]);
      box.append(
        section(
          title,
          node('div', 'fx-profile', [
            node('p', 'fx-muted', '现有内容：' + (resident[key] || '未填写')),
            titleRow,
            input('原文依据', origin),
            input('拟写入内容', value)
          ])
        )
      );
      controls.push({ key, check, value, origin });
    }
    form.append(box);
  }
  const confirm = node('input');
  confirm.type = 'checkbox';
  confirm.required = true;
  const submit = node('button', 'btn btn-primary', '确认概括及所选回填项');
  submit.type = 'submit';
  form.append(node('label', 'access-check', [confirm, '已对照原件核实概括和所选项目']), submit);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (submit.disabled) return;
    if (totalPages > 1 && checked.size !== totalPages) {
      const missing = Array.from({ length: totalPages }, (_, i) => i + 1).find(p => !checked.has(p));
      viewer.selectPage(missing);
      pageCheck.focus();
      return ctx.toast('请先核对原件的每一页。');
    }
    submit.disabled = true;
    try {
      const changes = controls
        .filter((c) => c.check.checked)
        .map((c) => ({
          field: c.key,
          previous: resident[c.key] || '',
          value: c.value.value,
          page: Number(c.origin.value.split(':')[0]),
          line: Number(c.origin.value.split(':')[1]) || null
        }));
      const saved = await ctx.command('dossier.reviewDocument', {
        residentId: resident.id,
        documentId: doc.id,
        verifiedName: identity.value,
        sourceFacts: factsText.value,
        pending: pending.value,
        method: recognized && !manual
          ? doc.ocr.engine === 'DeepSeek OCR'
            ? 'DeepSeek OCR 人工核对'
            : '院内 OCR 人工核对'
          : '手工描述',
        changes,
        ...(totalPages > 1 ? { reviewedPages: [...checked].sort((a, b) => a - b) } : {}),
      });
      if (saved) reopenVisit?.();
    } finally {
      submit.disabled = false;
    }
  });
  ctx.detail('核对文书与回填档案', form);
}

export async function recognizeDocument(ctx, residentId, reference, confirmed = false, reopenVisit) {
  const processed = await ctx.command('dossier.ocr', { residentId, ...reference, consent: true }, { confirmed });
  reopenVisit?.();
  if (!processed) return;
  const snapshot = await ctx.get('/api/state');
  if (snapshot.data.user.id !== ctx.state.user.id) return;
  if (!snapshot.data.allowedActions.includes('dossier.reviewDocument')) return;
  const doc = snapshot.data.medicalDocuments.find(
    (d) =>
      d.residentId === residentId &&
      (reference.documentId ? d.id === reference.documentId : d.imageHash === reference.imageHash)
  );
  if (doc && !doc.summary) reviewOcr({ ...ctx, state: snapshot.data }, doc, reopenVisit);
}

export function pendingDocument(ctx, doc, reopenVisit) {
  const body = node('div', 'fx-profile', [
    facts([
      ['文书类型', doc.category],
      ['发生日期', doc.eventDate],
      ['来源', doc.source],
      [
        '识别状态',
        { queued: '原件已保存', failed: '待人工补录', recognized: '待人工核对' }[doc.ocr.state]
      ]
    ])
  ]);
  if (doc.ocr.error) body.append(node('p', 'fx-muted', doc.ocr.error));
  body.append(originalViewer(doc).element);
  if (hasGrant(ctx, 'medical.write') && ctx.state.residents.some(r=>r.id===doc.residentId && r.status==='在住')) {
    if (['queued', 'failed'].includes(doc.ocr.state))
      body.append(
        btn(
          ctx,
          '提交 DeepSeek OCR',
          () =>
            ctx.dialog({
              title: '确认发送文书原件',
              description: '此原件共 ' + (doc.pageCount || 1) + ' 页，预计使用 ' + (doc.pageCount || 1) + ' 页 OCR 额度。',
              fields: [],
              submitLabel: '确认并发送',
              onSubmit: async () => {
                await recognizeDocument(ctx, doc.residentId, { documentId: doc.id }, true, reopenVisit);
                return true;
              }
            }),
          'primary'
        )
      );
    if (ctx.state.allowedActions.includes('dossier.reviewDocument'))
      body.append(
        btn(ctx, doc.ocr.state === 'recognized' ? '核对原文与回填' : '按原件手工补录', () =>
          reviewOcr(ctx, doc, reopenVisit)
        )
      );
  }
  ctx.detail('医疗文书原件', body);
}

export function reviewReceipt(doc) {
  return section(
    '档案回填凭证',
    facts(
      Object.entries(doc.reviewChanges).map(([key, entry]) => [
        names[key],
        (entry.before || '未填写') +
          ' → ' +
          entry.after +
          ' · ' +
          (entry.line ? '原件第 ' + (entry.page || 1) + ' 页第 ' + entry.line + ' 行' : '人工摘录原件第 ' + (entry.page || 1) + ' 页')
      ])
    )
  );
}
