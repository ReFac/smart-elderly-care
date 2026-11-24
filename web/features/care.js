import { careTimeline } from './care-timeline.js';
import {
  canAct,
  hasGrant,
  node,
  page,
  table,
  tabs,
  field,
  staffField,
  select,
  options,
  memo,
  residentField,
  residentName,
  byRecent,
  btn,
  link,
  named,
  badge,
  runForm,
  facts,
  section,
  records,
  today,
  nextDay,
} from './shared.js';
import { scaleForm, evaluationDetails } from './assessment-scale.js';
import { followups, referrals } from './care-pathway.js';
import { medicationReminders, drugRules } from './medication-rules.js';
import { levels } from './residency.js';
import { handovers } from './handovers.js';

const personSearch = (ctx, extra) => ({
  placeholder: '搜索长者或记录',
  value: (r) => residentName(ctx, r.residentId) + ' ' + (extra?.(r) || ''),
});

const statusFilter = {
  value: (r) => r.status,
};

const personCol = (ctx) => ({
  label: '长者',
  view: (r) => residentName(ctx, r.residentId),
});

const observations = ['生活起居', '院内活动', '日常沟通'];

function observationFields() {
  return observations.map((name) =>
    select(
      name,
      name,
      [
        {
          value: '',
          label: '未记录',
        },
        ...options(['可独立完成', '需协助', '待观察']),
      ],
      {
        required: false,
      }
    )
  );
}

export function assessments(ctx) {
  const state = ctx.state;
  function assess() {
    runForm(ctx, {
      title: '登记能力评估',
      description: '填写评估人员确认的等级和服务需求，保存后生成照护计划草稿。',
      submitLabel: '保存评估并生成草稿',
      action: 'care.assess',
      fields: [
        residentField(ctx),
        select('source', '观察记录来源', options(['线上采集', '纸质观察记录'])),
        select('level', '评定照护等级', options(levels)),
        ...observationFields(),
        memo('note', '评估结论与照护需求', true),
        staffField(ctx, 'assignee', '负责照护的人员', {
          required: false,
          placeholder: '留空按所在区域、当日排班与待办量匹配',
        }),
        field('reviewDate', '下次复评日期', {
          type: 'date',
          min: nextDay(today(ctx)),
          required: false,
        }),
      ],
      map: (values) => {
        const payload = {
          ...values,
          observations: {},
        };
        for (const name of observations) {
          if (values[name]) payload.observations[name] = values[name];
          delete payload[name];
        }
        return payload;
      },
    });
  }
  function approve(plan) {
    runForm(ctx, {
      title: '复核照护计划',
      action: 'care.approvePlan',
      description:
        residentName(ctx, plan.residentId) +
        ' · ' +
        plan.title +
        ' · ' +
        plan.note +
        '。待派工：' +
        (plan.items || ['执行个体照护计划']).join('、') +
        '。责任人：' +
        plan.assignee +
        '（' +
        (plan.assignmentSource || '人工指定') +
        '）。',
      fields: [],
      map: (v) => ({
        ...v,
        planId: plan.id,
      }),
      submitLabel: '确认并派发',
    });
  }
  const evaluationList = () =>
    table(ctx, {
      title: '评估记录',
      action:
        state.careScale && hasGrant(ctx, 'clinical', 'medical')
          ? btn(ctx, '标准量表评估', () => scaleForm(ctx))
          : null,
      rows: byRecent(state.assessments),
      search: personSearch(ctx, (r) => r.note),
      cols: [
        personCol(ctx),
        {
          label: '照护等级',
          view: (r) => r.level,
        },
        {
          label: '能力与需求',
          view: (r) =>
            named(
              r.note,
              Object.entries(r.observations || {})
                .map(([name, value]) => name + ' ' + value)
                .join(' · ')
            ),
        },
        {
          label: '负责人员',
          view: (r) => r.assignee,
        },
        {
          label: '评估日期',
          view: (r) => r.scale?.assessedOn || r.date,
        },
        {
          label: '下次复评',
          view: (r) => (r.historyOnly ? '历史补录' : r.reviewDate),
        },
        {
          label: '依据',
          view: (r) =>
            link(ctx, r.scale ? r.scale.total + ' 分 · 查看量表' : '查看记录', () =>
              evaluationDetails(ctx, r)
            ),
        },
      ],
    });
  const reviews = () =>
    table(ctx, {
      title: '复评安排',
      rows: byRecent(state.assessments)
        .filter(
          (r) =>
            r.reviewDate &&
            state.residents.some((p) => p.id === r.residentId && p.status === '在住')
        )
        .sort((a, b) => b.date.localeCompare(a.date))
        .filter((r, i, arr) => arr.findIndex((x) => x.residentId === r.residentId) === i)
        .sort((a, b) => a.reviewDate.localeCompare(b.reviewDate)),
      search: personSearch(ctx),
      cols: [
        personCol(ctx),
        {
          label: '上次评估',
          view: (r) => r.date,
        },
        {
          label: '预约复评',
          view: (r) => r.reviewDate,
        },
        {
          label: '计划状态',
          view: (r) =>
            r.reviewDate <= today(ctx)
              ? badge(ctx, '待复评', 'amber')
              : badge(ctx, '已安排', 'blue'),
        },
        {
          label: '负责人员',
          view: (r) => r.assignee,
        },
      ],
    });
  const plans = () =>
    table(ctx, {
      title: '照护方案',
      rows: byRecent(state.plans),
      search: personSearch(ctx, (r) => r.title),
      filter: statusFilter,
      cols: [
        personCol(ctx),
        {
          label: '计划',
          view: (r) => named(r.title, r.note),
        },
        {
          label: '负责人员',
          view: (r) => r.assignee,
        },
        {
          label: '状态',
          view: (r) => badge(ctx, r.status),
        },
        {
          label: '操作',
          align: 'end',
          view: (r) =>
            r.status === '待复核'
              ? link(ctx, '复核派发', () => approve(r))
              : link(ctx, '查看', () =>
                  ctx.detail(
                    '照护计划',
                    facts([
                      ['长者', residentName(ctx, r.residentId)],
                      ['计划', r.title],
                      ['内容', r.note],
                      ['状态', r.status],
                      ['复核人', r.reviewer],
                      ['复评日期', r.reviewDate],
                    ])
                  )
                ),
        },
      ],
    });
  return page(
    ctx,
    '评估与计划',
    '记录长者能力与服务需求，复核方案后派发照护工单。',
    btn(ctx, '登记评估', assess, 'primary'),
    tabs('assessments', [
      ['assess', '评估记录', evaluationList],
      ['plans', '照护计划', plans],
      ['review', '复评安排', reviews],
    ])
  );
}

