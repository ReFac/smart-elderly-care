import { residentAnchor } from './people-labels.js';
import {
  btn,
  canAct,
  choose,
  facts,
  field,
  link,
  memo,
  money,
  named,
  node,
  options,
  records,
  residentName,
  runForm,
  select,
  table,
  today,
} from './shared.js';

import { checkoutAction } from './payment-qr.js';
import { importExpenses } from './expense-import.js';

const channels = ['微信支付', '支付宝'];
const amount = (value, max) =>
  field('amount', '金额（元）', { type: 'number', min: '0.01', step: '0.01', value, max });
const date = (ctx, key, label) =>
  field(key, label, { type: 'date', value: today(ctx), max: today(ctx) });

export function channelOrders(ctx) {
  const available = ctx.get('/api/payments/checkout/channels').then((data) => data.channels).catch(() => []);
  const bills = ctx.state.bills.filter((b) => b.balance > 0);
  const billField = select(
    'billId',
    '收费账单',
    bills.map((b) => ({
      value: b.id,
      label: residentName(ctx, b.residentId) + ' · ' + (b.billingDate || b.month) + (b.kind === 'trial' ? ' 试住费' : ' 月费') + ' · 待缴 ' + money(b.balance),
    }))
  );
  function issue() {
    runForm(ctx, {
      title: '生成商户订单',
      action: 'ops.paymentOrder',
      description: '机构已开通收款码的渠道可直接扫码，也可用商户订单号在机构收银系统结账。',
      fields: [billField, select('channel', '支付渠道', options(channels)), amount()],
    });
  }
  function manual(order) {
    const allBills = select(
      'billId',
      '原始账单',
      ctx.state.bills.map((b) => ({
        value: b.id,
        label: residentName(ctx, b.residentId) + ' · ' + b.month + ' · ' + b.id,
      }))
    );
    runForm(ctx, {
      title: '登记渠道对账凭证',
      action: 'ops.importReceipt',
      description: '请核对商户后台的成功交易。该凭证保留财务人工核对来源。',
      fields: [
        ...(order
          ? []
          : [
              allBills,
              select('channel', '支付渠道', options(channels)),
              field('merchantOrder', '商户订单号', { maxLength: 100 }),
              amount(),
            ]),
        field('transactionId', '渠道交易流水号', { maxLength: 100 }),
        date(ctx, 'paidDate', '实际到账日期'),
        field('source', '对账单或凭证编号', { maxLength: 160 }),
      ],
      map: (v) =>
        order
          ? {
              ...v,
              billId: order.billId,
              merchantOrder: order.id,
              channel: order.channel,
              amount: order.amount,
            }
          : v,
      submitLabel: '确认已到账',
    });
  }
  const orders = table(ctx, {
    title: '渠道订单',
    rows: ctx.state.paymentOrders || [],
    search: {
      placeholder: '搜索订单、账单或长辈',
      value: (r) => [r.id, r.billId, residentName(ctx, r.residentId)].join(' '),
    },
    filter: { value: (r) => r.status },
    action: choose(
      btn(ctx, '登记渠道对账凭证', () => manual()),
      btn(ctx, '生成商户订单', issue, 'primary')
    ),
    cols: [
      { label: '商户订单', view: (r) => named(r.id, r.channel) },
      { label: '长辈 / 账单', view: (r) => named(residentAnchor(ctx, r.residentId), r.billId) },
      { label: '应收金额', view: (r) => money(r.amount) },
      { label: '状态', view: (r) => r.status },
      {
        label: '操作',
        view: (r) => (r.status === '待支付' ? choose(checkoutAction(ctx, r, available), link(ctx, '核对到账', () => manual(r))) : r.date),
      },
    ],
  });
  const receipts = table(ctx, {
    title: '实收对账',
    rows: ctx.state.channelReceipts || [],
    search: {
      placeholder: '搜索渠道流水或商户订单',
      value: (r) => r.transactionId + ' ' + r.merchantOrder,
    },
    filter: { value: (r) => r.channel },
    cols: [
      { label: '渠道流水', view: (r) => named(r.transactionId, r.channel) },
      { label: '到账日期', view: (r) => r.paidDate },
      { label: '实收金额', view: (r) => money(r.amount) },
      { label: '核对方式', view: (r) => r.verification },
      {
        label: '凭证',
        view: (r) =>
          link(ctx, '查看凭证', () =>
            ctx.detail(
              '渠道实收凭证',
              facts([
                ['凭证号', r.id],
                ['账单号', r.billId],
                ['商户订单号', r.merchantOrder],
                ['交易流水号', r.transactionId],
                ['实收总额', money(r.amount)],
                ['机构承担手续费', r.feeAmount == null ? '历史凭证未记录' : money(r.feeAmount)],
                ['计算费率', r.feeRateBps == null ? '—' : (r.feeRateBps / 100).toFixed(2) + '%'],
                ['净入账', r.netAmount == null ? '历史凭证未记录' : money(r.netAmount)],
                ['核销本单', money(r.billAmount)],
                ['转入预交', money(r.depositAmount)],
                ['来源', r.verification],
                ['依据编号', r.source],
              ])
            )
          ),
      },
    ],
  });
  const channelGuide=node('details','fx-disclosure',[
    node('summary','fx-disclosure-head','收款码与顾客付款码'),
    node('div','fx-disclosure-body',[
      node('p','','已配置商户签约资料时，可在待支付订单中显示商户收款码。顾客在自己的微信或支付宝中扫码付款。'),
      node('p','','如需前台扫描顾客手机付款码，可签约微信付款码支付或支付宝当面付。该收银方式待机构开通及联调。'),
    ]),
  ]);
  return node('div', 'fx-page', [orders,receipts,channelGuide]);
}

