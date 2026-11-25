import { displayLocale } from '../lib/locale.js';
import { btn, facts, field, node, page, section, select, table } from './shared.js';

const providers = {deepseek:'DeepSeek', openai:'OpenAI / 兼容服务', anthropic:'Anthropic', google:'Google'};
const titles = values => values.map(value => ({value,label:value}));
const stamp = seconds => seconds ? new Date(seconds * 1000).toLocaleString(displayLocale,{hour12:false}) : '—';
const planStates = {available:'可用',inactive:'未开通或已到期',exhausted:'套餐额度已用完',unconfigured:'服务尚未配置',no_scope:'待配置业务范围'};

async function request(path = '', data) {
  const response = await fetch('/api/deployment' + path, data === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || '部署设置暂不可用');
  return result;
}

export function deploymentConsole(ctx) {
  if (ctx.state.user.kind !== 'owner') return ctx.ui.empty('仅 Owner 可查看部署设置');
  const body = node('div','fx-profile');
  let view, sequence = 0;
  const latest = async () => {
    const id = ++sequence;
    try {
      const result = await request();
      if (id === sequence) draw(result);
    } catch (err) {
      if (id === sequence) body.replaceChildren(ctx.ui.empty(err.message));
    }
  };
  const after = async (path, data) => { ++sequence; draw(await request(path,data)); return true; };

  function edit() {
    const current = view.draft || view.running, revision = view.revision;
    const dialog = ctx.dialog({title:'编辑部署配置',submitLabel:'保存待应用配置',
      description:'密钥仅写入后台加密运维库。保存后可继续使用当前连接，在重启服务时应用已批准的配置。',
      fields:[
        select('provider','模型服务商',Object.entries(providers).map(([value,label])=>({value,label})),{value:current.provider}),
        field('model','模型编号',{value:current.model,maxLength:180}),
        select('endpoint','API 端点',titles(view.allowedEndpoints[current.provider] || []),{value:current.endpoint}),
        field('key','服务端密钥',{type:'password',required:false,maxLength:512,placeholder:'留空使用该端点已有凭据'}),
        select('host','监听地址',titles(view.networkBind ? ['127.0.0.1','0.0.0.0'] : ['127.0.0.1']),{value:current.host}),
        field('port','监听端口',{type:'number',min:1,max:65535,value:current.port}),
        select('policy','应用策略',[{value:'manual',label:'保存后另行批准'},{value:'next-start',label:'下次重启时应用'}],{value:view.policy}),
      ],
      onSubmit:({provider,model,endpoint,key,host,port,policy})=>after('/settings',{
        action:'save',revision,policy,key,config:{provider,model,endpoint,host,port:Number(port)},
      }),
    });
    const form = dialog.querySelector('form'), fields = form.elements;
    fields.key.autocomplete='new-password';
    fields.port.readOnly = view.portPinned;
    fields.port.title = view.portPinned ? '当前端口由启动参数固定' : '';
    fields.model.readOnly = current.provider === 'deepseek';
    fields.provider.addEventListener('change',()=>{
      const kind = fields.provider.value;
      fields.endpoint.replaceChildren(...view.allowedEndpoints[kind].map(url=>new Option(url,url)));
      fields.key.value = '';
      fields.model.readOnly = kind === 'deepseek';
      fields.model.value = kind === 'deepseek' ? 'deepseek-flash' : kind === current.provider ? current.model : '';
    });
    fields.endpoint.addEventListener('change',()=>{fields.key.value='';});
  }

  function pending(action) {
    const revision = view.revision, arm = action === 'arm';
    ctx.dialog({title:arm?'批准下次重启应用':'撤回待应用配置',fields:[],
      description:arm?'运维人员下次启动服务时将应用这份配置。':'撤回后继续使用当前部署参数。',
      submitLabel:arm?'批准':'撤回',onSubmit:()=>after('/settings',{action,revision})});
  }

  function device(existing) {
    const dialog = ctx.dialog({
      title:existing ? '修改设备网关' : '登记设备网关',submitLabel:'保存网关',
      description:'网关使用专用令牌上报心跳。MQTT 和 Modbus 由院内网桥适配，平台显示最近一次已验证的 HTTP 心跳。',
      fields:[field('id','网关编号',{value:existing?.id || '',maxLength:48}),
        field('label','设备名称',{value:existing?.label || '',maxLength:60}),
        select('transport','边缘接入方式',titles(view.gatewayTypes),{value:existing?.transport}),
        select('enabled','连接状态',[{value:'yes',label:'允许接入'},{value:'no',label:'暂停接入'}],{value:existing?.enabled===false?'no':'yes'}),
        field('secret',existing?'轮换专用令牌（留空沿用）':'设备专用令牌',{type:'password',required:!existing,maxLength:128,placeholder:'32–128 位随机字符'})],
      onSubmit:fields=>after('/devices',{...fields,enabled:fields.enabled==='yes'}),
    });
    const fields=dialog.querySelector('form').elements;
    fields.id.readOnly=!!existing; fields.secret.autocomplete='new-password';
  }

  function draw(data) {
    view=data;
    const running=view.running, own=view.mode==='operator';
    const sections=[section('当前部署',facts([
      ['运行版本',view.version],['部署角色',own?'平台自营部署':'机构托管套餐'],
      ['机构类型',view.profile==='licensed-medical'?'持证医疗机构':'养老服务机构'],
      ['部署语言',view.locale.languageName],
      ['地图服务',view.locale.mapProvider==='google'?'Google Maps':'高德地图'],
      ['服务商',providers[running.provider] || running.provider],['模型',running.model || '待配置'],
      ['服务凭据',view.credentialConfigured?'已配置':'待配置'],
      ['套餐',view.plan.name || '尚未开通'],['服务状态',planStates[view.plan.status] || view.plan.status],
      ...(own?[['监听地址',running.host + ':' + running.port],['访问入口',view.publicOrigin || '本机访问'],
        ['模型端点',running.endpoint],['端口来源',view.portPinned?'启动命令指定':'部署配置']]:[]),
    ]))];
    if (own) {
      const d=view.draft;
      const details=d?facts([['应用策略',view.policy==='next-start'?'已批准 · 下次服务重启应用':'等待 Owner 批准'],
        ['模型',providers[d.provider]+' · '+d.model],['端点',d.endpoint],['监听地址',d.host+':'+d.port]]):
        node('p','muted','当前没有待应用配置。');
      sections.push(section('部署变更',node('div','fx-profile',[details,
        node('div','fx-actions',[btn(ctx,'编辑部署配置',edit,'primary'),
          d && view.policy==='manual' && btn(ctx,'批准下次启动应用',()=>pending('arm')),
          d && btn(ctx,'撤回配置',()=>pending('discard'))])])));
    } else {
      sections.push(section('机构 API 套餐',node('div','fx-profile',[
        node('p','','模型服务由平台提供，套餐付费、续期及技术支持请联系平台运营方。'),
        btn(ctx,'查看套餐与用量',()=>ctx.go('settings','providerPlan'))])));
    }
    sections.push(table(ctx,{title:'设备网关连接',action:btn(ctx,'登记设备网关',()=>device(),'primary'),rows:view.devices,
      empty:'尚未登记设备网关',cols:[{label:'名称',view:r=>r.label},{label:'心跳路径',view:r=>node('code','','/api/deployment/gateways/'+r.id+'/heartbeat')},
        {label:'边缘接入',view:r=>r.transport},{label:'接入状态',view:r=>r.status},
        {label:'最近心跳',view:r=>stamp(r.lastSeen)},{label:'操作',view:r=>btn(ctx,'管理连接',()=>device(r))}]}));
    sections.push(table(ctx,{title:'部署变更记录',rows:view.recent,empty:'尚无部署变更',
      cols:[{label:'时间',view:r=>stamp(r.at)},{label:'操作人',view:r=>r.actor},{label:'变更',view:r=>r.message}]}));
    body.replaceChildren(...sections);
  }
  body.append(node('p','muted','正在读取部署状态…')); latest();
  return page(ctx,'部署控制台','',btn(ctx,'刷新状态',latest),body);
}