export function taskForm(ctx) {
  runForm(ctx, {
    title: '新建照护任务',
    action: 'care.addTask',
    fields: [
      residentField(ctx),
      field('title', '任务名称'),
      staffField(ctx, 'assignee', '执行人员'),
      select('kind', '服务类型', options(['日常照护', '巡视', '康复服务', '膳食服务', '医嘱执行'])),
      select('routineActivity', '完成后时间线归类', [
        { value: 'auto', label: '按标准服务名称' },
        { value: 'water', label: '饮水照护' },
        { value: 'meal', label: '用餐陪护' },
        { value: 'separate', label: '单独展示' },
      ]),
      field('date', '执行日期', {
        type: 'date',
        value: today(ctx),
      }),
      field('time', '执行时间', {
        type: 'time',
        value: '09:00',
      }),
    ],
    submitLabel: '创建任务',
  });
}

export function completeTask(ctx, row) {
  const person = ctx.state.residents.find((r) => r.id === row.residentId);
  runForm(ctx, {
    title: '登记任务执行',
    action: 'care.completeTask',
    description: residentName(ctx, row.residentId) + ' · ' + row.title,
    fields: [
      field('bedId', '床位编号（选填）', {
        placeholder: person?.bedId || '',
        required: false,
      }),
      memo('note', '执行记录'),
    ],
    map: (v) => ({
      ...v,
      taskId: row.id,
    }),
    submitLabel: '确认完成',
  });
}

function quality(ctx, row) {
  runForm(ctx, {
    title: '登记服务抽检',
    action: 'care.quality',
    description: row.title,
    fields: [
      field('rating', '满意度（1–5 分）', {
        type: 'number',
        value: '5',
        min: 1,
        max: 5,
        step: 1,
      }),
      memo('note', '抽检记录', true),
    ],
    map: (v) => ({
      ...v,
      taskId: row.id,
    }),
  });
}

function serviceProof(ctx, id) {
  const task = ctx.state.tasks.find((r) => r.id === id);
  if (!task) return ctx.toast('工单已更新，请重新载入');
  const checks = (ctx.state.qualityChecks || []).filter((r) => r.taskId === id);
  ctx.detail(
    '服务凭证',
    node('div', 'fx-profile', [
      facts([
        ['工单编号', task.id],
        ['任务', task.title],
        ['服务对象', residentName(ctx, task.residentId)],
        ['执行人', task.operator || '未登记'],
        ['执行记录', task.note],
        ['床位核验', task.checkedBedId || '未登记'],
        [
          '实际完成',
          task.executedAt?.replace('T', ' ').slice(0, 19) || task.completedAt || '未登记',
        ],
        ['计划时间', task.date + ' ' + task.time],
      ]),
      section(
        '服务抽检',
        records(checks, (r) =>
          named(
            [r.source || '服务抽检', r.rating && r.rating + ' 分', r.note]
              .filter(Boolean)
              .join(' · '),
            r.reviewer,
          ),
        ),
      ),
      canAct(ctx, 'care.quality') ? btn(ctx, '登记抽检', () => quality(ctx, task)) : null,
    ]),
  );
}

