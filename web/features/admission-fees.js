import { admissionCollection } from './admission-collection.js';
import { chargesEditor, feeLedger, lineDescription } from './charge-lines.js';
import { btn, canAct, facts, field, money, node, section, select } from './shared.js';

const paymentModes = {
  standard: ['正常入住 · 已有足额预缴', '使用档案中已到账的预缴金核销首期费用。'],
  offline: ['线下款已收 · 登记后入住', '实际到款后填写。超出本次应缴的金额转入预缴金。'],
  qr: ['微信 / 支付宝 · 出示定额收款码', '由机构指定金额，收到支付渠道回执后核销。'],
  terminal: ['商户收银终端', '由收银终端调取定额订单，到账后自动入账。'],
  temporary: ['临时入住 · 欠费待缴', '建立待缴账单，可在入住交费中登记到账或使用商户收款二维码。'],
};
const offlineMethods = {
  现金: '线下登记',
  银行转账: '线下登记',
  银联刷卡: '线下刷卡登记',
};
const amountInCents = (value) => Math.round(Number(value || 0) * 100);

export function billingPolicyFields(
  { reminderDays = 3, securityMode = 'none', depositMonths = 1 } = {},
  { hideReminder = false } = {},
) {
  return [
    ...(!hideReminder ? [field('reminderDays', '出账前几天提醒', {
      type: 'number', min: 0, max: 30, step: 1, value: reminderDays,
    })] : []),
    select('securityMode', '逾期账单处理', [
      { value: 'none', label: depositMonths ? '押金单独保管' : '按约定提醒' },
      ...(depositMonths ? [{ value: 'overdue', label: '到期未交可动用押金，冲抵时提醒' }] : []),
    ], { value: securityMode }),
  ];
}

export function admissionFinanceFields(ctx) {
  const finance = canAct(ctx, 'ops.pay');
  return [
    ...(finance ? [
      select('depositMonths', '入住押金', Array.from({ length: 4 }, (_, value) => ({
        value: String(value), label: value === 0 ? '免押金' : '押 ' + value + ' 个月',
      })), { value: '1' }),
      ...billingPolicyFields(),
    ] : []),
    select('paymentMode', '本次收款确认', Object.entries(paymentModes)
      .filter(([value]) => ['standard','temporary'].includes(value) || finance)
      .map(([value, [label]]) => ({ value, label }))),
    ...(finance ? [
      field('offlineAmount', '线下实收金额（元）', { type: 'number', min: '0.01', max: 99999999, step: '0.01' }),
      select('offlineChannel', '线下付款渠道', Object.entries(offlineMethods)
        .map(([value, method]) => ({ value, label: method + '（' + value + '）' }))),
    ] : []),
  ];
}

function priceRequest(action, payload, revision) {
  return fetch('/api/care/admission/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, payload, revision }),
  }).then(async (response) => {
    const quote = await response.json();
    if (!response.ok) {
      const error = new Error(quote.error || '暂时无法核算入住费用，请重试。');
      error.status = response.status;
      throw error;
    }
    return quote;
  });
}

function quoteFacts(quote) {
  return [
    ['首期服务费', money(quote.bill?.amount)],
    ...(quote.securityBill ? [['入住押金', money(quote.depositAmount)]] : []),
    ['可抵扣预缴', money(quote.prepaidAmount)],
    ['本次应补', money(quote.dueAmount)],
  ];
}

function chargeRows(quote) {
  return [
    ...(quote.bill?.lineItems || []),
    ...(quote.securityBill?.lineItems || []),
  ].map((row) => [row.label, lineDescription(row)]);
}

