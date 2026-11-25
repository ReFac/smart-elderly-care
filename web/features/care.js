import { openScheduledMeal } from './scheduled-meals.js';
import { scheduledWork } from './scheduled-work.js';
import { medicationRoundDesk } from './med-rounds.js';
import { receivingDesk } from './medication-receiving.js';
import { residentAnchor, staffLabel } from './people-labels.js';
import { careTimeline } from './care-timeline.js';
import { openExamMedications } from './medication-reports.js';
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
  choose,
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
import { openCarePlan } from './care-plan-editor.js';
import { riskDesk } from './risk-reports.js';
import { followups, referrals } from './care-pathway.js';
import { medicationReminders, drugRules } from './medication-rules.js';
import { levels } from './residency.js';
import { createHandover, handovers, showHandover } from './handovers.js';
import { groupActivities } from './group-activities.js';
import { assessmentStages, healthDesk, ledgerDigest } from './care-workbench.js';

const personSearch = (ctx, extra) => ({
  placeholder: '搜索长辈或记录',
  value: (r) => residentName(ctx, r.residentId) + ' ' + (extra?.(r) || ''),
});

const statusFilter = {
  value: (r) => r.status,
};

const personCol = (ctx) => ({
  label: '长辈',
  view: (r) => residentAnchor(ctx, r.residentId),
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
  const canUseScale = state.careScale && hasGrant(ctx, 'clinical', 'medical');
  const currentResidents = new Map(state.residents.filter((r) => r.status === '在住').map((r) => [r.id, r]));
  const latest = new Map();
  const assessedOn = (r) => r.scale?.assessedOn || r.date;
  for (const row of byRecent(state.assessments).sort((a,b) => assessedOn(b).localeCompare(assessedOn(a)))) {
    if (!row.historyOnly && currentResidents.has(row.residentId) && !latest.has(row.residentId))
      latest.set(row.residentId, row);
  }
  const upcoming = [...latest.values()].filter((r) => r.reviewDate)
    .sort((a,b) => a.reviewDate.localeCompare(b.reviewDate));
  function assess(residentId = '') {
    runForm(ctx, {
      title: '登记能力评估',
      description: '填写评估人员确认的等级和服务需求，保存后生成照护计划草稿。',
      submitLabel: '保存评估并生成草稿',
      action: 'care.assess',
      fields: [
        residentField(ctx, { value: residentId }),
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
    const items = plan.serviceItems;
    const specs = items ? items.map(r=>[r.title, r.enabled ? [
      {once:'仅一次',daily:'每日',weekly:'每周'+['一','二','三','四','五','六','日'][r.weekday-1]}[r.period],
      r.count+' 次',r.times.length?r.times.join('、'):'不指定时点',r.assignee,r.roles.join('、'),
    ].join(' · ') : '停用']) : (plan.items||['执行个体照护计划']).map(title=>[title,'仅一次 · 09:00 · '+plan.assignee]);
    ctx.dialog({title:'复核照护计划',fields:[],description:residentName(ctx,plan.residentId)+' · '+plan.note,
      content:section('确认执行安排',facts(specs)),submitLabel:'确认并派发',
      onSubmit:()=>ctx.command('care.approvePlan',{planId:plan.id},{title:'审核照护计划并派发',target:plan.title,fields:specs})});
  }
  const evaluationList = () =>
    table(ctx, {
      title: '评估记录',
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
          view: (r) => staffLabel(ctx, r.assignee, r.assigneeId),
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
  const grading = () => table(ctx, {
    title: '在住长辈的最近一次等级判定',
    rows: [...latest.values()],
    search: personSearch(ctx, (row) => (row.scale?.gradeName || '') + ' ' + row.level),
    cols: [
      personCol(ctx),
      { label: '量表能力等级', view: (r) => r.scale?.gradeName || '未录入标准量表' },
      { label: '本次核定的照护等级', view: (r) => badge(ctx, r.level) },
      { label: '档案当前照护等级', view: (r) => currentResidents.get(r.residentId).level },
      { label: '评估日期', view: assessedOn },
      { label: '判定依据', align: 'end', view: (r) => link(ctx,'查看评估与依据',() => evaluationDetails(ctx,r)) },
    ],
    empty: '暂无可查看的在住长辈评估，可先登记新评估。',
  });
  const reviews = () =>
    table(ctx, {
      title: '复评安排',
      rows: upcoming,
      search: personSearch(ctx),
      cols: [
        personCol(ctx),
        {
          label: '上次评估',
          view: assessedOn,
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
          view: (r) => staffLabel(ctx, r.assignee, r.assigneeId),
        },
        {
          label: '办理', align: 'end',
          view: (r) => choose(
            link(ctx, '查看上次评估', () => evaluationDetails(ctx, r)),
            canAct(ctx, 'care.assess')
              ? link(ctx, '登记复评', () => canUseScale ? scaleForm(ctx, r.residentId) : assess(r.residentId))
              : null,
          ),
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
          view: (r) => staffLabel(ctx, r.assignee, r.assigneeId),
        },
        {
          label: '状态',
          view: (r) => badge(ctx, r.status),
        },
        {
          label: '操作',
          align: 'end',
          view: (r) => choose(
            canAct(ctx,'care.revisePlan') ? link(ctx, r.supersededBy ? '查看历史方案' : '调整计划', () => openCarePlan(ctx,r)) : null,
            r.status === '待复核' && canAct(ctx,'care.approvePlan') ? link(ctx,'复核派发',()=>approve(r)) :
              link(ctx,'计划详情',()=>ctx.detail('个性化照护方案',node('div','fx-profile',[
                facts([['计划',r.title],['状态',r.supersededBy?'已被后续方案替代':r.status],['说明',r.note],
                  ['复核人',staffLabel(ctx,r.reviewer)],['复评日期',r.reviewDate]]),
                section('照护项目',records(r.items||['执行个体照护计划'],item=>item)),
                link(ctx,'查看已派发照护工单',()=>ctx.go('care','tasks')),
              ])))
          ),
        },
      ],
    });
  return page(
    ctx,
    '评估与计划',
    '记录长辈能力与服务需求，复核方案后派发照护工单。',
    choose(
      btn(ctx, '登记照护观察', () => assess()),
      canUseScale ? btn(ctx, '标准量表评估', () => scaleForm(ctx), 'primary') : null,
    ),
    assessmentStages(ctx, {
      total: state.assessments.length, classified: latest.size,
      pendingPlans: state.plans.filter((r) => r.status === '待复核').length,
      dueReviews: upcoming.filter((r) => r.reviewDate <= today(ctx)).length,
    }),
    tabs('assessments', [
      ['assess', '评估记录', evaluationList],
      ['grading', '等级判定', grading],
      ['plans', '照护计划', plans],
      ['review', '复评安排', reviews],
      ...(hasGrant(ctx,'clinical') ? [['risk','专项风险档案',()=>riskDesk(ctx)]] : []),
    ])
  );
}

export function taskForm(ctx, proposal = null) {
  if (proposal && (ctx.state.tasks || []).some(row => row.assistantActionId === proposal.id && row.publisherId === ctx.state.user.id))
    return ctx.toast('这项建议已经发布，请查看照护工单');
  const config = {
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
  };
  if (!proposal) return runForm(ctx, config);
  return ctx.dialog({
    title: '填写照护工单', fields: [...config.fields, memo('note', '执行说明', false, { maxLength: 500 })],
    submitLabel: '核对发布',
    onSubmit: values => ctx.command('care.addTask', { ...values, assistantActionId: proposal.id }),
  });
}

export function completeTask(ctx, row) {
  if (row.occurrenceId && row.mealKind) return openScheduledMeal(ctx, { taskId: row.id });
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
        ['执行人', task.operator ? staffLabel(ctx, task.operator, task.operatorId) : '未登记'],
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
            staffLabel(ctx, r.reviewer),
          ),
        ),
      ),
      canAct(ctx, 'care.quality') ? btn(ctx, '登记抽检', () => quality(ctx, task)) : null,
    ]),
  );
}