function taskHistory(ctx) {
  const rows = ctx.state.tasks
    .filter((r) => r.status !== '已完成')
    .sort(
      (a, b) =>
        Number(b.date === today(ctx)) - Number(a.date === today(ctx)) ||
        b.date.localeCompare(a.date) ||
        a.time.localeCompare(b.time),
    );
  return table(ctx, {
    title: '待办工单',
    rows,
    search: personSearch(ctx, (r) => r.title + ' ' + r.assignee),
    filter: statusFilter,
    cols: [
      { label: '任务', view: (r) => named(r.title, r.kind) },
      personCol(ctx),
      { label: '计划时间', view: (r) => named(r.time, r.date) },
      { label: '责任人', view: (r) => r.assignee },
      { label: '状态', view: (r) => badge(ctx, r.status) },
      {
        label: '操作',
        align: 'end',
        view: (r) =>
          r.status === '待执行'
            ? r.date > today(ctx)
              ? '未到执行日'
              : link(ctx, '登记执行', () => completeTask(ctx, r))
            : '—',
      },
    ],
    empty: '没有符合条件的待办工单。',
  });
}

function vitalForm(ctx) {
  runForm(ctx, {
    title: '录入健康体征',
    action: 'care.vital',
    fields: [
      residentField(ctx),
      field('metric', '体征项目', {
        placeholder: '如体温、收缩压、脉搏',
      }),
      field('value', '测量值', {
        type: 'number',
        step: 'any',
      }),
      field('unit', '单位'),
      select('abnormal', '上报状态', [
        {
          value: 'false',
          label: '常规记录',
        },
        {
          value: 'true',
          label: '标记异常并上报',
        },
      ]),
      memo('note', '观察记录'),
    ],
    map: (v) => ({
      ...v,
      abnormal: v.abnormal === 'true',
    }),
  });
}

function vitals(ctx) {
  return table(ctx, {
    title: '体征记录',
    rows: byRecent(ctx.state.vitals),
    search: personSearch(ctx, (r) => r.metric),
    filter: statusFilter,
    action: btn(ctx, '录入体征', () => vitalForm(ctx)),
    cols: [
      personCol(ctx),
      {
        label: '体征项目',
        view: (r) => r.metric,
      },
      {
        label: '测量结果',
        view: (r) => r.value + ' ' + (r.unit || ''),
      },
      {
        label: '日期',
        view: (r) => r.date,
      },
      {
        label: '状态',
        view: (r) => badge(ctx, r.status),
      },
      {
        label: '操作',
        align: 'end',
        view: (r) =>
          r.status === '待复核'
            ? link(ctx, '记录处理', () =>
                runForm(ctx, {
                  title: '处理异常上报',
                  action: 'care.resolveVital',
                  fields: [memo('note', '处理记录', true)],
                  map: (v) => ({
                    ...v,
                    vitalId: r.id,
                  }),
                })
              )
            : link(ctx, '查看', () =>
                ctx.detail(
                  '体征记录',
                  facts([
                    ['长者', residentName(ctx, r.residentId)],
                    ['项目', r.metric],
                    ['测量结果', r.value + ' ' + (r.unit || '')],
                    ['状态', r.status],
                    ['记录人', r.operator],
                    ['记录', r.note],
                    ['处理记录', r.resolution || r.resolutionNote],
                  ])
                )
              ),
      },
    ],
  });
}

export function care(ctx) {
  return page(
    ctx,
    '照护服务',
    canAct(ctx, 'care.addTask') ? '执行照护工单并登记班次交接。' : '登记体征测量与异常处理结果。',
    canAct(ctx, 'care.addTask') ? btn(ctx, '新建任务', () => taskForm(ctx), 'primary') : null,
    tabs('care', [
      ...(canAct(ctx, 'care.completeTask') ? [
        ['tasks', '照护工单', () => taskHistory(ctx)],
        ['completed', '已完成服务', () => careTimeline(ctx, 'work', '', (id) => serviceProof(ctx, id))],
      ] : []),
      ...(canAct(ctx, 'care.vital') ? [['vitals', '健康体征', () => vitals(ctx)]] : []),
      ...(canAct(ctx, 'care.screen')
        ? [
            ['followups', '筛查与随访', () => followups(ctx)],
            ['referrals', '院外衔接', () => referrals(ctx)],
          ]
        : []),
      ...(canAct(ctx, 'care.handover') ? [['handover', '班次交接', () => handovers(ctx)]] : []),
    ])
  );
}

