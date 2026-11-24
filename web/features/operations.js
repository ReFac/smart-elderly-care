import {
  canAct,
  hasGrant,
  node,
  page,
  table,
  tabs,
  field,
  select,
  options,
  memo,
  residentName,
  choose,
  btn,
  link,
  named,
  badge,
  runForm,
  facts,
  section,
  records,
  today,
} from './shared.js';
import { monthlyPanel } from './monthly.js';

function addItem(ctx) {
  runForm(ctx, {
    title: '建立物资品目',
    description: '品目建立后，在入库流水中登记期初实存数量。',
    action: 'ops.addItem',
    fields: [
      field('name', '物资名称', { maxLength: 80 }),
      field('unit', '计量单位', { maxLength: 16, placeholder: '如：盒、包、瓶' }),
      field('minimum', '库存下限', { type: 'number', min: 0, max: 999999999, step: 1, value: 0 }),
    ],
    submitLabel: '建立品目',
  });
}

function stock(ctx, type, itemId) {
  runForm(ctx, {
    title: '登记' + type,
    action: 'ops.stock',
    defaults: {
      itemId,
    },
    fields: [
      select(
        'itemId',
        '物品',
        ctx.state.inventory.map((i) => ({
          value: i.id,
          label: i.name + '（' + i.unit + '）',
        }))
      ),
      field('quantity', '数量', {
        type: 'number',
        min: 1,
        step: 1,
      }),
      memo('note', type === '出库' ? '领用人及用途' : '入库备注', true),
    ],
    map: (v) => ({
      ...v,
      type,
    }),
    submitLabel: '确认' + type,
  });
}

export function inventory(ctx) {
  const state = ctx.state;
  const low = (i) => (i.quantity < i.minimum ? '低库存' : '正常');
  const findItem = (id) => state.inventory.find((i) => i.id === id);
  return page(
    ctx,
    '仓储物资',
    '管理护理物品存量、领用与补货记录。',
    choose(
      canAct(ctx, 'ops.addItem')
        ? btn(
            ctx,
            '建立物资品目',
            () => addItem(ctx),
            state.inventory.length ? 'secondary' : 'primary'
          )
        : null,
      state.inventory.length ? btn(ctx, '登记出库', () => stock(ctx, '出库')) : null,
      state.inventory.length ? btn(ctx, '登记入库', () => stock(ctx, '入库'), 'primary') : null
    ),
    tabs('inventory', [
      [
        'stock',
        '库存台账',
        () =>
          table(ctx, {
            title: '库存明细',
            rows: state.inventory,
            search: {
              placeholder: '搜索物品名称',
              value: (r) => r.name,
            },
            filter: {
              value: low,
            },
            cols: [
              {
                label: '物品名称',
                view: (i) => named(i.name, i.id),
              },
              {
                label: '现有库存',
                view: (i) => i.quantity + ' ' + i.unit,
              },
              {
                label: '库存下限',
                view: (i) => i.minimum + ' ' + i.unit,
              },
              {
                label: '状态',
                view: (i) => badge(ctx, low(i), low(i) === '正常' ? 'green' : 'amber'),
              },
              {
                label: '操作',
                align: 'end',
                view: (i) =>
                  link(ctx, '查看流水', () =>
                    ctx.detail(
                      i.name + ' · 出入库流水',
                      node('div', 'fx-profile', [
                        facts([
                          ['现有库存', i.quantity + ' ' + i.unit],
                          ['库存下限', i.minimum + ' ' + i.unit],
                        ]),
                        records(
                          state.transactions.filter((t) => t.itemId === i.id),
                          (t) =>
                            named(
                              t.type + ' ' + t.quantity + ' ' + i.unit,
                              t.date + ' · ' + (t.note || '—')
                            )
                        ),
                        choose(
                          btn(ctx, '入库', () => stock(ctx, '入库', i.id)),
                          btn(ctx, '出库', () => stock(ctx, '出库', i.id))
                        ),
                      ])
                    )
                  ),
              },
            ],
          }),
      ],
      [
        'moves',
        '出入库流水',
        () =>
          table(ctx, {
            title: '物资流水',
            rows: state.transactions,
            search: {
              placeholder: '搜索物品或用途',
              value: (t) => findItem(t.itemId)?.name + ' ' + t.note,
            },
            filter: {
              value: (t) => t.type,
              all: '全部类型',
            },
            cols: [
              {
                label: '日期',
                view: (t) => t.date,
              },
              {
                label: '物品',
                view: (t) => findItem(t.itemId)?.name,
              },
              {
                label: '类型',
                view: (t) => badge(ctx, t.type),
              },
              {
                label: '数量',
                view: (t) => t.quantity + ' ' + (findItem(t.itemId)?.unit || ''),
              },
              {
                label: '用途 / 备注',
                view: (t) => t.note || '—',
              },
            ],
          }),
      ],
    ])
  );
}

