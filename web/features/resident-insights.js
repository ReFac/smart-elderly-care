import { node, choose, btn, badge, field, select, hasGrant, today } from './shared.js';

const modes = { inherit: '跟随机构', auto: '定时生成', manual: '手动生成' };
const evidenceTypes = {
  task: '照护工单',
  vital: '体征记录',
  reviewedCough: '已复核咳嗽观察',
  resident: '长者档案',
};
const labels = [
  ['planned', '计划'],
  ['completed', '已完成'],
  ['pending', '待执行'],
  ['overdue', '已过时'],
];
export const localStamp = (value) =>
  value
    ? new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(new Date(value))
    : '尚无记录';

export async function roundsWrite(ctx, url, data, revision, review) {
  const answer = await ctx.confirmChange({ allowComment: true, ...review });
  if (!answer) return null;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...data, revision, comment: answer.comment || '' }),
  });
  const result = await res.json();
  if (!res.ok) throw new Error(result.error || '保存失败，请刷新后重试');
  return result;
}

export function taskTotals(values) {
  return node(
    'dl',
    'rounds-counts',
    labels.map(([key, title]) =>
      node('div', key === 'overdue' && values[key] ? 'rounds-overdue' : '', [
        node('dt', '', title),
        node('dd', '', String(values[key] ?? '—')),
      ]),
    ),
  );
}

function evidenceList(items, empty) {
  if (!items.length) return node('p', 'fx-muted', empty);
  return node(
    'ul',
    'rounds-findings',
    items.map((item) => {
      const list = item.evidence || [];
      return node('li', '', [
        node('p', '', item.text),
        list.length
          ? node('details', 'rounds-evidence', [
              node('summary', '', '查看依据（' + list.length + '）'),
              node(
                'ul',
                '',
                list.map((e) =>
                  node(
                    'li',
                    '',
                    [e.date, evidenceTypes[e.kind] || '记录', e.id].filter(Boolean).join(' · '),
                  ),
                ),
              ),
            ])
          : null,
      ]);
    }),
  );
}

function observationForm(ctx, info, url, submit) {
  ctx.dialog({
    title: '登记已核实的咳嗽观察',
    description:
      '请核实声音属于这位长者。每人每小时登记一个合计；多人房间来源不明的声音请保留在设备端。',
    fields: [
      field('day', '观察日期', { type: 'date', value: today(ctx), max: today(ctx) }),
      field('hour', '观察小时（北京时间 0–23）', { type: 'number', min: 0, max: 23 }),
      field('observedMinutes', '该小时实际观察分钟', { type: 'number', min: 1, max: 60 }),
      field('count', '复核后的咳嗽事件数', { type: 'number', min: 0, max: 3600 }),
      field('source', '稳定的设备或观察来源标识', {
        maxLength: 80,
        placeholder: '例如 yamnet:随身设备01:0.50，沿用相同来源及阈值',
      }),
      select('attribution', '个人归属依据', [
        { value: '', label: '请选择已核实的依据' },
        { value: 'wearable', label: '个人佩戴设备并已复核' },
        { value: 'staff-verified', label: '工作人员现场核实' },
      ]),
    ],
    submitLabel: '复核并登记',
    onSubmit: async (v) => {
      const data = {
        ...v,
        hour: Number(v.hour),
        count: Number(v.count),
        observedMinutes: Number(v.observedMinutes),
        reviewed: true,
      };
      return Boolean(
        await submit(url + '/observations', data, {
          title: '确认个人观察记录',
          target: info.name,
          fields: [
            [
              '归属依据',
              v.attribution === 'wearable' ? '个人佩戴设备并已复核' : '工作人员现场核实',
            ],
            ['观察时段', v.day + ' ' + v.hour + ' 时，覆盖 ' + v.observedMinutes + ' 分钟'],
            ['咳嗽事件', v.count + ' 次'],
            ['来源', v.source],
          ],
        }),
      );
    },
  });
}