function taskActionsAllowed(ctx, row) {
  const actor = ctx.state.user;
  const assignments = actor.role === '自定义' ? actor.staffDuties || [] : [actor.role];
  return row.status === '待执行' && row.date <= today(ctx) && canAct(ctx,'care.completeTask') &&
    (!row.allowedRoles?.length || actor.kind === 'owner' || assignments.some(a=>row.allowedRoles.includes(a)));
}

function taskSource(row) {
  if (row.planId) return '照护计划';
  if (row.occurrenceId) return '定时工单';
  if (row.assistantActionId) return '健康助理';
  return row.source || '照护工单';
}

export function taskDetail(ctx, row) {
  const body = node('div', 'fx-profile', [
    node('div', 'care-record-heading', [
      node('div', '', [node('small','',taskSource(row)), node('h2','',row.title)]),
      badge(ctx,row.status),
    ]),
    section('任务安排', facts([
      ['服务对象', residentAnchor(ctx, row.residentId)],
      ['服务类型', row.kind], ['计划执行', [row.date,row.time || '当日安排'].join(' ')],
      ['执行人员', staffLabel(ctx,row.assignee,row.assigneeId)],
      ['可执行岗位或职责', row.allowedRoles?.length ? row.allowedRoles.join('、') : '具备照护执行权限的人员'],
      ['工单编号', row.id],
    ])),
    section('执行说明',node('p','',row.note || '暂无补充说明')),
    row.cancellationReason ? section('终止原因',node('p','',row.cancellationReason)) : null,
  ]);
  const dialog = ctx.detail('照护工单详情',body);
  dialog.dataset.roundsResidentId = row.residentId;
  dialog.classList.add('care-record-drawer','desk-detail-drawer');
  if (taskActionsAllowed(ctx,row)) body.append(btn(ctx, row.mealKind ? '核对实际进食' : '登记执行', () => {
    dialog.close();
    completeTask(ctx,row);
  },'primary'));
}

