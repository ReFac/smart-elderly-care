import { btn, facts, hasGrant, node, section } from './shared.js';

const fields = { summary: '病史摘要', allergies: '过敏史', risk: '高危要点' };
const names = { name: '原件姓名', ...fields };

function input(label, control) {
  return node('label', 'field', [node('span', '', label), control]);
}

export async function reviewOcr(ctx, doc) {
  try {
    doc = { ...doc, ocr: await ctx.get('/api/documents/' + encodeURIComponent(doc.id) + '/ocr') };
  } catch (error) {
    ctx.toast(error.message);
    return;
  }
  const resident = ctx.state.residents.find((r) => r.id === doc.residentId);
  const recognized = doc.ocr.state === 'recognized';
  const form = node('form', 'fx-profile fx-document');
  const image = node('img');
  image.src = '/api/documents/' + encodeURIComponent(doc.id) + '/image';
  image.alt = doc.source + ' · ' + doc.category + '原件';
  const original = node('a', 'btn btn-secondary', '放大原件');
  original.href = image.src;
  original.target = '_blank';
  original.rel = 'noopener';
  const svgNS = 'http://www.w3.org/2000/svg';
  const canvas = document.createElementNS(svgNS, 'svg');
  const paper = document.createElementNS(svgNS, 'image');
  const marker = document.createElementNS(svgNS, 'rect');
  canvas.setAttribute('width', '100%');
  canvas.setAttribute('aria-label', '原件及所选识别行的位置');
  marker.setAttribute('fill', '#ffd567');
  marker.setAttribute('fill-opacity', '.30');
  marker.setAttribute('stroke', '#946100');
  marker.setAttribute('stroke-width', '3');
  paper.setAttribute('href', image.src);
  const layout = () => {
    if (!image.naturalWidth) return;
    canvas.setAttribute('viewBox', '0 0 ' + image.naturalWidth + ' ' + image.naturalHeight);
    paper.setAttribute('width', image.naturalWidth);
    paper.setAttribute('height', image.naturalHeight);
  };
  image.addEventListener('load', layout);
  layout();
  canvas.append(paper, marker);
  const highlight = (line) => {
    if (!line?.box) {
      marker.removeAttribute('width');
      return;
    }
    ['x', 'y', 'width', 'height'].forEach((k, i) => marker.setAttribute(k, line.box[i]));
  };
  const preview = node('figure', 'fx-original', [canvas, original]);
  const lines = node('ol', 'fx-profile');
  for (const line of doc.ocr.lines) {
    lines.append(
      node('li', '', [
        btn(ctx, line.text, () => highlight(line), 'text'),
        node(
          'small',
          'fx-muted',
          '  第 ' +
            line.page +
            ' 页 · 第 ' +
            line.line +
            ' 行' +
            (line.confidence == null
              ? ''
              : ' · 置信度 ' +
                line.confidence +
                '%' +
                (line.confidence < 80 ? ' · 请重点核对' : ''))
        )
      ])
    );
  }
  form.append(
    node('div', 'fx-document-sheet', [
      preview,
      recognized
        ? node('details', '', [
            node('summary', '', '核对识别原文（' + doc.ocr.lines.length + ' 行）'),
            lines
          ])
        : node('p', 'fx-muted', doc.ocr.error || '原件已保存，可按原图手工核对。')
    ])
  );
  const identity = node('input');
  identity.required = true;
  identity.maxLength = 60;
  const observed = doc.ocr.candidates.filter((c) => c.field === 'name').map((c) => c.value);
  const mismatch = observed.some((name) => name !== resident.name);
  form.append(
    facts([
      ['当前长者', resident.name],
      ['原件识别姓名', observed.join('、') || '请核对原件']
    ]),
    input('对照原件后输入长者姓名', identity)
  );
  const factsText = node('textarea');
  factsText.required = true;
  factsText.maxLength = 8000;
  factsText.rows = 4;
  if (recognized)
    factsText.value = doc.ocr.lines
      .map((l) => l.text)
      .join('\n')
      .slice(0, 8000);
  if (recognized && doc.ocr.lines.map((line) => line.text).join('\n').length > 8000)
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
    input(recognized ? '核对并修订原文事实' : '手工摘录原文事实', factsText),
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
      const candidates = doc.ocr.candidates.filter((c) => c.field === key);
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
        origin.add(new Option('第 1 页 · 第 ' + c.line + ' 行 · ' + c.value, String(c.line)));
      origin.add(new Option('人工摘录原件', ''));
      const setValue = () => {
        value.value = candidates.find((c) => String(c.line) === origin.value)?.value || '';
      };
      origin.addEventListener('change', () => {
        setValue();
        highlight(doc.ocr.lines.find((l) => String(l.line) === origin.value));
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
    submit.disabled = true;
    try {
      const changes = controls
        .filter((c) => c.check.checked)
        .map((c) => ({
          field: c.key,
          previous: resident[c.key] || '',
          value: c.value.value,
          line: c.origin.value ? Number(c.origin.value) : null
        }));
      await ctx.command('dossier.reviewDocument', {
        residentId: resident.id,
        documentId: doc.id,
        verifiedName: identity.value,
        sourceFacts: factsText.value,
        pending: pending.value,
        method: recognized
          ? doc.ocr.engine === 'DeepSeek OCR'
            ? 'DeepSeek OCR 人工核对'
            : '院内 OCR 人工核对'
          : '手工描述',
        changes
      });
    } finally {
      submit.disabled = false;
    }
  });
  ctx.detail('核对文书与回填档案', form);
}

export async function recognizeDocument(ctx, residentId, reference, confirmed = false) {
  if (
    !(await ctx.command('dossier.ocr', { residentId, ...reference, consent: true }, { confirmed }))
  )
    return;
  const snapshot = await ctx.get('/api/state');
  if (snapshot.data.user.id !== ctx.state.user.id) return;
  if (!snapshot.data.allowedActions.includes('dossier.reviewDocument')) return;
  const doc = snapshot.data.medicalDocuments.find(
    (d) =>
      d.residentId === residentId &&
      (reference.documentId ? d.id === reference.documentId : d.imageHash === reference.imageHash)
  );
  if (doc && !doc.summary) reviewOcr({ ...ctx, state: snapshot.data }, doc);
}

export function pendingDocument(ctx, doc) {
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
  const image = node('img');
  image.src = '/api/documents/' + doc.id + '/image';
  image.alt = '已归档原件';
  body.append(node('figure', 'fx-original', image));
  if (hasGrant(ctx, 'medical.write') && ctx.state.residents.some(r=>r.id===doc.residentId && r.status==='在住')) {
    if (['queued', 'failed'].includes(doc.ocr.state))
      body.append(
        btn(
          ctx,
          '提交 DeepSeek OCR',
          () =>
            ctx.dialog({
              title: '确认发送文书原件',
              description: '这张照片将提交 DeepSeek OCR，并按成功识别页数使用机构额度。',
              fields: [],
              submitLabel: '确认并发送',
              onSubmit: async () => {
                await recognizeDocument(ctx, doc.residentId, { documentId: doc.id });
                return true;
              }
            }),
          'primary'
        )
      );
    if (ctx.state.allowedActions.includes('dossier.reviewDocument'))
      body.append(
        btn(ctx, doc.ocr.state === 'recognized' ? '核对原文与回填' : '按原件手工补录', () =>
          reviewOcr(ctx, doc)
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
          (entry.line ? '原件第 1 页第 ' + entry.line + ' 行' : '人工摘录原件')
      ])
    )
  );
}
