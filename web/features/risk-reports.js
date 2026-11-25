import { badge, btn, byRecent, canAct, facts, link, named, node, residentName, section, table } from './shared.js';
import { evaluationBars, evaluationHeader, evaluationResult } from './evaluation-report.js';
import { evaluationDetails } from './assessment-scale.js';
import { residentAnchor, staffLabel } from './people-labels.js';

import { createRiskAssessment } from './risk-report-form.js';
export { createRiskAssessment };

function history(ctx, rid) {
  return byRecent(ctx.state.followups || []).filter(r=>r.residentId===rid);
}

function renderReport(ctx,r) {
  const data=r.riskReport;
  const root=node('div','risk-report');
  const previous = history(ctx,r.residentId).filter(p=>p.riskReport?.topic===data?.topic);
  const index=previous.findIndex(p=>p.id===r.id);
  const last=index<0?null:previous[index+1]?.riskReport;
  const level = data?.level || r.priority || '待专业复核';
  root.append(evaluationResult({
    title: level, topic: data?.topic || r.subject, finding: r.finding,
    score: data?.score, maximum: data?.maximum,
    lastScore: last?.instrument === data?.instrument && last?.maximum === data?.maximum ? last?.score : null,
    bands: data?.bands || [],
    tone: ({'高风险':'high','中风险':'medium','低风险':'low'})[level] || 'neutral',
  }));
  const factors=data?.factors||[];
  const grouped=new Map();
  for(const f of factors) if(f.points!=null) grouped.set(f.group,(grouped.get(f.group)||0)+f.points);
  const factorsCard=section('风险触发因素',factors.length ? node('dl','risk-factor-list',factors.map(f=>node('div','',[
    node('dt','',f.group),node('dd','',f.finding),node('strong','',f.points==null?'未评分':f.points+' 分')]))) :
    node('p','fx-muted',r.basis||'本次记录未登记分项因素'));
  const dimensions = data?.dimensions || [];
  const scores = dimensions.length ? dimensions.map(d => [d.group, d.score]) : [...grouped];
  const maxima = Object.fromEntries(dimensions.map(d => [d.group,d.maximum]));
  const totals = section('分项得分分布', scores.length ? evaluationBars(scores, maxima) :
    node('p','fx-muted','本次记录没有可汇总的分项得分'));
  root.append(node('div','risk-columns',[factorsCard,totals]));

  const lines = text => (text || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const recommendations = [...new Set([...(data?.bedside?.recommended || []), ...lines(r.intervention)])];
  const cautions = [...new Set([...(data?.bedside?.avoid || []), ...lines(data?.avoid)])];
  if (recommendations.length || cautions.length) {
    const groups = [['推荐措施',recommendations,'clinical-guidance'],['避免事项',cautions,'clinical-caution']];
    root.append(section('床旁防护重点', node('div','risk-precautions',groups.filter(([,items]) => items.length)
      .map(([title,items,tone]) => node('article',tone,[node('h4','',title),
        node('ul','',items.map(text=>node('li','',text)))])))));
  }
  const measures = [['立即执行', data?.immediate], ['近期跟进', data?.follow], ['日常维护', data?.routine]];
  if (measures.some(([,value]) => value)) root.append(section('护理干预建议', node('div','risk-measures',
    measures.map(([title,value]) => node('article','',[node('h4','',title), value
      ? node('ul','',lines(value).map(text=>node('li','',text))) : node('p','fx-muted','未登记')])))));
  if (data?.preventionSteps?.length) {
    const plan = section((data.topic || '') + '重点防护预案', node('ol','risk-steps',
      data.preventionSteps.map(step=>node('li','',[node('h4','',step.title),node('p','',step.detail)]))));
    plan.classList.add('clinical-plan');
    root.append(plan);
  }
  const reviewer = data?.reviewer || r.assignee;
  const next = section('下次评估计划', facts([
    ['建议评估日期',data?.nextReview || r.dueDate || '待安排'],
    ['负责评估人',reviewer ? staffLabel(ctx,reviewer,r.assignee === reviewer ? r.assigneeId : undefined) : '待安排'],
    ['跟进备注',data?.reviewNote || '未登记']]));
  next.classList.add('review-plan');
  root.append(next);
  return root;
}

function profileRisk(person){
  return {residentId:person.id,id:'profile-'+person.id,subject:'档案风险提示',finding:person.risk,date:'',profile:true};
}

export function riskDrawer(ctx,row,{example = false} = {}) {
  const person=ctx.state.residents.find(p=>p.id===row.residentId);
  if(!person)return;
  const body=node('div','risk-panel'); let dialog;
  function show(r,tab='报告'){
    const chooseTab=n=>{const b=btn(ctx,'评估'+n,()=>show(r,n),'ghost');b.setAttribute('aria-pressed',String(n===tab));return b;};
    const other=btn(ctx,'其他评估',()=>show(r,'其他'),'ghost');other.setAttribute('aria-pressed',String(tab==='其他'));
    const header=evaluationHeader(ctx, r.residentId,
      [r.date && '评估日期 ' + r.date, r.openedBy && '评估人 ' + staffLabel(ctx,r.openedBy),
       r.subject && '专项 ' + r.subject, !r.profile && '编号 ' + r.id],
      [person.level && '照护等级 ' + person.level, r.riskReport?.instrument], r.riskReport?.tags || []);
    const tabs=node('nav','risk-tabs',[chooseTab('报告'),chooseTab('详情'),other]);
    tabs.setAttribute('aria-label','专项评估视图');
    let content;
    if(tab==='报告') content=renderReport(ctx,r);
    else if(tab==='详情') content=facts([['评估编号',r.profile?'档案风险提示':r.id],['评估专项',r.subject],
      ['记录时间',r.date||'见档案历史'],['评估依据',r.riskReport?.instrument],['观察记录',r.finding],['分级依据',r.basis],
      ['干预安排',r.intervention],['随访记录',r.actual],['效果评价',r.outcome],['状态',r.status||'已登记']].filter(([,v])=>v));
    else {
      const otherRows=history(ctx,person.id).filter(p=>p.id!==r.id);
      if(person.risk&&!r.profile)otherRows.push(profileRisk(person));
      content=section('该长辈的其他专项记录',otherRows.length?node('div','fx-profile',otherRows.map(a=>
        link(ctx,[a.date,a.subject,a.riskReport?.level||a.priority].filter(Boolean).join(' · '),()=>show(a)))):
        node('p','fx-muted','没有其他已登记的专项记录'));
      const assessments=byRecent(ctx.state.assessments||[]).filter(a=>a.residentId===person.id);
      if(assessments.length) content.append(section('能力与照护评估',node('div','fx-profile',assessments.map(a=>
        link(ctx,[a.scale?.assessedOn||a.date,a.scale?.gradeName||a.level].filter(Boolean).join(' · '),()=>evaluationDetails(ctx,a))))));
    }
    const print=btn(ctx,'打印报告',()=>{
      show(r,'报告');
      window.print();
    },'primary');
    const switching = body.contains(document.activeElement);
    body.replaceChildren(header,tabs,content,node('footer','plan-footer',[btn(ctx,'关闭',()=>dialog.close()),print]));
    if (switching) tabs.querySelector('[aria-pressed=true]')?.focus({preventScroll:true});
  }
  show(row);
  dialog=ctx.detail(example ? '专项评估结果 · 虚构示例' : '专项评估结果',body);
  dialog.classList.add('risk-drawer');
  if (!example) dialog.dataset.roundsResidentId = row.residentId;
}

export function riskDesk(ctx) {
  const data=byRecent(ctx.state.followups||[]);
  const rows=[...data,...ctx.state.residents.filter(p=>p.risk).map(profileRisk)];
  return table(ctx,{title:'专项风险档案',rows,
    search:{placeholder:'搜索长辈、专项或结论',value:r=>residentName(ctx,r.residentId)+' '+r.subject+' '+r.finding},
    action:canAct(ctx,'care.screen')?btn(ctx,'登记专项评估',()=>createRiskAssessment(ctx),'primary'):null,
    cols:[{label:'长辈',view:r=>residentAnchor(ctx,r.residentId)},{label:'本次评估',view:r=>named(r.subject,r.date||'长辈档案')},
      {label:'风险等级',view:r=>r.riskReport?badge(ctx,r.riskReport.level):r.priority||'未核定'},
      {label:'原始总分',view:r=>r.riskReport?.score??'—'},{label:'评估人',view:r=>r.openedBy?staffLabel(ctx,r.openedBy):'—'},
      {label:'报告',view:r=>link(ctx,'查看报告',()=>riskDrawer(ctx,r))}]});
}