function taskHistory(ctx) {
  const day = today(ctx);
  const rows = ctx.state.tasks.filter(r => r.status !== '已完成').sort((a,b) =>
    Number(b.status==='待执行') - Number(a.status==='待执行') ||
    a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''));
  const active = rows.filter(r => r.status === '待执行');
  const mine = r => r.assigneeId ? r.assigneeId === ctx.state.user.id : r.assignee === ctx.state.user.displayName;
  return node('div','care-register',[
    ledgerDigest([['今日待执行',active.filter(r=>r.date===day).length],
      ['往日未完成',active.filter(r=>r.date<day).length],
      ['分派给我',active.filter(mine).length],
      ['以后执行',active.filter(r=>r.date>day).length]]),
    table(ctx, {
      title: '待办工单', rows,
      search: personSearch(ctx, r => [r.title,r.assignee,r.kind,r.id,taskSource(r)].join(' ')),
      filter: {label:'工单范围',all:'全部工单',options:['今日待执行','往日未完成','分派给我',...new Set(rows.map(r=>r.status))],
        matches:(r,s)=>s==='今日待执行' ? r.status==='待执行'&&r.date===day : s==='往日未完成' ?
          r.status==='待执行'&&r.date<day : s==='分派给我' ? mine(r) : r.status===s},
      cols: [
        { label: '任务', view: r => named(r.title,r.kind) }, personCol(ctx),
        { label: '工单来源', view: taskSource },
        { label: '计划执行', view: r => named(r.date, r.time || '当日安排') },
        { label: '执行人员', view: r => staffLabel(ctx, r.assignee,r.assigneeId) },
        { label: '进度', view: r => badge(ctx,r.status==='待执行'&&r.date<day ? '逾期待执行' : r.status) },
        { label: '操作', align:'end', view: r => choose(
          link(ctx,'工单详情',()=>taskDetail(ctx,r)),
          taskActionsAllowed(ctx,r) ? link(ctx,'登记执行',()=>completeTask(ctx,r)) : null) },
      ],
      empty:'没有符合条件的待办工单。',
    }),
  ]);
}

