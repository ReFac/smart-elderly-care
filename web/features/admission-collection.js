import { money, node, btn, residentName } from './shared.js';
import { showCheckout } from './payment-qr.js';

const cents = n => Math.round(Number(n) * 100);

export function admissionCollection(ctx, getPayload, refreshQuote) {
  const name = node('select');
  name.setAttribute('aria-label','实际收款渠道');
  const amount = node('input');
  amount.type = 'number'; amount.min = '0.01'; amount.max = '99999999'; amount.step = '.01';
  const note = node('p','fx-muted');
  note.setAttribute('role','status');
  const issue = btn(ctx,'发起定额收款',collect,'primary');
  const check = btn(ctx,'核对到账状态',status);
  const panel = node('section','admission-collection',[
    node('label','field',[node('span','','收款渠道'),name]),
    node('label','field',[node('span','','商户指定金额（元）'),amount]),issue,check,note]);
  let mode, channels, selected, reference, loading = false;
  const orders = () => ctx.current().state.paymentOrders || [];
  function findOrder() {
    const resident = getPayload().residentId;
    return orders().find(r => r.residentId === resident && r.purpose === 'admission' && r.channel === name.value &&
      r.collection === mode && cents(r.amount) === cents(amount.value) &&
      (r.id === selected || r.status === '待支付'));
  }
  async function status() {
    const order = findOrder();
    if (!order) { note.textContent = '请先发起收款。'; return; }
    try {
      const receipt = await ctx.get('/api/payments/checkout/orders/' + encodeURIComponent(order.id));
      if (!panel.isConnected) return;
      selected = order.id;
      note.textContent = order.id + ' · ' + receipt.status;
      if (receipt.status === '已到账') {
        await ctx.refreshWorkspace(panel);
        await refreshQuote();
      }
    } catch (error) { note.textContent = error.message; }
  }
  async function collect() {
    if (loading || !name.value) return;
    if (!amount.value || !amount.checkValidity()) {
      note.textContent='请输入大于零且精确到分的收款金额。'; amount.focus();return;
    }
    loading = true;
    issue.disabled = true;
    try {
      let order = findOrder();
      if (!order) {
        reference ||= crypto.randomUUID().replaceAll('-','');
        const args = {residentId:getPayload().residentId,channel:name.value,amount:amount.value,collection:mode,requestId:reference};
        const ok = await ctx.command('ops.admissionOrder',args,{
          title:'确认向长辈收取入住款',target:residentName(ctx,args.residentId),
          fields:[['收款方式',(mode === 'qr' ? '扫码 · ' : '商户终端 · ') + name.value],['商户指定金额',money(amount.value)]],
          preserveForm:panel.closest('dialog'),quiet:true});
        if (!ok || !panel.isConnected) return;
        order = orders().find(r => r.requestId === reference);
      }
      if (!order) throw new Error('请重新核对收款订单');
      selected = order.id;
      if (order.status === '已到账') return await status();
      note.textContent = mode === 'qr' ? '收款单 ' + order.id + ' · 等待扫码到账'
        : '请在收银终端调取订单 ' + order.id + '。终端将读取指定金额，支付成功后自动回传。';
      if (mode === 'qr') await showCheckout(ctx.current(),order,true);
    } catch (error) { note.textContent = error.message; }
    finally { loading = false; issue.disabled = !name.value; }
  }
  function changed() { reference = null; selected = null; note.textContent=''; }
  name.onchange = changed; amount.oninput = changed;
  async function display(next) {
    panel.hidden = !['qr','terminal'].includes(next);
    amount.disabled = name.disabled = panel.hidden;
    if (panel.hidden || mode === next && name.length) return;
    mode = next; changed(); name.replaceChildren(); issue.disabled = true;
    note.textContent = '正在读取机构收款渠道…';
    try {
      channels ||= await ctx.get('/api/payments/checkout/channels');
      if (mode !== next) return;
      const options = (mode === 'qr' ? channels.channels : channels.terminalChannels) || [];
      name.replaceChildren(...options.map(channel => new Option(channel,channel)));
      issue.disabled = !options.length;
      note.textContent = options.length ? '核算费用后可修改本次收款金额。' : mode === 'qr' ? '本机构尚未开通商户收款码。' : '本机构尚未接入收银终端。';
    } catch (error) { note.textContent = error.message; }
  }
  return {panel, display, quoted(value) { if (!amount.value && value > 0) amount.value = value; },
    async verified() {
      const order = findOrder();
      if (!order || (await ctx.get('/api/payments/checkout/orders/' + order.id)).status !== '已到账')
        throw new Error('请先完成收款，收到渠道到账回执后才能确认入住。');
      return order.id;
    }};
}
