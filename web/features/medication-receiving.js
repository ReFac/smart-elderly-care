import { residentAnchor, residentLabel, staffLabel } from './people-labels.js';
import { bedName, btn, canAct, facts, field, hasGrant, link, memo, named, node, options, residentField, runForm, select, table } from './shared.js';

const sources = ['家属交付', '长辈自带', '医疗机构', '药房配送', '其他'];
const units = ['盒', '瓶', '支', '板', '片', '袋', '贴', '粒', '毫升', '克', '套'];

export function medicationReceivingLink(ctx, person) {
  if (!ctx.available?.('medications') || !hasGrant(ctx, 'clinical') || !person) return null;
  const a = node('a', 'btn btn-ghost', '药品接收登记');
  a.href = '#medications?' + new URLSearchParams({tab:'receiving', person:person.id});
  return a;
}

function receive(ctx, person) {
  const key = crypto.randomUUID();
  runForm(ctx, {
    title:'登记接收药品', action:'care.receiveMedication', submitLabel:'核对交接',
    description: (person ? residentLabel(ctx,person) + ' · ' : '') + '按实际交付包装登记。给药另按医嘱核对。',
    fields:[
      ...(person ? [] : [residentField(ctx)]),
      field('name','包装药品全名',{maxLength:120}), field('specification','剂型及规格',{maxLength:120}),
      field('quantity','接收数量',{type:'number',min:.001,max:1000000,step:.001}),
      select('unit','数量单位',options(units)), select('source','交付来源',options(sources)),
      field('sender','交付人',{maxLength:80}), field('lot','生产批号',{required:false,maxLength:80}),
      field('expiry','包装标示有效期',{type:'date',required:false}), memo('note','交接备注',false,{maxLength:500}),
    ],
    map:v=>({...v,residentId:person?.id || v.residentId,requestId:key}),
  });
}

export function receivingDesk(ctx) {
  if (!hasGrant(ctx,'clinical')) return ctx.ui.empty('当前岗位没有药品接收台账的查看权限。');
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const id = params.get('person');
  const people = new Map(ctx.state.residents.map(person=>[person.id,person]));
  const person = people.get(id);
  if (id && !person) return ctx.ui.empty('该长辈不在当前账号的可见档案中。');
  const rows = (ctx.state.medicationReceipts || []).filter(r=>people.has(r.residentId) && (!id || r.residentId===id)).reverse();
  const open = r=>ctx.detail('药品交接凭证',facts([
    ['登记编号',r.id], ['长辈',residentAnchor(ctx,r.residentId)],['交接时床位',bedName(ctx,r.bedId)],
    ['药品全名',r.name], ['剂型及规格',r.specification], ['实收数量',r.quantity + r.unit],
    ['生产批号',r.lot], ['有效期',r.expiry], ['交付来源',r.source], ['交付人',r.sender],
    ['接收人',staffLabel(ctx,r.operator,r.operatorId)], ['交接时间',r.receivedAt.replace('T',' ')], ['备注',r.note],
  ]));
  return table(ctx, {title:person ? residentLabel(ctx,person) + ' · 药品接收台账' : '药品接收台账',
    rows, empty:'尚无药品交接记录。',
    action:canAct(ctx,'care.receiveMedication') && (!person || person.status==='在住' && person.bedId)
      ? btn(ctx,'登记接收药品',()=>receive(ctx,person),'primary') : null,
    search:{placeholder:'搜索长辈、药品、生产批号或交付人',value:r=>[residentLabel(ctx,r.residentId),r.name,r.lot,r.sender].join(' ')},
    filter:{label:'交付来源',options:sources,value:r=>r.source},
    cols:[{label:'长辈',view:r=>residentAnchor(ctx,r.residentId)},
      {label:'药品 / 规格',view:r=>named(r.name,r.specification)}, {label:'实收数量',view:r=>r.quantity+' '+r.unit},
      {label:'批号 / 有效期',view:r=>named(r.lot || '批号未登记',r.expiry || '有效期未登记')},
      {label:'交付方',view:r=>named(r.sender,r.source)},
      {label:'交接时间 / 接收人',view:r=>named(r.receivedAt.slice(0,16).replace('T',' '),staffLabel(ctx,r.operator,r.operatorId))},
      {label:'操作',view:r=>link(ctx,'交接凭证',()=>open(r))}],
  });
}
