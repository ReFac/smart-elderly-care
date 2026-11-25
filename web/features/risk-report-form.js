import { btn, canAct, field, memo, node, options, residentField, residentName, section,
  select, staffField, today } from './shared.js';

const levels = ['低风险','中风险','高风险'];
const splitLines = text => text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
const number = value => value === '' ? null : Number(value);

// Repeated blocks mirror the recorded instrument. Blank reports carry no preset thresholds.
function rowEditor(ctx, title, addLabel, columns, limit) {
  const rows = node('div', 'risk-form-rows');
  const entries = new Map();
  const add = btn(ctx, addLabel, () => {
    const row = node('div', 'risk-form-row');
    const controls = columns.map(([key,label,type = 'text',max = 60,optional = false]) => {
      const input = node(type === 'level' ? 'select' : 'input', 'plan-input');
      if (type === 'level') {
        input.add(new Option('请选择', ''));
        for (const level of levels) input.add(new Option(level, level));
      } else if (type === 'number') {
        input.type = 'number'; input.min = '0'; input.max = '10000'; input.step = '1';
      } else input.maxLength = max;
      input.required = !optional;
      row.append(node('label','field',[node('span','', label), input]));
      return [key, input];
    });
    entries.set(row, controls);
    row.append(btn(ctx, '移除', () => {
      entries.delete(row);
      row.remove();
      add.disabled = false;
    }, 'ghost'));
    rows.append(row);
    add.disabled = entries.size >= limit;
    controls[0][1].focus();
  });
  return {
    element: section(title, node('div','',[rows,add])),
    read: () => [...entries.values()].map(controls => Object.fromEntries(controls.map(([key,input]) =>
      [key,input.type === 'number' ? number(input.value) : input.value.trim()]))),
  };
}

export function createRiskAssessment(ctx, rid = '') {
  if (!canAct(ctx,'care.screen')) return;
  const subject = residentField(ctx, {value: rid});
  if (rid) {
    subject.options = subject.options.filter(option => option.value === rid);
    if (!subject.options.length) return;
  }
  const factors = rowEditor(ctx,'风险触发因素','添加评估因素',[
    ['group','评估维度'],['finding','观察与依据','text',200],['points','原表分值','number',0,true]],30);
  const dimensions = rowEditor(ctx,'分项得分','添加分项',[
    ['group','评估维度'],['score','得分','number'],['maximum','满分','number']],30);
  const bands = rowEditor(ctx,'原量表风险区间','添加评分区间',[
    ['level','风险等级','level'],['min','起始分','number'],['max','截至分（无上限可留空）','number',0,true]],3);
  const steps = rowEditor(ctx,'重点防护预案','添加预案步骤',[
    ['title','步骤名称'],['detail','具体措施','text',400]],3);
  const content = node('div','risk-form-sections',[factors.element,dimensions.element,bands.element,steps.element]);
  const score = (key,label) => field(key,label,{type:'number',required:false,min:0,max:10000,step:1});
  const lines = (key,label,limit) => memo(key,label,false,{maxLength:limit,placeholder:'每行一项'});
  const dialog = ctx.dialog({
    title:'登记专项风险评估', description:'按本次评估的原始量表和专业人员意见登记。',
    fields:[subject, select('topic','评估专项', options(['跌倒/坠床','压疮','噎食/误吸','走失','其他'])),
      field('instrument','量表名称、版本或评估依据'),
      select('level','经专业人员核定的等级',[{value:'',label:'请选择'},...options([...levels,'待专业复核'])]),
      score('score','原量表总分'),score('maximum','原量表满分'),memo('finding','评估结论',true),
      lines('tags','评估关注标签',500),lines('recommended','床旁推荐措施',2000),lines('cautions','床旁应避免的情况',2000),
      lines('immediate','立即执行',800),lines('follow','近期跟进',800),lines('routine','日常维护',800),
      field('nextReview','下次专项评估日期',{type:'date',min:today(ctx),required:false}),
      staffField(ctx,'reviewer','负责复评人员',{required:false}),memo('reviewNote','复评跟进备注',false,{maxLength:800})],
    content,submitLabel:'确认登记',onSubmit:values=>{
      const {residentId,finding,tags,recommended,cautions,...report} = values;
      const target = rid || residentId;
      return ctx.command('care.screen', {residentId:target,subject:report.topic,finding,riskReport:{
        ...report,score:number(report.score),maximum:number(report.maximum),factors:factors.read(),dimensions:dimensions.read(),
        bands:bands.read(),tags:splitLines(tags),bedside:{recommended:splitLines(recommended),avoid:splitLines(cautions)},
        avoid:'',preventionSteps:steps.read(),
      }},{title:'登记专项风险报告',target:residentName(ctx,target),fields:[['专项',report.topic],['人工核定等级',report.level]]});
    },
  });
  if (dialog) dialog.querySelector('[name=finding]').closest('label').after(content.closest('.form-content'));
}
