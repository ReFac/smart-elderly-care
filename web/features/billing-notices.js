import { residentAnchor, residentLabel } from './people-labels.js';
import { link, money, named, table } from './shared.js';

export function billingNotices(ctx, openBill) {
  const family = ctx.state.user.kind === 'family';
  const people = family ? [] : [
    { label: '长者', view: (r) => residentAnchor(ctx, r.residentId) }
  ];
  const finance = family ? [] : [
    { label: '本次冲抵', align: 'end', view: (r) => r.amount != null ? money(r.amount) : '—' },
    ...(openBill ? [{
      label: '操作',
      align: 'end',
      view: (r) => {
        const bill = (ctx.state.bills || []).find((line) => line.id === r.billId);
        return bill ? link(ctx, '查看账单', () => openBill(bill)) : null;
      }
    }] : [])
  ];
  return table(ctx, {
    title: '缴费提醒',
    rows: ctx.state.billingNotices || [],
    empty: '暂时没有缴费提醒。',
    search: family ? null : {
      placeholder: '搜索长者或账单日',
      value: (r) => residentLabel(ctx, r.residentId) + ' ' + r.billingDate
    },
    filter: family ? null : { label: '筛选提醒类型', all: '全部类型', value: (r) => r.title },
    cols: [
      ...people,
      { label: '提醒', view: (r) => named(r.title, r.message) },
      { label: '约定账单日', view: (r) => r.billingDate },
      { label: '提醒日期', view: (r) => r.date },
      ...finance,
    ],
  });
}