export function vitalForm(ctx) {
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

function vitalDetail(ctx, row) {
  ctx.detail('体征与处置凭证', facts([
    ['长辈', residentAnchor(ctx, row.residentId)],
    ['体征项目', row.metric],
    ['测量结果', [row.value,row.unit].filter(Boolean).join(' ')],
    ['登记日期', row.date],
    ['状态', row.status],
    ['记录人', staffLabel(ctx, row.operator, row.operatorId)],
    ['观察记录', row.note],
    ['处置人', row.resolvedBy ? staffLabel(ctx, row.resolvedBy, row.resolvedById) : ''],
    ['处置日期', row.resolvedAt],
    ['处置记录', row.resolution || row.resolutionNote],
  ]));
}

function resolveVital(ctx, row) {
  runForm(ctx, {
    title: '记录异常处置', action: 'care.resolveVital',
    description: [residentName(ctx,row.residentId), row.metric, [row.value,row.unit].filter(Boolean).join(' '),row.note].filter(Boolean).join(' · '),
    fields: [memo('note', '核实与处置记录', true)],
    map: (values) => ({ ...values, vitalId: row.id }),
    submitLabel: '确认处置记录',
  });
}

function vitals(ctx) {
  return table(ctx, {
    title: '体征记录',
    rows: byRecent(ctx.state.vitals),
    search: personSearch(ctx, (r) => r.metric),
    filter: statusFilter,
    action: node('div', 'fx-actions', [btn(ctx, '录入体征', () => vitalForm(ctx)),
      btn(ctx, '体检用药自报', () => openExamMedications(ctx))]),
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
        view: (r) => choose(
          link(ctx, '查看凭证', () => vitalDetail(ctx,r)),
          r.status === '待复核' && canAct(ctx, 'care.resolveVital')
            ? link(ctx, '记录处置', () => resolveVital(ctx,r))
            : null,
        ),
      },
    ],
  });
}

