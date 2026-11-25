import { el, icon, button } from '../lib/ui.js';
import { table, named, badge, money, facts } from './shared.js';
import { residentAnchor, staffLabel } from './people-labels.js';

function jump(ctx, label, glyph, destination, tab) {
  const link = el('a','desk-shortcut');
  link.href = '#' + destination + (tab ? '?' + new URLSearchParams({tab}) : '');
  link.append(icon(glyph,20), el('span','',label),icon('chevron',13));
  return link;
}

export function officeHome(ctx) {
  const s = ctx.state;
  const home = el('section','desk-home');
  const heading = el('header','desk-home-head');
  const identity = el('div');
  identity.append(el('h1','','机构运营总览'),el('p','',s.uiSettings.institutionName + '　' + s.today));
  heading.append(identity);
  const launch = el('a','btn btn-primary');
  launch.href = '#overview?view=cockpit'; launch.append(icon('chart',16),'打开经营大屏');
  heading.append(launch); home.append(heading);
  const metrics = el('div','desk-home-metrics');
  function metric(label,value,unit,detail,route,tab) {
    const a = el('a','desk-metric');
    a.href = '#' + route + (tab ? '?' + new URLSearchParams({tab}) : '');
    const number = el('strong','',value); number.append(el('small','',unit));
    a.append(el('span','',label),number,el('small','',detail)); metrics.append(a);
  }
  if (ctx.available('residents')) {
    const inHouse = s.residents.filter(r => r.status === '在住');
    metric('在院人数',inHouse.length,'人','本月新入住 ' + inHouse.filter(r=>r.admittedAt?.startsWith(s.today.slice(0,7))).length + ' 人','residents');
  }
  if (ctx.available('beds')) metric('空置床位',s.beds.filter(b=>b.status === '空闲').length,'床','登记床位共 ' + s.beds.length + ' 床','beds');
  if (ctx.available('care') && ctx.state.allowedActions.includes('care.completeTask')) {
    const tasks = s.tasks.filter(t=>t.date === s.today);
    metric('今日照护工单',tasks.length,'单','已完成 ' + tasks.filter(t=>t.status === '已完成').length + ' 单','care','tasks');
  }
  if (ctx.available('billing') && ctx.permitted('finance') && s.cashOverview) {
    metric('今日新增实收',money(s.cashOverview.todayGross),'','本月流水 ' + money(s.cashOverview.monthGross),'billing','receipts');
    metric('待收款',money(s.cashOverview.outstanding),'','按当前未结清账单汇总','billing','unpaid');
  }
  if (metrics.childElementCount) home.append(metrics);
  const grid = el('div','desk-home-grid');
  const queue = [];
  function pending(route,tab,label,items,status) {
    if (ctx.available(route)) queue.push({route,tab,label,count:items.length,status});
  }
  if (ctx.permitted('alerts')) pending('inbox','alerts','设备预警',s.gatewayAlerts.filter(x=>x.status === '待复核'),'待现场核实');
  if (ctx.permitted('clinical')) pending('medications','orders','用药计划',s.medications.filter(x=>x.status === '待复核'),'待医护复核');
  if (ctx.permitted('care')) pending('assessments','plans','照护计划',s.plans.filter(x=>x.status === '待复核'),'待审核');
  if (ctx.permitted('finance')) pending('billing','unpaid','收费账单',s.bills.filter(x=>x.balance>0),'待缴费');
  if (ctx.permitted('inventory')) pending('inventory','stock','库存补充',s.inventory.filter(x=>x.quantity<x.minimum),'低于库存下限');
  if (queue.length) grid.append(table(ctx,{title:'待办事项',rows:queue,cols:[
    {label:'业务',view:r=>r.label},{label:'数量',view:r=>r.count},{label:'办理状态',view:r=>r.count ? badge(ctx,r.status,'amber') : '已清'},
    {label:'操作',align:'end',view:r=>button('查看',()=>ctx.go(r.route,r.tab),'ghost')},
  ]}));
  const quick = el('section','desk-shortcuts fx-panel');
  quick.append(el('h2','','业务入口'));
  const links = el('div');
  for (const [route,label,glyph,tab] of [
    ['leads','接待登记','intake'],['residents','入住管理','people'],['dossier','长辈档案','folder'],
    ['beds','床位全景','bed'],['care','照护服务','care'],['inventory','库存台账','box'],
    ['billing','费用管理','wallet'],['reports','统计报送','reports'],['family','家属服务','people'],
  ]) if (ctx.available(route)) links.append(jump(ctx,label,glyph,route,tab));
  if (links.childElementCount) { quick.append(links); grid.append(quick); }
  if (grid.childElementCount) home.append(grid);
  if (ctx.available('care') && ctx.state.allowedActions.includes('care.completeTask'))
    home.append(table(ctx,{title:'今日照护安排',rows:s.tasks.filter(t=>t.date===s.today)
      .sort((a,b)=>String(a.time).localeCompare(String(b.time))),empty:'今天还没有照护工单',
      search:{placeholder:'搜索项目或执行人',value:r=>[r.title,r.assignee].join(' ')},cols:[
        {label:'计划时间',view:r=>r.time},{label:'照护项目',view:r=>named(r.title,r.category)},
        {label:'服务长辈',view:r=>residentAnchor(ctx,r.residentId)},{label:'执行人员',view:r=>staffLabel(ctx,r.assignee,r.assigneeId)},
        {label:'状态',view:r=>badge(ctx,r.status)},{label:'操作',align:'end',view:r=>button('查看工单',()=>ctx.detail(r.title,facts([
          ['工单编号',r.id],['计划时间',r.date + ' ' + r.time],['长辈',residentAnchor(ctx,r.residentId)],
          ['执行人',staffLabel(ctx,r.assignee,r.assigneeId)],['状态',r.status],['执行记录',r.note]
        ])),'ghost')},
      ]}));
  return home;
}