export function medications(ctx) {
  function create() {
    runForm(ctx, {
      title: '登记用药计划',
      action: 'care.addMedication',
      description: '按现有医嘱录入，保存后进入人工复核。',
      fields: [
        residentField(ctx),
        field('name', '药品名称'),
        memo('instruction', '医嘱与执行说明', true),
        field('scheduledAt', '本次医嘱给药时间（上海）', {
          type: 'datetime-local',
          required: false,
        }),
        staffField(ctx, 'assignee', '负责人员', {
          required: false,
        }),
        memo('interactionNote', '医护人员登记的配伍提醒'),
      ],
      submitLabel: '提交复核',
    });
  }
  function review(r) {
    runForm(ctx, {
      title: '复核用药计划',
      action: 'care.reviewMedication',
      description: [residentName(ctx, r.residentId), r.name, r.instruction, ...r.warnings].join(
        ' · '
      ),
      fields: [
        memo(
          'note',
          r.warnings.length ? '筛查提醒的核实结果' : '复核意见',
          Boolean(r.warnings.length)
        ),
      ],
      map: (v) => ({
        ...v,
        medicationId: r.id,
      }),
      submitLabel: '确认复核',
    });
  }
  function execute(r) {
    runForm(ctx, {
      title: '记录给药执行',
      action: 'care.giveMedication',
      description: [
        residentName(ctx, r.residentId),
        r.name,
        r.instruction,
        r.scheduledAt && '计划给药 ' + r.scheduledAt.replace('T', ' '),
        ...r.warnings,
      ]
        .filter(Boolean)
        .join(' · '),
      fields: [memo('executionNote', '实际执行补充（例如计划时刻变动）')],
      map: (v) => ({
        ...v,
        medicationId: r.id,
      }),
      submitLabel: '确认执行',
    });
  }
  return page(
    ctx,
    '用药管理',
    '登记既有医嘱，查看筛查提醒并保留复核、执行凭证。',
    btn(ctx, '登记用药计划', create, 'primary'),
    tabs('medications', [
      [
        'orders',
        '用药台账',
        () =>
          table(ctx, {
            title: '用药台账',
            rows: byRecent(ctx.state.medications),
            search: personSearch(ctx, (r) => r.name),
            filter: statusFilter,
            cols: [
              personCol(ctx),
              {
                label: '药品',
                view: (r) => named(r.name, r.instruction),
              },
              {
                label: '筛查提醒',
                view: (r) =>
                  r.warnings.length ? badge(ctx, r.warnings.length + ' 项提醒', 'amber') : '—',
              },
              {
                label: '负责人员',
                view: (r) => r.assignee || '—',
              },
              {
                label: '状态',
                view: (r) => badge(ctx, r.status),
              },
              {
                label: '操作',
                align: 'end',
                view: (r) =>
                  r.status === '待复核'
                    ? link(ctx, '复核', () => review(r))
                    : r.status === '待执行'
                      ? link(ctx, '登记执行', () => execute(r))
                      : link(ctx, '查看凭证', () =>
                          ctx.detail(
                            '用药凭证',
                            facts([
                              ['长者', residentName(ctx, r.residentId)],
                              ['药品', r.name],
                              ['医嘱', r.instruction],
                              ['筛查提醒', r.warnings.join('、')],
                              ['审核意见', r.note],
                              ['复核人', r.reviewer],
                              ['执行人', r.operator],
                              ['执行补充', r.executionNote],
                              ['计划给药时间', r.scheduledAt?.replace('T', ' ')],
                              ['执行登记时间', (r.executedTime || r.executedAt)?.replace('T', ' ')],
                              [
                                '核查历史',
                                (r.reviews || [])
                                  .map((v) =>
                                    [v.date, v.reviewer, ...v.warnings, v.note]
                                      .filter(Boolean)
                                      .join(' · ')
                                  )
                                  .join('；'),
                              ],
                              ['状态', r.status],
                            ])
                          )
                        ),
              },
            ],
          }),
      ],
      ['reminders', '定时提醒', () => medicationReminders(ctx, execute)],
      ['rules', '配伍规则', () => drugRules(ctx)],
    ])
  );
}