export function admissionFinance(ctx, action, toPayload) {
  const finance = canAct(ctx, 'ops.pay');
  const extras = finance && ctx.state.chargeCatalog ? chargesEditor(ctx) : null;
  const methodHint = node('p', 'fx-muted');
  const securityTransfer = node('input');
  securityTransfer.type = 'checkbox';
  securityTransfer.name = 'allocateSecurityFromPrepaid';
  securityTransfer.value = 'yes';
  const securityChoice = node('label', 'admission-security-choice', [securityTransfer, '授权从已有预缴余额转存押金']);
  const notice = node('p', 'fx-muted', '核算后可查看房间床位费、护理费、其他约定费用和押金。');
  notice.setAttribute('aria-live', 'polite');
  const price = node('div', 'admission-price');
  const quoteBox = node('section', 'admission-quote', [
    node('h3', '', '首期费用明细'),
    node('div', 'admission-quote-content', [notice, price]),
  ]);
  const financeNames = ['depositMonths', 'reminderDays', 'securityMode', 'paymentMode'];
  const offlineNames = ['offlineAmount', 'offlineChannel'];
  let form;
  let currentQuote = null;
  let requestId = 0;
  let preview;

  const collection = finance && admissionCollection(ctx,
    () => payload(Object.fromEntries(new FormData(form))),
    () => getQuote(payload(Object.fromEntries(new FormData(form)))));
  function payload(values) {
    const { offlineAmount, offlineChannel, allocateSecurityFromPrepaid, ...terms } = values;
    const result = toPayload(terms);
    if (['qr','terminal'].includes(result.paymentMode)) result.paymentMode = 'standard';
    if (terms.paymentMode && finance) {
      result.depositMonths = Number(terms.depositMonths);
      result.reminderDays = Number(terms.reminderDays ?? 3);
      result.feeItems = extras?.read() || [];
    }
    if (terms.paymentMode === 'offline') {
      result.offlinePayment = { amount: offlineAmount, method: offlineMethods[offlineChannel], channel: offlineChannel };
    }
    if (allocateSecurityFromPrepaid === 'yes') result.allocateSecurityFromPrepaid = true;
    return result;
  }

  function setVisible(name, visible) {
    const control = form.elements[name];
    if (control) control.disabled = control.closest('label').hidden = !visible;
  }

  function invalidate() {
    requestId++;
    currentQuote = null;
    notice.textContent = '核算后可查看本次收费项目及金额。';
    notice.hidden = false;
    price.replaceChildren();
    preview.disabled = false;
  }

  function showQuote(quote, trial) {
    const bill = quote.bill;
    notice.hidden = true;
    price.replaceChildren(node('div', 'admission-price-breakdown', [
      facts(quoteFacts(quote)),
      bill?.startDate && bill?.endDate ? node('p', 'fx-muted', '首期计费 ' + bill.startDate + ' 至 ' + bill.endDate +
        (quote.nextBillingDate ? ' · 下次出账 ' + quote.nextBillingDate : '')) : null,
      bill ? section(trial ? '一次性试住费' : '服务费明细', feeLedger(bill)) : null,
      quote.securityBill ? section('押金明细', feeLedger(quote.securityBill)) : null
    ]));
  }

  async function getQuote(result) {
    const previewPayload = { ...result };
    delete previewPayload.offlinePayment;
    let revision = ctx.current().state.revision;
    let key = JSON.stringify([previewPayload, revision]);
    if (currentQuote?.key === key) return currentQuote.quote;
    const id = ++requestId;
    let quote;
    try {
      quote = await priceRequest(action, previewPayload, revision);
    } catch (error) {
      if (error.status !== 409 || id !== requestId || !await ctx.refreshWorkspace?.(form) || id !== requestId) throw error;
      revision = ctx.current().state.revision;
      key = JSON.stringify([previewPayload, revision]);
      quote = await priceRequest(action, previewPayload, revision);
    }
    if (id !== requestId) throw new Error('入住信息已更新，请重新核算。');
    currentQuote = { key, quote };
    collection?.quoted?.(quote.dueAmount);
    showQuote(quote, result.stayType === 'trial');
    return quote;
  }

  function showFormFields() {
    const { elements } = form;
    const formal = elements.stayType?.value !== 'trial';
    const waiveSecurity = elements.depositMonths?.value === '0';
    for (const name of financeNames) setVisible(name, formal && (name !== 'reminderDays' || waiveSecurity));
    for (const name of offlineNames) setVisible(name, formal && elements.paymentMode.value === 'offline');
    if (finance) {
      if (waiveSecurity) elements.securityMode.value = 'none';
      elements.securityMode.options[0].textContent = waiveSecurity ? '按约定提醒' : '押金单独保管';
      elements.securityMode.options[1].disabled = waiveSecurity;
    }
    if (collection) collection.display(formal ? elements.paymentMode.value : '');
    const transferEnabled = formal && !waiveSecurity && ['standard','qr','terminal'].includes(elements.paymentMode.value) && finance;
    securityChoice.hidden = securityTransfer.disabled = !transferEnabled;
    if (!transferEnabled) securityTransfer.checked = false;
    methodHint.hidden = !formal;
    methodHint.textContent = formal ? [!finance ? '默认押 1 个月。' : '',
      !waiveSecurity ? '合同到期或动用押金时提醒。' : '',
      paymentModes[elements.paymentMode.value][1]].filter(Boolean).join(' ') : '';
    if (extras) {
      if (formal) quoteBox.before(extras.element);
      else extras.element.remove();
    }
  }

  function mount(dialog) {
    form = dialog.querySelector('form');
    form.classList.add('admission-finance-form');
    const footer = form.querySelector('.dialog-actions');
    const quoteContent = node('div', 'admission-finance', quoteBox);
    form.elements.reminderDays?.closest('label').append(node('small', 'fx-muted', '填 0 时仅在账单日提醒。'));
    preview = btn(ctx, '核算首期费用', async () => {
      const amount = form.elements.offlineAmount;
      if (amount) amount.required = false;
      const valid = form.reportValidity();
      if (amount) amount.required = true;
      if (!valid) return;
      preview.disabled = true;
      notice.hidden = false;
      notice.textContent = '正在核算费用…';
      const id = requestId;
      try {
        const quote = await getQuote(payload(Object.fromEntries(new FormData(form))));
        if (amount && !amount.disabled && !amount.value && quote.dueAmount > 0) amount.value = quote.dueAmount;
        notice.hidden = true;
        price.scrollIntoView({ block: 'nearest' });
      } catch (error) {
        if (id + 1 >= requestId) notice.textContent = error.message;
      } finally {
        preview.disabled = false;
      }
    });
    quoteBox.insertBefore(preview, quoteBox.children[1]);
    footer.before(node('div', 'admission-payment-hint', [methodHint, securityChoice]), quoteContent);
    if (collection) footer.before(collection.panel);
    form.addEventListener('input', (event) => {
      if (['paymentMode', 'depositMonths'].includes(event.target.name)) showFormFields();
      if (!offlineNames.includes(event.target.name)) invalidate();
    });
    form.addEventListener('change', (event) => {
      if (['stayType', 'paymentMode', 'depositMonths'].includes(event.target.name)) showFormFields();
      if (!offlineNames.includes(event.target.name)) invalidate();
    });
    extras?.element.addEventListener('click', (event) => {
      if (event.target.closest('button')) invalidate();
    });
    showFormFields();
  }

  async function review(values) {
    const result = payload(values);
    if (['qr','terminal'].includes(values.paymentMode)) {
      result.paymentOrderId = await collection.verified();
      if (!await ctx.refreshWorkspace(form)) throw new Error('请重新打开入住档案');
    }
    const quote = await getQuote(result);
    const due = amountInCents(quote.dueAmount);
    if (result.paymentMode === 'standard' && due > 0) {
      throw new Error('本次还需实收 ' + money(quote.dueAmount) + '。已有实际到账时可选线下款已收；需要稍后收款时可选临时入住。');
    }
    if (result.paymentMode === 'offline') {
      if (!due) throw new Error('本次费用已能用预缴金结清，请选择正常入住。');
      if (amountInCents(result.offlinePayment.amount) < due) {
        throw new Error('实收金额须覆盖本次应补 ' + money(quote.dueAmount) + '。不足时请办理临时入住。');
      }
    }
    const tender = result.offlinePayment;
    const netFields = [];
    if (tender) {
      const gross = amountInCents(tender.amount);
      const rate = ctx.current().state.paymentFeeSettings?.[0]?.rates?.[tender.channel] || 0;
      const fee = Math.round(gross * rate / 10000);
      netFields.push(
        ['实收与渠道', money(tender.amount) + ' · ' + tender.method + '（' + tender.channel + '）'],
        ['机构承担手续费', money(fee / 100)],
        ['净入账', money((gross - fee) / 100)],
        ['超额转预缴', money(Math.max(0, gross - due) / 100)]
      );
    }
    return { payload: result, expectedRevision: quote.revision, fields: [
      ['生效日期', quote.admittedAt || result.admittedAt],
      ...(quote.bill?.startDate ? [['首期计费', quote.bill.startDate + ' 至 ' + quote.bill.endDate]] : []),
      ...(quote.nextBillingDate ? [['下次出账', quote.nextBillingDate]] : []),
      ...chargeRows(quote),
      ...quoteFacts(quote),
      ...(result.paymentMode ? [['收款确认', paymentModes[result.paymentMode][0]]] : []),
      ...(result.allocateSecurityFromPrepaid ? [['押金转存', '已授权从当前预缴余额转存']] : []),
      ...(result.paymentOrderId ? [['已核实渠道订单', result.paymentOrderId]] : []),
      ...netFields,
    ] };
  }

  return { mount, review };
}
