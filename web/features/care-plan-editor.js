import { badge, btn, canAct, choose, facts, node, residentName, staffField } from './shared.js';

const categories = ['生活照料','健康观察','康复支持','服务设施','其他'];
const roles = ['护工','护士','护士长','院长'];
const duties = ['日常照护','临床护理','康复支持'];
const week = ['一','二','三','四','五','六','日'];
const periods = [['once','仅一次'],['daily','每日'],['weekly','每周']];

function input(type, label, value) {
  const el = node('input', 'plan-input');
  el.type = type;
  el.setAttribute('aria-label', label);
  if (type === 'checkbox') el.checked = !!value;
  else el.value = value;
  return el;
}

function choice(label, values, value) {
  const el = node('select', 'plan-input');
  el.setAttribute('aria-label', label);
  for (const item of values) {
    const [id, name] = Array.isArray(item) ? item : [item, item];
    el.add(new Option(name, id));
  }
  el.value = value;
  return el;
}

function newItem(title, assignee) {
  return {title, category:categories[0], period:'once', weekday:1, count:1, times:['09:00'], roles:[...roles], assignee, enabled:true};
}

export function restoreCarePlanTab(ctx, id) {
  if (!id.startsWith('plan-') || !canAct(ctx,'care.revisePlan')) return null;
  const planId = id.slice(5);
  if (!ctx.state.plans?.some(p => p.id === planId)) return null;
  return {id, tab:'plans', title:'照护计划调整', render: live => {
    const plan = live.state.plans?.find(p=>p.id === planId);
    if (!plan || !canAct(live,'care.revisePlan')) return node('p','','当前账号无法访问此计划');
    return editor(live, plan);
  }};
}

export function openCarePlan(ctx, plan) {
  const tab = restoreCarePlanTab(ctx, 'plan-' + plan.id);
  if (tab) ctx.openWorkspaceTab('assessments', tab);
}