export function residentInsights(ctx, residentId) {
  const box = node('section', 'rounds-card');
  box.dataset.roundsResidentId = residentId;
  const url = '/api/rounds/residents/' + encodeURIComponent(residentId);
  const name = ctx.state.residents?.find((r) => r.id === residentId)?.name || '该长者';
  let info,
    busy = false;
  async function load() {
    try {
      info = await ctx.get(url);
      draw();
    } catch (e) {
      box.replaceChildren(node('p', 'fx-muted', e.message), btn(ctx, '重新加载', load));
    }
  }
  async function submit(path, data, review) {
    if (busy) return false;
    busy = true;
    try {
      const result = await roundsWrite(ctx, path, data, info.revision, review);
      if (!result) return false;
      await load();
      ctx.toast(result.changed === false ? '当前资料已是最新' : '已保存');
      return true;
    } catch (e) {
      ctx.toast(e.message);
      await load();
      return false;
    } finally {
      busy = false;
    }
  }
  function configure() {
    ctx.dialog({
      title: '设置巡查生成方式',
      fields: [
        select(
          'mode',
          '这位长者的简报',
          Object.entries(modes).map(([value, label]) => ({ value, label })),
          { value: info.mode },
        ),
      ],
      onSubmit: (v) =>
        submit(url + '/mode', v, {
          title: '更改巡查生成方式',
          target: name,
          fields: [
            ['原设置', modes[info.mode]],
            ['新设置', modes[v.mode]],
          ],
        }),
    });
  }
  function draw() {
    const report = info.latest;
    const head = node('header', 'rounds-heading', [
      node('div', 'rounds-identity', [
        ctx.ui.icon('spark', 22),
        node('div', '', [
          node('h3', '', '近期变化与建议'),
          node(
            'small',
            'fx-muted',
            report
              ? (report.source === 'deepseek' ? 'AI 助理' : '历史巡查记录') + ' · ' + localStamp(report.generatedAt)
              : '尚未生成巡查简报',
          ),
        ]),
      ]),
      badge(ctx, modes[info.effectiveMode], 'blue'),
    ]);
    const controls = choose(
      info.canGenerate
        ? btn(
            ctx,
            report ? '更新简报' : '生成简报',
            () =>
              submit(
                url + '/generate',
                {},
                {
                  title: '生成巡查简报',
                  target: name,
                  fields: [
                    ['依据', '最新照护工单及获授权的已复核观察'],
                    ['执行', '由 AI 助理生成简报，保留资料依据'],
                  ],
                },
              ),
            'primary',
          )
        : null,
      info.canConfigure ? btn(ctx, '生成设置', configure) : null,
      info.canObserve
        ? btn(ctx, '登记观察', () => observationForm(ctx, { name }, url, submit))
        : null,
    );
    const contents = report
      ? [
          node('div', 'rounds-day', [
            node('strong', '', report.day === today(ctx) ? '今日状况' : '最近一次状况'),
            node('time', '', report.day),
          ]),
          taskTotals(report.today),
          node('div', 'rounds-columns', [
            node('section', '', [
              node('h4', '', '近期变化'),
              evidenceList(report.changes, '当前简报暂无新的已核实变化。'),
            ]),
            node('section', '', [
              node('h4', '', '近期建议'),
              evidenceList(report.suggestions, '现有记录未产生待核对建议。'),
            ]),
          ]),
        ]
      : [node('p', 'rounds-empty', '尚无巡查简报。生成后可查看今日工单、近期变化及核对依据。')];
    if (report?.cough) {
      const c = report.cough;
      contents.push(
        node('details', 'rounds-observation', [
          node(
            'summary',
            '',
            '个人咳嗽趋势 · ' +
              {
                elevated: '高于近期基线，待核对',
                stable: '未高于近期基线',
                insufficient: '可比数据不足',
              }[c.status],
          ),
          node(
            'p',
            '',
            '本日纳入 ' +
              c.observedMinutes +
              ' 分钟，' +
              c.count +
              ' 次；历史可比 ' +
              c.historyDays +
              ' 天。',
          ),
          c.baseline != null
            ? node('p', '', '本日 ' + c.rate + ' 次/小时，历史中位数 ' + c.baseline + ' 次/小时。')
            : null,
          node('small', 'fx-muted', c.coverageNote),
          btn(
            ctx,
            '查看逐小时观察记录',
            async () => {
              try {
                const response = await ctx.get(url + '/observations');
                ctx.detail(
                  '逐小时观察记录',
                  node('div', 'fx-profile', [
                    node(
                      'p',
                      'fx-muted',
                      '北京时间 · ' + response.since + ' 至 ' + response.through,
                    ),
                    ...response.rows.map((row) =>
                      node('section', 'fx-section', [
                        node('h3', '', row.day + ' ' + String(row.hour).padStart(2, '0') + ' 时'),
                        node(
                          'p',
                          '',
                          '已核对 ' + row.count + ' 次 · 实际观察 ' + row.observedMinutes + ' 分钟',
                        ),
                        node(
                          'small',
                          'fx-muted',
                          row.source +
                            ' · ' +
                            (row.attribution === 'wearable' ? '个人佩戴设备' : '工作人员现场核实') +
                            ' · 复核 ' +
                            localStamp(row.reviewedAt),
                        ),
                      ]),
                    ),
                    response.rows.length ? null : node('p', 'fx-muted', '此时段暂无个人复核记录。'),
                  ]),
                );
              } catch (e) {
                ctx.toast(e.message);
              }
            },
            'ghost',
          ),
        ]),
      );
    }
    if (report && info.canGenerate && hasGrant(ctx, 'assistants') && hasGrant(ctx, 'care')) {
      contents.push(priorityPanel(ctx, url, report, () => info.revision, load));
    }
    box.replaceChildren(
      head,
      ...contents,
      controls,
      node('p', 'rounds-warning', [
        ctx.ui.icon('shield', 16),
        'AI 可能出错。请核对原始记录；诊断、用药和治疗决定须由医护人员作出。',
      ]),
    );
  }
  box.append(node('p', 'fx-muted', '正在读取巡查简报…'));
  load();
  return box;
}

