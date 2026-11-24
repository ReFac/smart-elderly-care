import { residentLabel, residentAnchor } from './people-labels.js';
import { node, btn, badge, records } from './shared.js';
import { localStamp, residentInsights, roundsWrite } from './resident-insights.js';

function input(type, value, attrs = {}) {
  const el = node('input');
  el.type = type;
  el.value = value;
  el.required = true;
  Object.assign(el, attrs);
  return el;
}
function choice(items, value) {
  const el = node('select');
  for (const [key, label] of items) el.add(new Option(label, key));
  el.value = value;
  return el;
}
const labeled = (text, el) => node('label', 'field', [node('span', '', text), el]);
const reasons = {
  pending: '今日待办',
  carry: '往日待办',
  vital: '体征待复核',
  cough: '咳嗽频率上升',
};

export function roundsSettings(ctx) {
  const box = node('section', 'rounds-settings');
  async function load() {
    try {
      const data = await ctx.get('/api/rounds/settings'),
        s = data.settings;
      const enabled = choice(
        [
          ['on', '启用定时巡查'],
          ['off', '暂停定时巡查'],
        ],
        s.enabled ? 'on' : 'off',
      );
      const mode = choice(
        [
          ['auto', '定时生成'],
          ['manual', '手动生成'],
        ],
        s.defaultMode,
      );
      const interval = input('number', s.intervalMinutes, { min: 5, max: 1440, step: 1 });
      const notify = input('time', s.notifyAt);
      const save = node('button', 'btn btn-primary', '保存巡查设置');
      save.type = 'submit';
      const form = node('form', 'rounds-config', [
        node('div', 'rounds-form-grid', [
          labeled('巡查状态', enabled),
          labeled('巡查间隔（分钟）', interval),
          labeled('长者默认生成方式', mode),
          labeled('每日站内提醒时间（北京时间）', notify),
        ]),
        node(
          'p',
          'fx-muted',
          '巡查服务在后台运行。每位长者可在档案内单独选择生成方式；家属的站内简报还需取得长者授权和家属订阅。',
        ),
        save,
      ]);
      form.onsubmit = async (e) => {
        e.preventDefault();
        save.disabled = true;
        try {
          const result = await roundsWrite(
            ctx,
            '/api/rounds/settings',
            {
              enabled: enabled.value === 'on',
              intervalMinutes: Number(interval.value),
              defaultMode: mode.value,
              notifyAt: notify.value,
            },
            data.revision,
            {
              title: '保存机构巡查设置',
              target: ctx.state.uiSettings.institutionName,
              fields: [
                ['状态', enabled.selectedOptions[0].text],
                ['巡查间隔', interval.value + ' 分钟'],
                ['默认生成', mode.selectedOptions[0].text],
                ['站内提醒', notify.value + ' 北京时间'],
              ],
            },
          );
          if (result) {
            await load();
            ctx.toast('巡查设置已保存');
          }
        } catch (err) {
          ctx.toast(err.message);
          await load();
        } finally {
          save.disabled = false;
        }
      };
      box.replaceChildren(
        node('div', 'rounds-card', [
          node('header', 'rounds-heading', [
            node('div', 'rounds-identity', [ctx.ui.icon('care', 23), node('h2', '', '定时巡查')]),
            badge(ctx, s.enabled ? '运行中' : '已暂停', s.enabled ? 'green' : 'neutral'),
          ]),
          node('div', 'rounds-schedule', [
            node('div', '', [
              node('small', '', '上次巡查'),
              node('strong', '', localStamp(s.lastRunAt)),
            ]),
            node('div', '', [
              node('small', '', '下次巡查'),
              node('strong', '', s.enabled ? localStamp(s.nextRunAt) : '已暂停'),
            ]),
          ]),
          form,
        ]),
      );
    } catch (e) {
      box.replaceChildren(node('p', 'fx-muted', e.message), btn(ctx, '重新加载', load));
    }
  }
  box.textContent = '正在读取巡查设置…';
  load();
  return box;
}

export function roundsInbox(ctx) {
  const panel = node('section', 'rounds-card');
  async function load() {
    try {
      const data = await ctx.get('/api/rounds/inbox');
      panel.replaceChildren(
        node('header', 'rounds-heading', [
          node('div', 'rounds-identity', [ctx.ui.icon('bell', 20), node('h2', '', '巡查提醒')]),
          btn(ctx, '刷新', load),
        ]),
        records(
          data.items,
          (item) =>
            node('div', 'rounds-inbox-row', [
              node('div', '', [
                node('strong', '', residentAnchor(ctx, item.residentId)),
                node(
                  'p',
                  '',
                  (item.signals || [])
                    .map((s) => reasons[s])
                    .filter(Boolean)
                    .join(' · '),
                ),
                node(
                  'p',
                  'fx-muted',
                  item.day +
                    ' · 待执行 ' +
                    item.today.pending +
                    ' 项 · 已过时 ' +
                    item.today.overdue +
                    ' 项',
                ),
                node('small', 'fx-muted', '送达 ' + localStamp(item.deliveredAt)),
              ]),
              btn(
                ctx,
                '查看近期简报',
                () =>
                  ctx.detail(
                    residentLabel(ctx, item.residentId) + ' · 巡查简报',
                    residentInsights(ctx, item.residentId),
                  ),
                'ghost',
              ),
            ]),
          '当前授权范围内暂无巡查提醒。到达机构设置的提醒时间后，有待跟进事项的长者会出现在这里。',
        ),
      );
    } catch (e) {
      panel.replaceChildren(node('p', 'fx-muted', e.message), btn(ctx, '重新加载', load));
    }
  }
  panel.textContent = '正在读取巡查提醒…';
  load();
  return panel;
}
