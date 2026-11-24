import { priorReports } from './agent-runs.js';
import { node, table, select, options, memo, link, named, badge, runForm, facts, section, records, btn } from './shared.js';

function review(ctx, row) {
  runForm(ctx, {
    title: '审核建议',
    action: 'ops.review',
    description: row.title + '。' + row.detail,
    fields: [
      select('decision', '审核结果', options(['采纳', '驳回'])),
      memo('note', '审核意见', true),
    ],
    map: (v) => ({
      ...v,
      id: row.id,
    }),
    submitLabel: '保存审核结果',
  });
}

export function openPriorReports(ctx) {
  function inspect(row) {
    const evidence = (row.evidence || []).map((e) => {
      const details = node('details');
      details.append(
        node('summary', '', e.label + ' · ' + e.value),
        node('small', 'fx-muted', [e.source, ' · ', (e.recordIds || []).join('、') || '无关联编号'])
      );
      return details;
    });
    const contents = node('div', 'fx-profile', [
      facts([
        ['建议', row.title],
        ['类别', row.category],
        ['生成日期', row.date],
        ['规则版本', row.ruleVersion],
        ['审核状态', row.status],
      ]),
      section('建议内容', node('p', '', row.detail)),
      section(
        '数据依据',
        records(evidence, (item) => item)
      ),
    ]);
    if (row.status === '待审核') {
      contents.append(btn(ctx, '审核建议', () => review(ctx, row), 'primary'));
    } else {
      contents.append(
        section(
          '审核记录',
          facts([
            ['结果', row.status],
            ['日期', row.reviewedAt],
            ['意见', row.reviewNote],
          ])
        )
      );
    }
    ctx.detail('建议详情', contents);
  }
  const list = table(ctx, {
    title: '建议审核台账',
    rows: ctx.state.suggestions,
    search: {
      placeholder: '搜索建议或类别',
      value: (r) => r.category + ' ' + r.title + ' ' + r.detail,
    },
    filter: {
      value: (r) => r.status,
    },
    cols: [
      {
        label: '建议',
        view: (r) => named(r.title, r.category),
      },
      {
        label: '生成日期',
        view: (r) => r.date,
      },
      {
        label: '审核状态',
        view: (r) => badge(ctx, r.status),
      },
      {
        label: '操作',
        align: 'end',
        view: (r) => link(ctx, r.status === '待审核' ? '查看并审核' : '查看详情', () => inspect(r)),
      },
    ],
  });
  ctx.detail('历史业务简报', node('div', 'fx-page', [priorReports(ctx), list]));
}