export function care(ctx) {
  const showDesk = hasGrant(ctx, 'care', 'clinical');
  return page(
    ctx,
    '照护服务',
    canAct(ctx,'care.vital')
      ? '核对体征异常、交班和医嘱，查看各项业务凭证。'
      : canAct(ctx,'care.addTask') ? '执行照护工单、登记班次交接并查阅服务凭证。' : '',
    canAct(ctx, 'care.addTask') ? btn(ctx, '新建任务', () => taskForm(ctx), 'primary') : null,
    tabs('care', [
      ...(showDesk ? [['healthDesk', '健康工作台', () => healthDesk(ctx, {
        vitalForm: () => vitalForm(ctx),
        inspectVital: (row) => vitalDetail(ctx, row),
        resolveVital: (row) => resolveVital(ctx, row),
        inspectTask: row => taskDetail(ctx, row),
        createHandover: button => createHandover(ctx, button),
        showHandover: row => showHandover(ctx, row),
        openOrder: row => medicationWork(ctx).detail(row),
      })]] : []),
      ...(canAct(ctx, 'care.completeTask') ? [
        ['tasks', '照护工单', () => taskHistory(ctx)],
        ['completed', '已完成服务', () => careTimeline(ctx, 'work', '', (id) => serviceProof(ctx, id))],
      ] : []),
      ...(ctx.permitted('care') || ctx.permitted('clinical') || ctx.permitted('care.schedule')
        ? [['scheduledWork', '定时工单与批量派发', () => scheduledWork(ctx)]] : []),
      ...(canAct(ctx, 'care.confirmMedRound') ? [['medRounds', '服药核对', () => medicationRoundDesk(ctx)]] : []),
      ...(canAct(ctx, 'care.vital') ? [['vitals', '健康体征', () => vitals(ctx)]] : []),
      ...(canAct(ctx, 'care.proposeGroupActivity') || canAct(ctx, 'care.confirmGroupActivity')
        ? [['groupLife', '集体活动', () => groupActivities(ctx)]] : []),
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

export function medicationForm(ctx) {
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

export function medicationWork(ctx) {
  const warnings = (row) => row.warnings || [];
  function detail(row) {
    const body = node('div', 'fx-profile', [
      facts([
        ['长辈', residentAnchor(ctx, row.residentId)],
        ['药品', row.name],
        ['医嘱', row.instruction],
        ['状态', row.status],
        ['负责人员', staffLabel(ctx, row.assignee, row.assigneeId)],
        ['计划给药时间', row.scheduledAt?.replace('T', ' ')],
        ['复核人', staffLabel(ctx, row.reviewer)],
        ['审核意见', row.note],
        ['执行人', staffLabel(ctx, row.operator, row.operatorId)],
        ['执行登记时间', (row.executedTime || row.executedAt)?.replace('T', ' ')],
        ['执行补充', row.executionNote],
      ]),
      section('筛查提醒', records(warnings(row),(warning) => warning,'当前凭证没有筛查提醒')),
      section('核查历史', records(row.reviews || [], (entry) =>
        named([entry.date, staffLabel(ctx, entry.reviewer)].filter(Boolean).join(' · '),
          [...(entry.warnings || []), entry.note].filter(Boolean).join(' · ')))),
    ]);
    const dialog = ctx.detail('医嘱、核查与执行凭证',body);
    dialog.dataset.roundsResidentId = row.residentId;
    dialog.classList.add('care-record-drawer','desk-detail-drawer');
    if (row.status === '待复核' && canAct(ctx,'care.reviewMedication'))
      body.append(btn(ctx,'复核用药计划',()=>{dialog.close();review(row);},'primary'));
    if (row.status === '待执行' && canAct(ctx,'care.giveMedication'))
      body.append(btn(ctx,'登记给药执行',()=>{dialog.close();execute(row);},'primary'));
  }
  function review(r) {
    runForm(ctx, {
      title: '复核用药计划',
      action: 'care.reviewMedication',
      description: [residentName(ctx, r.residentId), r.name, r.instruction, ...warnings(r)].join(
        ' · '
      ),
      fields: [
        memo(
          'note',
          warnings(r).length ? '筛查提醒的核实结果' : '复核意见',
          Boolean(warnings(r).length)
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
        ...warnings(r),
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
  return { warnings, detail, review, execute };
}

export function medications(ctx) {
  const { warnings, detail, review, execute } = medicationWork(ctx);
  const orderAction = (row) => choose(
    link(ctx, '查看医嘱凭证', () => detail(row)),
    row.status === '待复核' && canAct(ctx, 'care.reviewMedication')
      ? link(ctx, '复核', () => review(row))
      : row.status === '待执行' && canAct(ctx, 'care.giveMedication')
        ? link(ctx, '登记执行', () => execute(row))
        : null,
  );
  return page(
    ctx,
    '用药管理',
    '登记既有医嘱，查看筛查提醒并保留复核、执行凭证。',
    btn(ctx, '登记用药计划', () => medicationForm(ctx), 'primary'),
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
                  warnings(r).length ? badge(ctx, warnings(r).length + ' 项提醒', 'amber') : '—',
              },
              {
                label: '负责人员',
                view: (r) => staffLabel(ctx, r.assignee, r.assigneeId) || '—',
              },
              {
                label: '状态',
                view: (r) => badge(ctx, r.status),
              },
              {
                label: '操作',
                align: 'end',
                view: orderAction,
              },
            ],
          }),
      ],
      ['reminders', '定时提醒', () => medicationReminders(ctx, execute)],
      ['receiving', '药品接收登记', () => receivingDesk(ctx)],
      ['safety', '筛查提醒', () => table(ctx, {
        title: '过敏、重复用药与配伍提醒',
        rows: byRecent(ctx.state.medications).filter((row) => warnings(row).length ||
          row.reviews?.some((review) => review.warnings?.length)),
        search: personSearch(ctx, (row) => row.name + ' ' + warnings(row).join(' ')),
        filter: statusFilter,
        cols: [
          personCol(ctx),
          { label: '药品与医嘱', view: (r) => named(r.name,r.instruction) },
          { label: '当前提醒', view: (r) => warnings(r).length ? warnings(r).join(' · ') : '查看历史核查' },
          { label: '状态', view: (r) => badge(ctx,r.status) },
          { label: '办理与追溯', align: 'end', view: orderAction },
        ],
        empty: '授权范围内暂无用药筛查提醒。',
      })],
      ['rules', '配伍规则', () => drugRules(ctx)],
    ])
  );
}
