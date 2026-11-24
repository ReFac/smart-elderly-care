import { node, choose, btn, badge, facts, named, disclosure, section } from './shared.js';

const sharing = '站内简报包含当日照护工单数量、咳嗽观察是否提示增加，以及复核建议。';
const methods = ['长者当面确认', '长者电话确认', '长者书面确认'];

function consent(ctx, resident, recipient) {
  const enabled = !recipient.allowed;
  const title = enabled ? '同意分享巡查简报' : '撤回简报分享';
  const fields = [
    ['长者', resident.name],
    ['接收家属', recipient.name],
    ['站内简报', enabled ? '允许分享' : '撤回授权'],
  ];
  const submit = (details = {}) =>
    ctx.command(
      'family.consent',
      {
        residentId: resident.id,
        accountId: recipient.accountId,
        enabled,
        ...details,
      },
      {
        title,
        fields: [
          ...fields,
          ...(details.method
            ? [
                ['确认方式', details.method],
                ['意愿记录', details.evidence],
              ]
            : []),
        ],
      },
    );
  if (ctx.state.user.portalSelf) return submit();
  ctx.dialog({
    title: '登记长者意愿',
    description: resident.name + ' → ' + recipient.name + ' · ' + title + '。' + sharing,
    fields: [
      {
        name: 'method',
        label: '确认方式',
        type: 'select',
        options: methods,
        required: true,
      },
      {
        name: 'evidence',
        label: '长者意愿记录',
        type: 'textarea',
        required: true,
        maxLength: 240,
        placeholder: '记录确认经过或书面凭证位置。',
      },
    ],
    onSubmit: submit,
  });
}

export function familyRecipients(ctx, resident) {
  const recipients = (ctx.state.familyRoundRecipients || []).filter(
    (r) => r.residentId === resident.id,
  );
  const box = node('div', 'fx-profile', [
    node('p', 'fx-muted', sharing + '长者同意且家属订阅后，每天最多投递一次。'),
  ]);
  for (const recipient of recipients) {
    box.append(
      node('article', 'family-contact-card', [
        node('header', '', [
          named(recipient.name, recipient.subscribed ? '家属已订阅' : '家属未订阅'),
          badge(
            ctx,
            recipient.allowed ? '长者已同意' : '尚未授权',
            recipient.allowed ? 'green' : 'neutral',
          ),
        ]),
        recipient.decidedAt
          ? node(
              'small',
              'fx-muted',
              recipient.method + ' · ' + recipient.decidedAt.slice(0, 16).replace('T', ' '),
            )
          : null,
        recipient.evidence ? named('意愿记录', recipient.evidence) : null,
        choose(
          btn(ctx, recipient.allowed ? '撤回分享' : '同意分享', () =>
            consent(ctx, resident, recipient),
          ),
        ),
      ]),
    );
  }
  if (!recipients.length) box.append(node('p', 'fx-muted', '暂未绑定有效的家属账号。'));
  return ctx.state.user.portalSelf
    ? section('我的简报分享授权', box)
    : disclosure('家属简报分享授权', box, recipients.length);
}

export function familyInbox(ctx, resident) {
  const { subscribed, allowed, messages } = ctx.state.familyRoundInbox;
  const box = node('div', 'fx-profile', [
    node('header', 'fx-toolbar', [
      named('我的站内简报', sharing),
      btn(ctx, subscribed ? '取消订阅' : '订阅每日简报', () =>
        ctx.command(
          'family.subscribe',
          {
            residentId: resident.id,
            enabled: !subscribed,
          },
          {
            title: subscribed ? '取消家属简报订阅' : '订阅每日巡查简报',
            fields: [
              ['长者', resident.name],
              ['接收渠道', '本账号的站内收件箱'],
              ['订阅', subscribed ? '取消' : '开启'],
            ],
          },
        ),
      ),
    ]),
    node('p', 'fx-muted', [
      allowed ? '长者已同意分享。' : '等待长者同意分享。',
      subscribed ? '本账号已订阅。' : '本账号尚未订阅。',
      '任一方撤回后，历史简报也会停止展示。',
    ]),
  ]);
  if (!messages.length) box.append(node('p', 'fx-muted', '暂无可查看的巡查简报。'));
  for (const message of messages) {
    const counts = message.today;
    const card = node('article', 'family-contact-card', [
      node('header', '', [
        named(
          message.day + ' · 每日照护简报',
          '送达 ' + message.sentAt.slice(0, 16).replace('T', ' '),
        ),
        badge(ctx, message.readAt ? '已读' : '未读', message.readAt ? 'neutral' : 'blue'),
      ]),
      facts([
        ['计划工单', String(counts.planned)],
        ['已完成', String(counts.completed)],
        ['待完成', String(counts.pending)],
        ['已逾时', String(counts.overdue)],
      ]),
      message.coughIncreased
        ? node('p', '', '可比时段的咳嗽观察次数较近期增加。可联系护理人员了解人工复核情况。')
        : null,
      node(
        'small',
        'fx-muted',
        '巡查 Agent 根据机构记录整理，可能有遗漏。照护及健康情况请以护理人员核实为准。',
      ),
    ]);
    if (!message.readAt)
      card.append(
        choose(
          btn(ctx, '标为已读', () =>
            ctx.command(
              'family.read',
              {
                residentId: resident.id,
                messageId: message.id,
              },
              {
                title: '将巡查简报标为已读',
                fields: [
                  ['长者', resident.name],
                  ['简报日期', message.day],
                ],
              },
            ),
          ),
        ),
      );
    box.append(card);
  }
  return node('section', 'fx-panel family-round-inbox', box);
}