function priorityPanel(ctx, url, report, revision, reload) {
  const area = node('div', 'rounds-cloud');
  const path = url + '/priorities';
  async function show() {
    let saved;
    try {
      saved = await ctx.get(path + '?reportId=' + encodeURIComponent(report.id));
    } catch {
      return;
    }
    if (saved.items?.length) {
      area.replaceChildren(
        node('strong', '', 'DeepSeek 建议核对顺序'),
        node(
          'ol',
          '',
          saved.items.map((x) => node('li', '', x)),
        ),
        node('small', 'fx-muted', saved.model + ' · ' + localStamp(saved.generatedAt)),
      );
    } else if (saved.status) {
      area.replaceChildren(
        node(
          'small',
          'fx-muted',
          saved.status === 'pending'
            ? 'DeepSeek 排序已提交，可稍后重新打开简报查看。'
            : '本次未取得可用的 DeepSeek 排序。原始巡查简报仍可查看。',
        ),
      );
    } else if (saved.available) {
      const button = btn(
        ctx,
        '请 DeepSeek 排列核对顺序',
        async () => {
          button.disabled = true;
          try {
            const result = await roundsWrite(
              ctx,
              path,
              { reportId: report.id, confirmed: true },
              revision(),
              {
                title: '请 DeepSeek 排列核对顺序',
                target: '本次巡查简报',
                fields: [
                  ['发送内容', '仅发送待办类别代号，姓名、病历、录音和工单正文留在院内'],
                  ['费用', '使用机构 AI 套餐，本报告的相同请求只计一次'],
                ],
                confirmLabel: '确认并调用',
              },
            );
            if (result) await reload();
          } catch (e) {
            ctx.toast(e.message);
          } finally {
            button.disabled = false;
          }
        },
        'ghost',
      );
      area.replaceChildren(button);
    }
  }
  show();
  return area;
}