function editor(ctx, plan) {
  const person = ctx.state.residents.find(p => p.id === plan.residentId);
  const sourceItems = plan.serviceItems || (plan.items || ['执行个体照护计划']).map(title => newItem(title, plan.assignee));
  const signature = JSON.stringify([plan,person?.status]);
  const saved = ctx.workspaceState || {};
  if (saved.planSignature !== signature) {
    saved.planSignature = signature;
    saved.items = structuredClone(sourceItems);
    saved.marked = new Set();
    saved.search = '';
  }
  const items = saved.items;
  const selected = saved.marked;
  const staff = staffField(ctx, 'assignee','执行人员',{value:plan.assignee}).options
    .filter(p => p.value).map(p => [p.value,p.label]);
  for (const item of items) if (!staff.some(([id])=>id===item.assignee)) staff.push([item.assignee,item.assignee]);
  const root = node('section','plan-editor');
  root.dataset.roundsResidentId = plan.residentId;
  const status = plan.supersededBy ? '历史版本' : plan.status;
  const readOnly = !person || person.status !== '在住' || !!plan.supersededBy || !['已派发','待复核'].includes(status);
  root.append(node('h2','','编辑照护计划'),node('p','plan-note',
    readOnly ? '此计划已归档，可查阅审核时的项目设置。' :
    status === '已派发' ? '当前方案正在执行。调整提交后进入待复核，审核通过后切换执行安排。' : '当前方案待复核。可逐项调整照护内容，核对后提交审核。'));
  root.append(node('header','plan-person',[
    node('span','plan-avatar',person?.name?.slice(0,1) || '档'), node('div','',[node('strong','',residentName(ctx,plan.residentId)),
      node('p','',[(person?.gender||''),person?.age ? person.age+'岁' : '',person?.admittedAt ? '入住 '+person.admittedAt : ''].filter(Boolean).join(' · '))]),badge(ctx,status),
  ]));
  root.append(facts([['照护等级',ctx.state.assessments.find(a=>a.id===plan.assessmentId)?.level || person?.level],
    ['服务方案',plan.title],['负责人员',plan.assignee],['复评日期',plan.reviewDate]]));
  const search = input('search','搜索项目名称',saved.search); search.placeholder='搜索项目名称';
  const bulk = choice('批量选择执行人员',[['','选择执行人员'],...staff],'');
  const count = node('small','','');
  const body = node('tbody','');
  const grid = node('table','plan-grid');
  const checkAll = input('checkbox','选择当前可见项目',false);
  const visible = () => items.filter(item=>item.title.includes(search.value.trim()));
  function markCount() {
    count.textContent = '共 '+items.length+' 项 · 已选 '+selected.size+' 项';
    const rows = visible();
    checkAll.checked = !!rows.length && rows.every(item=>selected.has(item));
    checkAll.indeterminate = !checkAll.checked && rows.some(item=>selected.has(item));
  }
  function td(...elements) { return node('td','',elements); }
  function redraw() {
    body.replaceChildren();
    for (const item of visible()) {
      const toggle = input('checkbox','选择项目 '+item.title,selected.has(item));
      toggle.onchange=()=>{if(toggle.checked) selected.add(item); else selected.delete(item); markCount();};
      const cat = choice('项目分类',categories,item.category); cat.onchange=()=>{item.category=cat.value;};
      const name = input('text','项目名称',item.title); name.maxLength=80;
      name.oninput=()=>{item.title=name.value;};
      const period = choice('执行周期',periods,item.period);
      period.onchange=()=>{item.period=period.value; redraw();};
      const n=input('number','每次派发数量',item.count); n.min=1; n.max=12;
      n.onchange=()=>{if(!n.reportValidity()||!n.value) return; item.count=Number(n.value);
        if(item.times.length) item.times=Array.from({length:item.count},(_,i)=>item.times[i]||''); redraw();};
      const day = choice('执行星期',week.map((v,i)=>[String(i+1),'星期'+v]),String(item.weekday));
      day.onchange=()=>{item.weekday=Number(day.value);};
      const timed = input('checkbox','按时间点执行',item.times.length>0);
      timed.onchange=()=>{item.times=timed.checked?Array(item.count).fill(''):[]; redraw();};
      const times=item.times.map((v,i)=>{const t=input('time','执行时点 '+(i+1),v); t.required=true;
        t.oninput=()=>{item.times[i]=t.value;}; return t;});
      function roleOption(r) {
        const c = input('checkbox','可执行岗位或职责 '+r,item.roles.includes(r));
        c.onchange = () => {item.roles = c.checked ? [...item.roles,r] : item.roles.filter(v=>v!==r);};
        return node('label','',[c,r]);
      }
      const custom = node('details','plan-custom-duties',[
        node('summary','','自定义岗位职责'), ...duties.map(roleOption),
      ]);
      custom.open = item.roles.some(value => duties.includes(value));
      const allowed = node('div','plan-roles',[...roles.map(roleOption),custom]);
      const assigned=choice('执行人员',staff,item.assignee); assigned.onchange=()=>{item.assignee=assigned.value;};
      const enabled=input('checkbox','启用 '+item.title,item.enabled); enabled.onchange=()=>{item.enabled=enabled.checked;};
      const remove=btn(ctx,'移除',()=>{items.splice(items.indexOf(item),1); selected.delete(item); redraw();},'ghost');
      const row = node('tr','',[td(toggle),td(cat),td(name),td(node('div','plan-frequency',[period,
        item.period==='weekly'?day:null,n,'次',node('label','',[timed,'按时点']),...times])),td(allowed),td(assigned),td(enabled),td(remove)]);
      if(readOnly) for(const control of row.querySelectorAll('input,select,button')) control.disabled=true;
      body.append(row);
    }
    markCount();
  }
  const labels=[checkAll,'项目分类','项目名称','执行频次与时点','可执行岗位或职责','执行人员','启用','操作'];
  grid.append(node('thead','',node('tr','',labels.map(v=>node('th','',v)))),body);
  checkAll.disabled=readOnly;
  checkAll.onchange=()=>{for(const item of visible()) {if(checkAll.checked)selected.add(item);else selected.delete(item);} redraw();};
  search.oninput=()=>{saved.search=search.value;redraw();};
  const apply=btn(ctx,'批量维护执行人员',()=>{
    if(!selected.size || !bulk.value) return ctx.toast('请先勾选项目并选择人员');
    for(const row of selected) row.assignee=bulk.value;
    redraw();
  });
  const add=btn(ctx,'新增项目',()=>{saved.search=search.value=''; items.push(newItem('',plan.assignee)); redraw();
    body.lastElementChild.querySelector('[aria-label="项目名称"]').focus();});
  const footer = node('footer','plan-footer',[
    btn(ctx,'返回照护方案',()=>ctx.closeWorkspaceTab()),
    readOnly?null:btn(ctx,'保存并提交复核',async()=>{
      if (!items.length || items.some(r=>!r.title.trim() || !r.assignee || !r.roles.length ||
          (r.times.length && (r.times.some(v=>!v)||new Set(r.times).size!==r.count)))) {
        return ctx.toast('请核对项目名称、执行人员、岗位与时点');
      }
      const ok=await ctx.command('care.revisePlan',{planId:plan.id,serviceItems:items},{
        title:'提交照护计划调整',target:residentName(ctx,plan.residentId),fields:[['启用照护项目',items.filter(r=>r.enabled).length+' 项']]});
      if(ok){ctx.closeWorkspaceTab();ctx.go('assessments','plans');}
    },'primary'),
  ]);
  root.append(node('div','plan-toolbar',[node('h3','','计划项目编辑'),count,search,readOnly?null:choose(bulk,apply,add)]),
    node('div','plan-scroll',grid),footer); redraw(); return root;
}
