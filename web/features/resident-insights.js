import { residentLabel } from './people-labels.js';
import { node, choose, btn, badge, field, select, hasGrant, today } from './shared.js';

const modes = { inherit: '跟随机构', auto: '定时生成', manual: '手动生成' };
const evidenceTypes = {
  task: '照护工单',
  vital: '体征记录',
  reviewedCough: '已复核咳嗽观察',
  resident: '长辈档案',
  groupActivity: '活动出席确认',
  reviewedFall: '跌倒现场核实记录',
};
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

function evidenceList(items, empty, includeSources = true) {
  if (!items.length) return node('p', 'fx-muted', empty);
  return node(
    'div',
    'rounds-findings',
    items.map((item) => {
      const list = item.evidence || [];
      return node('div', 'rounds-paragraph', [
        node('p', '', item.text),
        includeSources && list.length
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

function observationForm(ctx, name, url, submit) {
  ctx.dialog({
    title: '登记已核实的咳嗽观察',
    description:
      '请核实声音属于这位长辈。每人每小时登记一个合计；多人房间来源不明的声音请保留在设备端。',
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
          target: name,
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

function dayHeading(ctx, date) {
  const current = today(ctx);
  const yesterday = new Date(Date.parse(current + 'T12:00:00Z') - 86400000).toISOString().slice(0, 10);
  const label = new Intl.DateTimeFormat('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai',
  }).format(new Date(date + 'T12:00:00+08:00'));
  const relative = date === current ? '今天' : date === yesterday ? '昨天' : '';
  return node('h4', '', [node('time', '', label), relative ? node('small', '', relative) : null]);
}

export function residentDailyReadOnly(ctx, residentId) {
  const panel = node('section', 'rounds-card');
  const heading = node('h3', '', '我这两天的生活');
  panel.append(heading, node('p', 'fx-muted', '正在读取生活简报…'));
  async function read() {
    try {
      const report = await ctx.get('/api/residents/' + encodeURIComponent(residentId) + '/personal-brief');
      const rows = report.paragraphs || [];
      const days = [...new Set(rows.map(r => r.day))].sort().reverse();
      panel.replaceChildren(heading, ...days.map(day => node('section', 'rounds-life-day', [
        dayHeading(ctx, day), ...rows.filter(r => r.day === day).map(r => node('p', '', r.text)),
      ])));
      if (!days.length) panel.append(node('p', 'fx-muted', '暂时还没有可查看的生活简报。'));
      else panel.append(node('small', 'fx-muted', '简报由 AI 根据已核实的记录整理。如有疑问，可向护理人员核对。'));
    } catch (error) {
      panel.replaceChildren(heading, node('p', 'fx-muted', error.message), btn(ctx, '重新读取', read));
    }
  }
  read();
  return panel;
}

export function residentInsights(ctx, residentId, {compact = false} = {}) {
  const box = node('section', compact ? 'rounds-card resident-brief-card' : 'rounds-card');
  box.dataset.roundsResidentId = residentId;
  const url = '/api/rounds/residents/' + encodeURIComponent(residentId);
  const name = residentLabel(ctx, residentId);
  let info,
    busy = false;
  async function load() {
    try {
      info = await ctx.get(url);
      draw();
    } catch (e) {
      box.replaceChildren(node('h3', '', '近期变化与建议'), node('p', 'fx-muted', e.message));
      if (!compact) box.append(btn(ctx, '重新加载', load));
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
          '这位长辈的简报',
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
              ? (report.source === 'deepseek' ? '健康助理' : '历史巡查记录') + ' · ' + localStamp(report.generatedAt)
              : '尚未生成巡查简报',
          ),
        ]),
      ]),
      compact ? null : badge(ctx, modes[info.effectiveMode], 'blue'),
    ]);
    const controls = compact ? null : choose(
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
                    ['依据', '这位长辈今天和昨天的用餐、活动和个人观察记录'],
                    ['生成内容', '按日期整理，保留每段的来源'],
                  ],
                },
              ),
            'primary',
          )
        : null,
      info.canConfigure ? btn(ctx, '生成设置', configure) : null,
      info.canObserve
        ? btn(ctx, '登记观察', () => observationForm(ctx, name, url, submit))
        : null,
    );
    const contents = [];
    const currentFormat = report?.format === 'daily-life-v2';
    if (currentFormat) {
      const dates = [...new Set(report.changes.map(row => row.day))].sort().reverse();
      for (const date of dates) {
        const rows = report.changes.filter(row => row.day === date);
        contents.push(node('section', 'rounds-life-day', [
          dayHeading(ctx, date),
          evidenceList(rows, '', !compact),
        ]));
      }
      if (report.suggestions.length) contents.push(node('section', 'rounds-life-advice', [
        node('h4', '', '接下来留意'), evidenceList(report.suggestions, '', !compact),
      ]));
      if (!contents.length) contents.push(node('p', 'fx-muted', '最近两天暂无可展示的生活记录。'));
    } else {
      contents.push(node('p', 'rounds-empty', compact
        ? '最近两天暂无可展示的生活简报。' : report
        ? '这份简报来自旧版护理统计。点击「更新简报」，即可查看近期的生活记录。'
        : '生成后可查看最近两天已记录的起居、三餐和活动。'));
    }
    if (!compact && currentFormat && report.cough?.noticeable) {
      const c = report.cough;
      contents.push(
        node('details', 'rounds-observation', [
          node(
            'summary',
            '',
            '查看咳嗽变化的观察依据',
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
    if (!compact && currentFormat && report.today.pending && info.canGenerate && hasGrant(ctx, 'assistants') && hasGrant(ctx, 'care')) {
      const extra = node('details', 'rounds-handoff', [node('summary', '', '护理交班工具')]);
      extra.addEventListener('toggle', () => {
        if (extra.open && extra.childElementCount === 1) extra.append(priorityPanel(ctx, url, report, () => info.revision, load));
      });
      contents.push(extra);
    }
    box.replaceChildren(
      head, ...contents, ...(controls ? [controls] : []),
      node('p', 'rounds-warning', [
        ctx.ui.icon('shield', 16),
        'AI 可能出错。请核对原始记录；诊断、用药和治疗决定须由医护人员作出。',
      ]),
    );
  }
  box.append(node('h3', '', '近期变化与建议'), node('p', 'fx-muted', '正在读取巡查简报…'));
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
        node('strong', '', 'AI 建议核对顺序'),
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
            ? '排序已提交，可稍后重新打开简报查看。'
            : '本次未取得可用的排序建议。原始巡查简报仍可查看。',
        ),
      );
    } else if (saved.available) {
      const button = btn(
        ctx,
        '生成核对顺序建议',
        async () => {
          button.disabled = true;
          try {
            const result = await roundsWrite(
              ctx,
              path,
              { reportId: report.id, confirmed: true },
              revision(),
              {
                title: '生成核对顺序建议',
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
