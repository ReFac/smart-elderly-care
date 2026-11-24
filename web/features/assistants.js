import { agentDesk } from './agent-runs.js';
import {
  hasGrant,
  tabs,
  node,
  page,
  table,
  select,
  options,
  memo,
  residentField,
  btn,
  link,
  named,
  badge,
  runForm,
  facts,
  section,
  records,
} from './shared.js';
const assistants = [
  {
    name: '日常照护',
    icon: 'heart',
    summary: '根据长者最近的有效评估整理已确认的生活需求、服务项目、责任人和复评日。',
  },
  {
    name: '物资管控',
    icon: 'box',
    summary: '核对库存下限，汇总需要补充的护理物品。',
  },
  {
    name: '运营分析',
    icon: 'chart',
    summary: '归集未核销账单，整理应收余额与跟进事项。',
  },
];

function generate(ctx, assistant) {
  runForm(ctx, {
    title: '生成' + assistant.name + '建议',
    description: assistant.summary,
    action: 'ops.suggest',
    fields: assistant.name === '日常照护' ? [residentField(ctx)] : [],
    map: (v) => ({
      ...v,
      category: assistant.name,
    }),
    submitLabel: '生成待审核建议',
  });
}

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

export function assistantsPage(ctx) {
  const grants = { 日常照护: 'care', 运营分析: 'finance', 物资管控: 'inventory' };
  const accessible = assistants.filter((a) => hasGrant(ctx, grants[a.name]));
  if (!accessible.length)
    return page(
      ctx,
      'Agent 工作台',
      '',
      null,
      ctx.ui.empty('此账号尚未分配可用于生成建议的业务权限。')
    );
  const cards = node(
    'div',
    'fx-assistants',
    accessible.map((a) =>
      node('article', 'fx-assistant', [
        node('div', 'fx-assistant-mark', ctx.ui.icon(a.icon, 23)),
        node('h2', '', a.name),
        node('p', '', a.summary),
        btn(ctx, a.name === '日常照护' ? '生成个体照护计划草稿' : '生成建议', () => generate(ctx, a)),
      ])
    )
  );
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
  return page(
    ctx,
    'Agent 工作台',
    '委派照护、物资和经营任务，核对工具读取的单据，再发布协作结果。',
    null,
    tabs('assistants', [
      ['runs', '多 Agent 协作', () => agentDesk(ctx)],
      ['ledger', '专项建议台账', () => node('div', 'fx-page', [cards, list])],
    ])
  );
}
