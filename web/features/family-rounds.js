import { residentLabel } from './people-labels.js';
import { node, choose, btn, badge, facts, named, disclosure, section, table, link, canAct } from './shared.js';

const sharing = '站内简报包含当日照护工单数量、咳嗽观察是否提示增加，以及复核建议。';
const methods = ['长辈当面确认', '长辈电话确认', '长辈书面确认'];

function consent(ctx, resident, recipient) {
  const enabled = !recipient.allowed;
  const title = enabled ? '同意分享巡查简报' : '撤回简报分享';
  const fields = [
    ['长辈', residentLabel(ctx, resident)],
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
    title: '登记长辈意愿',
    description: residentLabel(ctx, resident) + ' → ' + recipient.name + ' · ' + title + '。' + sharing,
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
        label: '长辈意愿记录',
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
    node('p', 'fx-muted', sharing + '长辈同意且家属订阅后，每天最多投递一次。'),
  ]);
  for (const recipient of recipients) {
    box.append(
      node('article', 'family-contact-card', [
        node('header', '', [
          named(recipient.name, recipient.subscribed ? '家属已订阅' : '家属未订阅'),
          badge(
            ctx,
            recipient.allowed ? '长辈已同意' : '尚未授权',
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
  const {subscribed, allowed, messages} = ctx.state.familyRoundInbox;
  const rows = [...messages].sort((a, b) => b.sentAt.localeCompare(a.sentAt));
  const sent = message => message.sentAt.slice(0, 16).replace('T', ' ');
  function markRead(message, dialog) {
    return ctx.command('family.read', {residentId: resident.id, messageId: message.id}, {
      title: '将巡查简报标为已读', fields: [['长辈', residentLabel(ctx, resident)], ['简报日期', message.day]],
    }).then(result => { if (result) dialog?.close(); });
  }
  function open(message) {
    const counts = message.today;
    const content = node('article', 'family-brief-detail', [
      named(message.day + ' · 每日照护简报', '送达 ' + sent(message)),
      facts([['计划工单', String(counts.planned)], ['已完成', String(counts.completed)],
        ['待完成', String(counts.pending)], ['已逾时', String(counts.overdue)]]),
      message.coughIncreased ? node('p', '', '同一时段的咳嗽观察次数比近期多，可联系护理人员了解复核情况。') : null,
      node('p', 'fx-muted', '简报根据机构记录整理。照护及健康情况请以护理人员核实为准。'),
    ]);
    const dialog = ctx.detail('巡查简报详情', content);
    if (!message.readAt && canAct(ctx, 'family.read')) {
      content.append(choose(btn(ctx, '标为已读', () => markRead(message, dialog))));
    }
  }
  const subscribe = canAct(ctx, 'family.subscribe') ? btn(ctx, subscribed ? '取消订阅' : '订阅每日简报', () =>
    ctx.command('family.subscribe', {residentId: resident.id, enabled: !subscribed}, {
      title: subscribed ? '取消家属简报订阅' : '订阅每日巡查简报',
      fields: [['长辈', residentLabel(ctx, resident)], ['接收渠道', '本账号的站内收件箱'], ['订阅', subscribed ? '取消' : '开启']],
    })) : null;
  return node('section', 'family-mail', [
    node('header', 'family-mail-policy', [
      named('每日照护简报', (allowed ? '长辈已同意分享' : '等待长辈同意分享') + ' · ' +
        (subscribed ? '已订阅' : '未订阅') + '。任一方撤回后，历史简报也会停止展示。'), subscribe,
    ]),
    table(ctx, {
      title: '站内收件箱', rows, empty: '暂无可查看的巡查简报。',
      filter: {label: '阅读状态', all: '全部消息', options: ['未读', '已读'], value: m => m.readAt ? '已读' : '未读'},
      cols: [
        {label: '消息', view: m => link(ctx, m.day + ' · 每日照护简报', () => open(m))},
        {label: '送达时间', view: sent},
        {label: '状态', view: m => badge(ctx, m.readAt ? '已读' : '未读', m.readAt ? 'neutral' : 'blue')},
        {label: '操作', view: m => link(ctx, '查看简报', () => open(m))},
      ],
    }),
  ]);
}
