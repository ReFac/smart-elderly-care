import { canAct, choose, field, link, memo, money, named, node, residentName, runForm, select, table, today } from './shared.js';

export async function requestRefund(ctx, receipt) {
  const refunds = (ctx.state.refunds || []).filter(r => r.receiptId === receipt.id && r.status !== '已取消');
  const remaining = receipt.gross - refunds.reduce((sum,r) => sum + Math.round(r.amount*100),0);
  if (remaining <= 0) return ctx.toast('此收款凭证已无可退金额');
  const modes = [{value:'manual', label:'按已核实的实际退款凭证对账'}];
  const signed = ctx.state.channelReceipts?.some(r => r.id===receipt.id && r.verification==='渠道签名通知');
  if (signed && receipt.merchantOrder && receipt.transactionId && ['微信支付','支付宝'].includes(receipt.channel)) {
    const result = await ctx.get('/api/payments/checkout/channels').catch(() => ({channels:[]}));
    if (result.channels.includes(receipt.channel)) modes.push({value:'channel',label:receipt.channel+'原路退款'});
  }
  const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)), b=>b.toString(16).padStart(2,'0')).join('');
  runForm(ctx, {
    title:'申请退款', action:'ops.requestRefund', submitLabel:'核对退款申请',
    description:residentName(ctx,receipt.residentId) + ' · 原收款凭证 ' + receipt.id +
      ' · 交易剩余 ' + money(remaining/100) + '。已消费的预缴余额需先核对，退款申请会占用本次可退金额。',
    fields:[field('amount','退款金额（元）',{type:'number',min:0.01,max:remaining/100,step:0.01,value:(remaining/100).toFixed(2)}),
      select('mode','核实方式',modes), memo('reason','退款原因',true)],
    map:values=>({...values,receiptId:receipt.id,residentId:receipt.residentId,requestId}),
  });
}

function verify(ctx, row) {
  return runForm(ctx, {
    title:'核实退款凭证', action:'ops.confirmRefund', submitLabel:'确认实际退款',
    description:'请核对 '+ row.channel + ' 实际退回 ' + money(row.amount) + ' 的流水或签收记录。确认后将冲正入账。',
    fields:[field('refundDate','实际退款日期',{type:'date',value:today(ctx),min:row.receiptDate,max:today(ctx)}),
      field('reference','实际退款流水或签收凭证号')],
    map:values=>({...values,residentId:row.residentId,refundId:row.id,verified:true}),
  });
}

export function refundLedger(ctx) {
  const rows=[...(ctx.state.refunds || [])].reverse();
  return table(ctx, {
    title:'退款对账',rows,empty:'暂无退款申请。',
    search:{placeholder:'搜索长辈、凭证或退款流水',value:r=>[residentName(ctx,r.residentId),r.id,r.receiptId,r.reference].join(' ')},
    cols:[
      {label:'申请日期',view:r=>r.date}, {label:'长辈',view:r=>residentName(ctx,r.residentId)},
      {label:'退款金额',view:r=>named(money(r.amount),r.channel)}, {label:'原收款凭证',view:r=>r.receiptId},
      {label:'退款原因',view:r=>r.reason}, {label:'状态',view:r=>named(r.status,r.reference||'')},
      {label:'经办人',view:r=>named(r.operator,r.reviewer ? '核实人 '+r.reviewer : '')},
      {label:'操作',view:r=>{
        if (!['待核实','渠道处理中'].includes(r.status)) return node('span','','—');
        if (r.mode==='channel') return canAct(ctx,'ops.confirmRefund')
          ? link(ctx,'提交或查询原路退款',async()=> (await import('./merchant-refund.js')).sendMerchantRefund(ctx,r)) : node('span','','等待渠道核实');
        return choose(canAct(ctx,'ops.confirmRefund') && link(ctx,'核实凭证',()=>verify(ctx,r)),
          canAct(ctx,'ops.cancelRefund') && link(ctx,'撤销申请',()=>ctx.command('ops.cancelRefund',{
            residentId:r.residentId, refundId:r.id,
          },{title:'撤销未付款的退款申请',target:r.id,fields:[['金额',money(r.amount)]]})));
      }},
    ],
  });
}
