import { staffLabel } from './people-labels.js';
import {
  disclosure,
  facts,
  field,
  staffField,
  hasGrant,
  kpis,
  memo,
  node,
  options,
  residentField,
  residentName,
  section,
  select,
  today,
} from './shared.js';

export function scaleForm(ctx, residentId = '') {
  const scale = ctx.state.careScale;
  if (!scale || !hasGrant(ctx, 'clinical', 'medical')) return;
  const values = [];
  const scoreBox = node('div', 'fx-profile');
  const source = node('a', 'btn btn-text', '查看国家标准评分细则');
  source.href = scale.sourceUrl;
  source.target = '_blank';
  source.rel = 'noopener noreferrer';
  scoreBox.append(source);
  const sum = node('output', 'fx-muted', '尚未评分');
  function update() {
    const filled = values.filter(({ control }) => control.value !== '');
    const total = filled.reduce((n, { control }) => n + Number(control.value), 0);
    sum.textContent =
      '已录入 ' + filled.length + ' / ' + values.length + ' 项 · 当前合计 ' + total + ' 分';
  }
  for (const [group, items] of Object.entries(scale.groups)) {
    const scores = node('div', 'access-choices');
    for (const [label, max] of Object.entries(items)) {
      const control = node('select', 'fx-input');
      control.name = 'score' + values.length;
      control.required = true;
      control.add(new Option('请选择', ''));
      for (let i = max; i >= 0; i--) control.add(new Option(i + ' 分', String(i)));
      control.addEventListener('change', update);
      values.push({ label, control });
      scores.append(node('label', 'field', [node('span', '', label), control]));
    }
    scoreBox.append(node('section', 'fx-section', [node('h3', '', group), scores]));
  }
  scoreBox.append(sum);
  const subject = residentField(ctx, { value: residentId });
  subject.options.unshift({ value: '', label: '请选择本次评估的长辈' });
  const dialog = ctx.dialog({
    title: '标准量表评估',
    description:
      scale.version + ' · 请按评估人员核实的分值逐项录入，登记两位评估人员及纸质原表编号。',
    content: scoreBox,
    fields: [
      subject,
      select('source', '采集方式', options(['线上采集', '纸质量表录入'])),
      field('assessedOn', '实际评估日期', { type: 'date', value: today(ctx), max: today(ctx) }),
      field('assessor', '评估人员一（医护背景）'),
      field('coAssessor', '评估人员二'),
      field('reference', '纸质原表编号（纸质录入必填）', { required: false, maxLength: 150 }),
      select('adjustment', '评估人员核实的等级调整条件', [
        { value: '', label: '请选择' },
        ...options(scale.adjustments),
      ]),
      memo('basis', '调整依据（有调整时必填）'),
      select('level', '机构核定的照护等级', [
        { value: '', label: '请选择' },
        ...options(['自理', '半失能', '失能']),
      ]),
      memo('note', '评估结论与照护需求', true),
      staffField(ctx, 'assignee', '责任人（留空按当日排班匹配）', { required: false }),
      field('reviewDate', '预约复评日期', { type: 'date' }),
    ],
    submitLabel: '保存评分并生成计划',
    onSubmit: (v) => {
      const scores = Object.fromEntries(
        values.map(({ label, control }) => [label, Number(control.value)])
      );
      const {
        source,
        residentId,
        level,
        note,
        assignee,
        reviewDate,
        assessedOn,
        assessor,
        coAssessor,
        reference,
        adjustment,
        basis,
      } = v;
      return ctx.command('care.assess', {
        source,
        residentId,
        level,
        note,
        assignee,
        reviewDate,
        scale: {
          version: scale.version,
          scores,
          assessedOn,
          assessor,
          coAssessor,
          reference,
          adjustment,
          basis,
        },
      });
    },
  });
  // Start with identity and provenance, then enter the item scores before grading.
  const anchor = dialog.querySelector('[name=reference]').closest('label');
  anchor.after(scoreBox.closest('.form-content'));
}

export function evaluationDetails(ctx, row) {
  const scale = row.scale;
  const body = node('div', 'fx-profile', [
    node(
      'h3',
      '',
      residentName(ctx, row.residentId) + ' · ' + (scale ? scale.gradeName : row.level)
    ),
    section('评估结论', node('p', '', row.note)),
  ]);
  if (scale) {
    body.append(
      kpis(Object.entries(scale.subtotals).map(([label, value]) => [label, String(value)]))
    );
    body.append(
      facts([
        ['能力总分', scale.total + ' / 90'],
        ['采用量表', scale.version],
        ['实际评估日期', scale.assessedOn],
        ...(scale.assessors ? [['评估人员', scale.assessors.join('、')]] : []),
        ['采集方式', row.source],
        ...('reference' in scale ? [['原表编号', scale.reference]] : []),
        ...('adjustment' in scale ? [['等级调整', scale.adjustment]] : []),
        ...(scale.basis ? [['调整凭据', scale.basis]] : []),
        ['机构照护等级', row.level],
        ['下次复评', row.historyOnly ? '历史补录' : row.reviewDate],
        ['登记人', staffLabel(ctx, row.recordedBy)],
        ['登记日期', row.date],
      ])
    );
    body.append(
      disclosure(
        '逐项评分',
        facts(Object.entries(scale.scores).map(([name, score]) => [name, score + ' 分'])),
        Object.keys(scale.scores).length
      )
    );
  } else {
    body.append(
      facts([
        ['评估日期', row.date],
        ['下次复评', row.reviewDate],
        ['采集方式', row.source],
        ['登记人', staffLabel(ctx, row.recordedBy)],
      ])
    );
  }
  ctx.detail('评估记录', body);
}
