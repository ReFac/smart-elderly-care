import { groups } from '../lib/navigation.js';
import { canAct, field, node, page } from './shared.js';

const passwordAction = 'account.changePassword';

function changePassword(ctx) {
  const dialog = ctx.dialog({
    title: '修改我的密码',
    description: '新密码须为 10 至 128 个字符。保存后，所有设备都需使用新密码重新登录。',
    fields: [
      field('currentPassword', '当前密码', { type: 'password', maxLength: 128 }),
      field('newPassword', '新密码', { type: 'password', maxLength: 128 }),
      field('confirmation', '再次输入新密码', { type: 'password', maxLength: 128 }),
    ],
    submitLabel: '保存新密码',
    onSubmit: async ({ currentPassword, newPassword, confirmation }) => {
      if ([...newPassword].length < 10) throw new Error('新密码至少需要 10 个字符。');
      if (newPassword === currentPassword) throw new Error('新密码须与当前密码不同。');
      if (newPassword !== confirmation) throw new Error('两次输入的新密码不一致。');
      const saved = await ctx.command(passwordAction, { currentPassword, newPassword });
      if (saved) ctx.toast('密码已更新，请使用新密码重新登录。');
      return saved;
    },
  });
  const controls = dialog.querySelector('form').elements;
  controls.currentPassword.autocomplete = 'current-password';
  for (const name of ['newPassword', 'confirmation']) {
    controls[name].autocomplete = 'new-password';
    controls[name].minLength = 10;
  }
}

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
    card.append(ctx.ui.button('修改密码', () => changePassword(ctx), 'secondary', 'shield'));
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