export function shifts(ctx) {
  const state = ctx.state;
  const workload = (staff, date) =>
    state.tasks.filter((t) => t.assignee === staff && t.date === date && t.status !== '已取消');
  function create() {
    runForm(ctx, {
      title: '安排班次',
      action: 'ops.shift',
      fields: [
        field('staff', '值班人员'),
        field('date', '排班日期', {
          type: 'date',
          value: today(ctx),
        }),
        select('period', '班次', options(['早班', '中班', '夜班'])),
        field('area', '负责区域'),
      ],
    });
  }
  return page(
    ctx,
    '排班管理',
    hasGrant(ctx, 'care')
      ? '按班次分配人员及责任区域，查看当日工单量。'
      : '按班次分配人员和责任区域。',
    btn(ctx, '安排班次', create, 'primary'),
    table(ctx, {
      title: '人员排班',
      rows: [...state.shifts].sort((a, b) => b.date.localeCompare(a.date)),
      search: {
        placeholder: '搜索人员、区域或日期',
        value: (s) => s.staff + ' ' + s.area + ' ' + s.date,
      },
      filter: {
        value: (s) => s.period,
        all: '全部班次',
      },
      cols: [
        {
          label: '值班日期',
          view: (s) => s.date,
        },
        {
          label: '值班人员',
          view: (s) => s.staff,
        },
        {
          label: '班次',
          view: (s) => badge(ctx, s.period, 'blue'),
        },
        {
          label: '责任区域',
          view: (s) => s.area,
        },
        ...(hasGrant(ctx, 'care')
          ? [
              {
                label: '当日工单',
                view: (s) => workload(s.staff, s.date).length + ' 项',
              },
              {
                label: '操作',
                align: 'end',
                view: (s) =>
                  link(ctx, '查看工作量', () =>
                    ctx.detail(
                      s.staff + ' · ' + s.date,
                      records(
                        workload(s.staff, s.date),
                        (t) =>
                          named(
                            t.title + ' · ' + residentName(ctx, t.residentId),
                            t.time + ' · ' + t.status
                          ),
                        '当日暂无照护工单'
                      )
                    )
                  ),
              },
            ]
          : []),
      ],
    })
  );
}

function download(ctx, report) {
  const payload = JSON.stringify(report, null, 2);
  const url = URL.createObjectURL(
    new Blob([payload], {
      type: 'application/json;charset=utf-8',
    })
  );
  const a = node('a');
  a.href = url;
  a.download = '民政报送草稿-' + report.month + '.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  ctx.toast('报送草稿已导出');
}

function reportDetails(ctx, r) {
  const issues = Array.isArray(r.issues) ? r.issues : [];
  ctx.detail(
    '民政报送草稿',
    node('div', 'fx-profile', [
      facts([
        ['月份', r.month],
        ['记录数', String(r.recordCount)],
        ['校验状态', r.status],
        ['生成日期', r.createdAt],
        ['数据截止', r.cutoff],
        ...Object.entries(r.summary || {}).map(([key, val]) => [key, String(val)]),
      ]),
      section(
        '校验项目',
        records(r.checks || [], (i) => i)
      ),
      section(
        '校验结果',
        records(issues, (i) => i, '当前草稿已通过本地完整性校验')
      ),
      table(ctx, {
        title: '报送数据集',
        rows: r.rows,
        search: {
          placeholder: '搜索档案编号',
          value: (item) => item.residentId,
        },
        cols: [
          {
            label: '档案编号',
            view: (item) => item.residentId,
          },
          {
            label: '入住日期',
            view: (item) => item.admittedAt,
          },
          {
            label: '退住日期',
            view: (item) => item.dischargedAt || '—',
          },
          {
            label: '状态',
            view: (item) => badge(ctx, item.status),
          },
        ],
      }),
      btn(ctx, '导出 JSON 草稿', () => download(ctx, r)),
    ])
  );
}

export function reports(ctx) {
  const state = ctx.state;
  function create() {
    runForm(ctx, {
      title: '生成民政报送草稿',
      description: '归集当月业务数据并校验完整性。相同月份会刷新本地草稿。',
      action: 'ops.report',
      fields: [
        field('month', '报送月份', {
          type: 'month',
          value: today(ctx).slice(0, 7),
          max: today(ctx).slice(0, 7),
        }),
      ],
      submitLabel: '生成并校验',
    });
  }
  const drafts = () =>
    table(ctx, {
      title: '月度报送草稿',
      rows: state.reports,
      search: {
        placeholder: '搜索报送月份',
        value: (r) => r.month,
      },
      filter: {
        value: (r) => r.status,
      },
      cols: [
        {
          label: '报送月份',
          view: (r) => r.month,
        },
        {
          label: '业务记录',
          view: (r) => r.recordCount + ' 条',
        },
        {
          label: '校验问题',
          view: (r) => r.issues.length + ' 项',
        },
        {
          label: '状态',
          view: (r) => badge(ctx, r.status),
        },
        {
          label: '操作',
          align: 'end',
          view: (r) => link(ctx, '查看草稿', () => reportDetails(ctx, r)),
        },
      ],
    });
  const audit = () =>
    table(ctx, {
      title: '最近 100 次业务操作',
      rows: state.audit,
      search: {
        placeholder: '搜索操作或记录',
        value: (r) => r.action + ' ' + r.summary,
      },
      cols: [
        {
          label: '版本',
          view: (r) => r.revision,
        },
        {
          label: '发生时间',
          view: (r) => r.at.slice(0, 19).replace('T', ' '),
        },
        {
          label: '业务操作',
          view: (r) => r.action,
        },
        {
          label: '变更摘要',
          view: (r) => r.summary,
        },
      ],
      empty: '尚无人工提交的操作',
    });
  return page(
    ctx,
    '统计报送',
    canAct(ctx, 'ops.report')
      ? '按月归集业务数据并生成民政报送草稿。'
      : '查阅获授权业务的操作记录。',
    canAct(ctx, 'ops.report') ? btn(ctx, '生成报送草稿', create, 'primary') : null,
    tabs('reports', [
      ...(canAct(ctx, 'ops.report') ? [['drafts', '民政报送', drafts]] : []),
      ...(hasGrant(ctx, 'reports') && hasGrant(ctx, 'finance', 'care', 'inventory')
        ? [['monthly', '经营月报', () => monthlyPanel(ctx)]]
        : []),
      ...(hasGrant(ctx, 'audit') ? [['audit', '操作日志', audit]] : []),
    ])
  );
}
