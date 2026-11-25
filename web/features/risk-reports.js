import { badge, btn, byRecent, canAct, facts, field, link, memo, named, node, options, residentField,
  residentName, section, select, table, today } from './shared.js';
import { evaluationDetails } from './assessment-scale.js';
import { residentAnchor, staffLabel } from './people-labels.js';

const topics=['跌倒/坠床','压疮','噎食/误吸','走失','其他'];
const levels=['低风险','中风险','高风险','待专业复核'];

function create(ctx, rid='') {
  const factors=node('div','risk-factors-form');
  function add() {
    const controls=['评估维度','观察与依据','原表分值'].map((label,i)=>{
      const c=node('input','plan-input'); c.type=i===2?'number':'text'; c.placeholder=label;
      c.setAttribute('aria-label',label); c.required=i!==2; c.maxLength=i===0?60:200;
      if(i===2){c.min=0;c.max=10000;c.step=1;} return c;
    });
    const row=node('div','risk-factor-input',[...controls,btn(ctx,'移除',()=>row.remove(),'ghost')]);
    factors.append(row);
  }
  const content = section('风险触发因素',node('div','',[factors,btn(ctx,'添加评估因素',add)]));
  const score = name => field(name,name==='score'?'原量表总分':'原量表满分',{type:'number',required:false,min:0,max:10000,step:1});
  ctx.dialog({title:'登记专项风险评估',description:'按专业人员完成的原始评估登记。无评分的评估可留空分值。',content,
    fields:[residentField(ctx,{value:rid}),select('topic','评估专项',options(topics)),
      field('instrument','量表名称、版本或评估依据'),select('level','经专业人员核定的等级',[{value:'',label:'请选择'},...options(levels)]),
      score('score'),score('maximum'),memo('finding','评估结论',true),memo('immediate','立即执行'),
      memo('follow','近期跟进'),memo('routine','日常维护'),memo('avoid','应避免的情况'),
      field('nextReview','下次专项评估日期',{type:'date',min:today(ctx),required:false})],
    submitLabel:'确认登记',onSubmit:v=>{
      const num=x=>x===''?null:Number(x);
      const entries=[...factors.children].map(r=>{const [group,finding,points]=r.querySelectorAll('input');
        return {group:group.value,finding:finding.value,points:num(points.value)};});
      const {residentId,finding,...report}=v;
      return ctx.command('care.screen',{residentId,subject:report.topic,finding,riskReport:{
        ...report,score:num(report.score),maximum:num(report.maximum),factors:entries}},
        {title:'登记专项风险报告',target:residentName(ctx,residentId),fields:[['专项',report.topic],['人工核定等级',report.level]]});
    }});
}

function history(ctx, rid) {
  return byRecent(ctx.state.followups || []).filter(r=>r.residentId===rid);
}

