import { residentLabel, staffLabel } from './people-labels.js';
import { menuFor } from '../lib/desk-navigation.js';
import { colorModeControl } from '../lib/color-mode.js';
import { openEmployment } from './staff-employment.js';
import { bindFlow, passwordFlow } from './identity.js';
import { passkeyButton, passkeySettings } from './passkeys.js';
import { canAct, node, page, tabs, table, btn } from './shared.js';
import { canOpenPermissionRequests, openPermissionRequests } from './permission-requests.js';

const passwordAction = 'account.changePassword';

function identity(ctx) {
  const { user, uiSettings, residents } = ctx.state;
  const details = [
    ['登录账号', user.username],
    ['所属机构', uiSettings.institutionName],
    ['当前岗位', user.role],
  ];
  if (user.kind === 'family') {
    const resident = residents.find((r) => r.id === user.residentId);
    if (resident) details.push(['绑定长辈', residentLabel(ctx, resident)]);
  } else if (ctx.state.signatureRealName || canAct(ctx, 'permissionRequest.review')) {
    details.push(['签名实名', ctx.state.signatureRealName || '待 Owner 登记']);
  }
  const card = node('section', 'personal-identity', [
    node('div', 'personal-avatar', user.displayName.slice(0, 1)),
    node('div', 'personal-identity-body', [
      node('h2', '', staffLabel(ctx, user)),
      node(
        'dl',
        'personal-details',
        details.map(([label, value]) =>
          node('div', '', [node('dt', '', label), node('dd', '', value)]),
        ),
      ),
    ]),
  ]);
  if (canAct(ctx, passwordAction))
    card.append(ctx.ui.button('修改密码', () => passwordFlow({username:user.username, locked:true}), 'secondary', 'shield'));
  card.append(ctx.ui.button('验证联系方式',()=>bindFlow(ctx),'secondary'));
  card.append(passkeyButton('通行密钥（Passkey）', passkeySettings));
  if (user.kind === 'staff')
    card.append(ctx.ui.button('我的劳动合同与工资日', () => openEmployment(ctx, user), 'secondary'));
  const channels=(ctx.state.identityContacts||[]).map(c=>c.masked+(c.verified?'（已核实）':'（待激活）'));
  card.querySelector('dl').append(node('div','',[node('dt','','恢复方式'),node('dd','',channels.join('、')||'待绑定')]));
  return card;
}

function moduleLinks(ctx) {
  const rows = menuFor(ctx).flatMap(group=>group.children
    ? group.children.map(([route,label,tab])=>({group:group.label,label,route,tab}))
    : [{group:'工作台',label:group.label,route:group.route,view:group.view}]);
  return table(ctx,{title:'本人可用的业务入口',rows,
    search:{placeholder:'搜索栏目或页面',value:r=>r.group + ' ' + r.label},
    cols:[{label:'栏目',view:r=>r.group},{label:'页面',view:r=>r.label},{label:'操作',align:'end',
      view:r=>btn(ctx,'打开',()=>ctx.go(r.route,r.tab,undefined,r.view ? {view:r.view} : undefined),'ghost')}],
  });
}

export function accountCenter(ctx) {
  const { permissions } = ctx.state.selfAccess;
  const grants = node('section', 'fx-panel personal-panel', [
    node('h2', 'personal-panel-title', [ctx.ui.icon('shield', 19), '我的权限']),
    canOpenPermissionRequests(ctx)
      ? ctx.ui.button('权限申请', () => openPermissionRequests(ctx), 'secondary', 'shield') : null,
    permissions.length
      ? node(
          'ul',
          'personal-grants',
          permissions.map(({ label }) =>
            node('li', '', [ctx.ui.icon('check', 15), node('span', '', label)]),
          ),
        )
      : node(
          'p',
          'personal-empty',
          ctx.state.user.kind === 'family'
            ? '此账号使用机构为本人开放的亲属服务。'
            : '尚未分配业务操作权限，请联系机构管理员。',
        ),
  ]);
  return page(
    ctx,
    '个人中心',
    '',
    colorModeControl(),
    tabs('account',[
      ['identity','账户资料',()=>identity(ctx)],
      ['grants','我的权限',()=>grants],
      ['modules','可用页面',()=>moduleLinks(ctx)],
    ]),
  );
}
