import { groups } from '../lib/navigation.js';
import { bindFlow, passwordFlow } from './identity.js';
import { canAct, node, page } from './shared.js';

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
    if (resident) details.push(['绑定长者', resident.name]);
  }
  const card = node('section', 'personal-identity', [
    node('div', 'personal-avatar', user.displayName.slice(0, 1)),
    node('div', 'personal-identity-body', [
      node('h2', '', user.displayName),
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
  const channels=(ctx.state.identityContacts||[]).map(c=>c.masked+(c.verified?'（已核实）':'（待激活）'));
  card.querySelector('dl').append(node('div','',[node('dt','','恢复方式'),node('dd','',channels.join('、')||'待绑定')]));
  return card;
}

function moduleLinks(ctx, allowed) {
  const content = node('div', 'personal-module-groups');
  for (const [group, items] of groups) {
    const links = [];
    for (const [id, label, icon] of items) {
      if (id === 'account' || !allowed.has(id)) continue;
      const anchor = node('a', 'personal-module-link', [
        ctx.ui.icon(icon, 17),
        node('span', '', id === 'family' && ctx.state.user.portalSelf ? '长者服务' : label),
        ctx.ui.icon('chevron', 13),
      ]);
      anchor.href = '#' + id;
      links.push(anchor);
    }
    if (links.length)
      content.append(
        node('section', 'personal-module-group', [
          node('h3', '', group),
          node('div', 'personal-module-links', links),
        ]),
      );
  }
  if (!content.childElementCount) content.append(ctx.ui.empty('当前账号暂无可用业务模块'));
  return node('section', 'fx-panel personal-panel', [
    node('h2', 'personal-panel-title', [ctx.ui.icon('layers', 19), '可用模块']),
    content,
  ]);
}

export function accountCenter(ctx) {
  const { routes, permissions } = ctx.state.selfAccess;
  const grants = node('section', 'fx-panel personal-panel', [
    node('h2', 'personal-panel-title', [ctx.ui.icon('shield', 19), '我的权限']),
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
    null,
    identity(ctx),
    node('div', 'personal-layout', [moduleLinks(ctx, new Set(routes)), grants]),
  );
}
