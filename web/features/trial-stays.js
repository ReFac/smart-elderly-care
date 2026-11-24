import { allocate, billingSchedule, bindContractFields, contractFields, isTrial, monthlyDayField } from './admission.js';
import { profile } from './residency.js';
import { trialLength, trialTermFields } from './trial-terms.js';
import { bedName, btn, canAct, choose, facts, field, link, memo, money, named, nextDay, node, section, select, table, today } from './shared.js';

export function confirmStay(ctx, person) {
  const day = today(ctx);
  const starts = person.trialEndsAt > day ? person.trialEndsAt : day;
  const dialog = ctx.dialog({
    title: '试住转正式入住',
    description: person.name + ' · ' + bedName(ctx, person.bedId) + ' · 正式月费从 ' + starts + ' 起算。',
    fields: [
      monthlyDayField(day, person.billingDay, '转正日'),
      ...contractFields(day, person.endDate || ''),
    ],
    submitLabel: '核对转正',
    onSubmit: ({ billingDay, contractTerm, endDate }) => {
      const payload = { residentId: person.id, billingDay: Number(billingDay), endDate: contractTerm === 'fixed' ? endDate : '' };
      return ctx.command('care.confirmStay', payload, {
        title: '确认试住转正式入住', target: person.name,
        fields: [
          ['床位', bedName(ctx, person.bedId)], ['月费起算日', starts], ['收费安排', billingSchedule(payload)],
          ['合同期限', payload.endDate || '无期限'],
        ], confirmLabel: '确认转正',
      });
    },
  });
  bindContractFields(dialog);
}

export async function endTrial(ctx, person) {
  try {
    const query = new URLSearchParams({ residentId: person.id });
    const { recipients } = await ctx.get('/api/care/trial-assignees?' + query);
    if (!recipients.length) return ctx.toast('当前分院没有可派发回访的员工，请先安排有权限的负责人。');
    ctx.dialog({
      title: '试住未转正 · 派发回访',
      description: person.name + ' · 确认后办理离院，释放床位并将回访任务发给所选员工。',
      fields: [
        memo('reason', '未转正原因', true),
        select('assigneeId', '回访负责人', [
          { value: '', label: '选择负责员工' },
          ...recipients.map((r) => ({ value: r.id, label: r.displayName + ' · ' + r.username })),
        ]),
        field('dueDate', '回访截止日', { type: 'date', min: today(ctx), value: nextDay(today(ctx)) }),
      ],
      submitLabel: '核对离院及回访',
      onSubmit: (v) => ctx.command('care.endTrial', { residentId: person.id, ...v }, {
        title: '确认试住离院并派发回访', target: person.name, confirmLabel: '确认离院并派发',
      }),
    });
  } catch (error) {
    ctx.toast(error.message);
  }
}

export function trialList(ctx) {
  const rows = ctx.state.residents.filter(isTrial).sort((a, b) => (a.trialEndsAt || '').localeCompare(b.trialEndsAt || ''));
  return table(ctx, {
    title: '试住中长者', rows,
    empty: '当前没有试住中的长者。',
    action: canAct(ctx, 'care.admit')
      ? btn(ctx, '选择档案办理试住', () => allocate(ctx, null, null, 'trial'), 'primary') : null,
    search: { placeholder: '搜索姓名或档案号', value: (r) => r.name + ' ' + r.id },
    cols: [
      { label: '长者', view: (r) => named(r.name, r.id) },
      { label: '床位', view: (r) => bedName(ctx, r.bedId) },
      { label: '试住安排', view: (r) => named(r.trialDays ? trialLength(r.trialDays) : '试住',
        [r.admittedAt, r.trialEndsAt].filter(Boolean).join(' 至 ')) },
      { label: '一次性试住费', view: (r) => r.trialPrice == null ? '—' : money(r.trialPrice) },
      { label: '操作', align: 'end', view: (r) => choose(
        link(ctx, '档案', () => profile(ctx, r)),
        canAct(ctx, 'care.confirmStay') ? link(ctx, '转正式', () => confirmStay(ctx, r)) : null,
        canAct(ctx, 'care.endTrial') ? link(ctx, '未转正离院', () => endTrial(ctx, r)) : null,
      ) },
    ],
  });
}

export function trialSettings(ctx) {
  const current = ctx.state.trialSettings;
  if (!current) return ctx.ui.empty('暂未取得试住设置');
  return section('试住默认约定', node('div', 'fx-profile', [
    facts([
      ['试住时长', trialLength(current.days)],
      ['一次性试住费', current.fee == null ? '在办理时填写' : money(current.fee)],
    ]),
    canAct(ctx, 'access.trialSettings') ? btn(ctx, '编辑试住设置', () => ctx.dialog({
      title: '编辑试住设置',
      description: '用于新办理的试住。经办人可在入住时按约定调整时长和总价。',
      fields: trialTermFields(current, { defaults: true }),
      onSubmit: ({ trialDays, trialPrice }) => {
        const fee = trialPrice === '' ? null : Number(trialPrice);
        return ctx.command('access.trialSettings', { days: Number(trialDays), fee }, {
          title: '保存试住默认约定', fields: [
            ['默认试住', trialLength(trialDays)],
            ['一次性试住费', fee == null ? '由经办人填写' : money(fee)],
          ],
        });
      },
    })) : null,
  ]));
}