export function expenseForm(ctx) {
  return runForm(ctx, {
    title: '登记已发生支出',
    action: 'ops.expense',
    fields: [
      date(ctx, 'date', '支出日期'),
      select('category', '分类', options(['照护耗材', '餐饮', '人力', '设施', '其他'])),
      amount(),
      field('voucher', '支出凭证号'),
      field('payee', '收款对象'),
      memo('note', '支出事由', true),
    ],
  });
}

export function expensePanel(ctx) {
  const rows = ctx.state.expenses || [];
  return table(ctx, {
    title: '机构支出凭证',
    rows,
    search: {
      placeholder: '搜索凭证、收款对象或用途',
      value: (r) => [r.voucher, r.payee, r.note, r.invoiceNo, r.transactionId].join(' '),
    },
    filter: { value: (r) => r.category },
    action: choose(
      canAct(ctx, 'ops.importExpenses') ? btn(ctx, '导入银行或电费凭证', () => importExpenses(ctx)) : null,
      btn(ctx, '登记支出', () => expenseForm(ctx)),
    ),
    cols: [
      { label: '日期', view: (r) => r.date },
      { label: '收款对象', view: (r) => named(r.payee, r.category) },
      { label: '事由', view: (r) => r.note },
      { label: '金额', view: (r) => money(r.amount) },
      { label: '凭证号', view: (r) => named(r.voucher, [r.invoiceNo, r.transactionId].filter((v) => v && v !== r.voucher).join(' · ')) },
      { label: '原件', view: (r) => !r.evidenceFiles?.length ? '—' : choose(...r.evidenceFiles.map((source) => {
        const a = node('a', 'btn btn-ghost', source.name);
        a.href = '/api/finance/expense-import/files/' + encodeURIComponent(source.id);
        a.download = source.name;
        return a;
      })) },
    ],
  });
}

export function reminders(ctx) {
  const rows = ctx.state.bills
    .filter((b) => b.balance > 0 && b.endDate && b.endDate < today(ctx))
    .sort((a, b) => a.endDate.localeCompare(b.endDate));
  return table(ctx, {
    title: '服务期已结束的未结账单',
    rows,
    empty: '当前没有到期仍欠费的账单',
    search: {
      placeholder: '搜索长辈或账期',
      value: (r) => residentName(ctx, r.residentId) + r.month,
    },
    cols: [
      { label: '长辈 / 账期', view: (r) => named(residentAnchor(ctx, r.residentId), r.month) },
      { label: '服务期末', view: (r) => r.endDate },
      { label: '待缴', view: (r) => money(r.balance) },
      { label: '最近跟进', view: (r) => r.reminders?.[0]?.date || '待跟进' },
      {
        label: '操作',
        view: (r) =>
          choose(
            link(ctx, '登记跟进', () =>
              runForm(ctx, {
                title: '登记催缴跟进',
                action: 'ops.remindBill',
                description:
                  residentName(ctx, r.residentId) + ' · ' + r.month + ' · ' + money(r.balance),
                fields: [
                  select('channel', '实际跟进方式', options(['电话', '当面', '机构消息'])),
                  memo('note', '已联系情况及跟进结果', true),
                ],
                map: (v) => ({ ...v, billId: r.id }),
              })
            ),
            link(ctx, '跟进历史', () =>
              ctx.detail(
                '催缴跟进记录',
                records(r.reminders || [], (x) =>
                  named(x.date + ' · ' + x.channel, x.note + ' · 当时待缴 ' + money(x.balance))
                )
              )
            )
          ),
      },
    ],
  });
}