function renderReport(ctx,r) {
  const data=r.riskReport;
  const root=node('div','risk-report');
  const previous = history(ctx,r.residentId).filter(p=>p.riskReport?.topic===data?.topic);
  const index=previous.findIndex(p=>p.id===r.id);
  const last=index<0?null:previous[index+1]?.riskReport;
  const score = data?.score;
  root.append(node('div','risk-result',[node('div','',[node('h2','',data?.level||r.priority||'待专业复核'),
    node('p','',r.finding)]),node('div','risk-score',[node('strong','',score==null?'—':score),
    node('small','',score==null?'未提供量表分值':'总得分'+(data.maximum==null?'':' / '+data.maximum)),
    last?.score!=null?node('small','','上次 '+last.score+' 分'):null])]));
  const factors=data?.factors||[];
  const grouped=new Map();
  for(const f of factors) if(f.points!=null) grouped.set(f.group,(grouped.get(f.group)||0)+f.points);
  const factorsCard=section('风险触发因素',factors.length ? node('dl','risk-factor-list',factors.map(f=>node('div','',[
    node('dt','',f.group),node('dd','',f.finding),node('strong','',f.points==null?'未评分':f.points+' 分')]))) :
    node('p','fx-muted',r.basis||'本次记录未登记分项因素'));
  const totals=section('分项得分分布',grouped.size?node('div','risk-bars',[...grouped].map(([label,value])=>{
    const meter=node('meter','');meter.max=Math.max(...grouped.values(),1);meter.value=value;meter.setAttribute('aria-label',label+' '+value+'分');
    return node('label','',[node('span','',label),meter,node('strong','',value+' 分')]);})):node('p','fx-muted','本次记录没有可汇总的分项得分'));
  root.append(node('div','risk-columns',[factorsCard,totals]));
  const measures=[['立即执行',data?.immediate],['近期跟进',data?.follow||r.intervention],['日常维护',data?.routine]];
  root.append(section('护理干预建议',node('div','risk-measures',measures.map(([t,v])=>
    node('article','',[node('h4','',t),node('p','',v||'未登记')])))));
  if(data?.avoid) root.append(section('防护注意事项',node('p','',data.avoid)));
  root.append(facts([['下次评估',data?.nextReview||r.dueDate||'待安排'],['随访责任人',r.assignee?staffLabel(ctx,r.assignee,r.assigneeId):'待安排'],
    ['原始依据',data?.instrument||'档案记录'],['登记人',r.openedBy?staffLabel(ctx,r.openedBy):'见长辈档案']]));
  return root;
}

function profileRisk(person){
  return {residentId:person.id,id:'profile-'+person.id,subject:'档案风险提示',finding:person.risk,date:'',profile:true};
}

export function riskDrawer(ctx,row) {
  const person=ctx.state.residents.find(p=>p.id===row.residentId);
  if(!person)return;
  const body=node('div','risk-panel'); let dialog;
  function show(r,tab='报告'){
    const chooseTab=n=>{const b=btn(ctx,'评估'+n,()=>show(r,n),'ghost');b.setAttribute('aria-pressed',String(n===tab));return b;};
    const other=btn(ctx,'其他评估',()=>show(r,'其他'),'ghost');other.setAttribute('aria-pressed',String(tab==='其他'));
    const header=node('header','plan-person',[node('span','plan-avatar',person.name.slice(0,1)),
      named(residentName(ctx,r.residentId),[person.level,r.subject,r.date,r.openedBy?staffLabel(ctx,r.openedBy):''].filter(Boolean).join(' · ')),
      badge(ctx,r.riskReport?.level||'查阅记录')]);
    const tabs=node('nav','risk-tabs',[chooseTab('报告'),chooseTab('详情'),other]);
    let content;
    const report=renderReport(ctx,r);
    if(tab==='报告') content=report;
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
    body.replaceChildren(header,tabs,content,node('footer','plan-footer',[btn(ctx,'关闭',()=>dialog.close()),print]));
  }
  show(row);
  dialog=ctx.detail('专项评估结果',body);
  dialog.classList.add('risk-drawer');
  dialog.dataset.roundsResidentId = row.residentId;
}

export function riskDesk(ctx) {
  const data=byRecent(ctx.state.followups||[]);
  const rows=[...data,...ctx.state.residents.filter(p=>p.risk).map(profileRisk)];
  return table(ctx,{title:'专项风险档案',rows,
    search:{placeholder:'搜索长辈、专项或结论',value:r=>residentName(ctx,r.residentId)+' '+r.subject+' '+r.finding},
    action:canAct(ctx,'care.screen')?btn(ctx,'登记专项评估',()=>create(ctx),'primary'):null,
    cols:[{label:'长辈',view:r=>residentAnchor(ctx,r.residentId)},{label:'本次评估',view:r=>named(r.subject,r.date||'长辈档案')},
      {label:'风险等级',view:r=>r.riskReport?badge(ctx,r.riskReport.level):r.priority||'未核定'},
      {label:'原始总分',view:r=>r.riskReport?.score??'—'},{label:'评估人',view:r=>r.openedBy?staffLabel(ctx,r.openedBy):'—'},
      {label:'报告',view:r=>link(ctx,'查看报告',()=>riskDrawer(ctx,r))}]});
}
