import { residentLabel } from './people-labels.js';
import { node, choose, btn, badge, disclosure, facts, named, today, hasGrant } from './shared.js';

import {
  displayAmount,
  group,
  loadProfileChoices,
  moneyChoice,
  regionPicker,
  picker,
} from './profile-controls.js';

const roles = ['推荐联系人', '常用联系人', '紧急联系人'];
const kinds = ['配偶', '子女', '其他'];

async function edit(ctx, resident, member = {}) {
  let catalog;
  try {
    catalog = await loadProfileChoices();
  } catch (e) {
    ctx.toast(e.message);
    return;
  }
  const address = regionPicker(
    catalog.regions,
    '成员联系地址',
    member.addressRegion,
    member.address,
  );
  const kind = picker('成员类别', kinds, member.kind || '子女', true);
  kind.control.name = 'kind';
  const relation = picker('与长者的具体关系', [], member.relationship);
  relation.control.name = 'relationship';
  function updateRelations() {
    const options = catalog.choices.familyRelations[kind.control.value];
    const old = relation.control.value;
    relation.control.replaceChildren(new Option('未登记', ''));
    for (const opt of options) relation.control.add(new Option(opt, opt));
    if (
      member.kind === kind.control.value &&
      member.relationship &&
      !options.includes(member.relationship)
    )
      relation.control.add(new Option(member.relationship + '（原记录）', member.relationship));
    relation.control.value = old;
    if (relation.control.selectedIndex < 0) relation.control.value = '';
  }
  updateRelations();
  const status = picker(
    '是否提供经济支持',
    catalog.choices.supportStatus,
    member.supportStatus || '待核实',
  );
  const amount = moneyChoice(
    catalog.choices,
    '月均支持金额',
    member,
    'supportBand',
    'supportAmount',
  );
  for (const option of amount.band.options) if (option.value === '无') option.remove();
  amount.element.querySelector('input').min = '0.01';
  const support = group('子女经济支持', [status.element, amount.element]);
  function sync() {
    support.hidden = kind.control.value !== '子女';
    support.disabled = support.hidden;
    amount.element.hidden =
      support.hidden || !['提供定期支持', '提供不定期支持'].includes(status.control.value);
    amount.band.required = !amount.element.hidden;
    for (const input of amount.element.querySelectorAll('input'))
      input.required = !amount.element.hidden && amount.band.value === '精确金额';
  }
  sync();
  kind.control.onchange = () => {
    updateRelations();
    sync();
  };
  status.control.onchange = sync;

  const rolePicker = node(
    'fieldset',
    'family-role-picker',
    node('legend', '', '联系人用途（可多选）'),
  );
  const checks = roles.map((role) => {
    const input = node('input');
    input.type = 'checkbox';
    input.checked = (member.roles || []).includes(role);
    rolePicker.append(node('label', '', [input, role]));
    return input;
  });
  const entry = (name, label, options = {}) => ({
    name,
    label,
    value: member[name] || '',
    ...options,
  });
  ctx.dialog({
    title: member.id ? '编辑家庭成员' : '添加家庭成员',
    description: residentLabel(ctx, resident) + ' · 添加配偶、每一位子女或其他联系人。',
    content: node('div', 'dossier-form', [
      kind.element,
      relation.element,
      rolePicker,
      support,
      address.element,
    ]),
    fields: [
      entry('name', '姓名', { required: true, maxLength: 60 }),
      entry('phone', '联系电话（承担联系用途时必填）', {
        type: 'tel',
        maxLength: 40,
      }),
      entry('verification', '电话畅通情况', {
        type: 'select',
        value: 'keep',
        options: [
          {
            value: 'keep',
            label: member.verifiedOn ? '沿用上次人工核实日期' : '尚未人工核实',
          },
          { value: 'verify', label: '已人工拨通，登记核实日期' },
          { value: 'clear', label: '目前无法确认接通' },
        ],
      }),
      entry('verifiedOn', '本次人工拨通日期', {
        type: 'date',
        value: '',
        max: today(ctx),
      }),
      entry('note', '照护分工与联络备注', { type: 'textarea', maxLength: 300 }),
    ],
    onSubmit: ({ verification, verifiedOn, ...values }) => {
      if (values.kind === '子女') {
        values.supportStatus = status.control.value;
        if (!amount.element.hidden) Object.assign(values, amount.read());
      }
      const loc = address.read();
      if (loc !== undefined) values.addressRegion = loc;
      if (verification === 'verify' && !verifiedOn) throw new Error('请填写实际拨通电话的日期');
      if (verification !== 'verify' && verifiedOn)
        throw new Error('请在电话畅通情况中选择“已人工拨通”');
      const unchanged = values.phone.trim() === (member.phone || '');
      const memberRoles = roles.filter((_, index) => checks[index].checked);
      const checkedDate =
        verification === 'verify'
          ? verifiedOn
          : verification === 'keep' && unchanged
            ? member.verifiedOn || ''
            : '';
      return ctx.command(
        'dossier.profile',
        {
          residentId: resident.id,
          name: resident.name,
          familyContact: {
            ...values,
            id: member.id || '',
            roles: memberRoles,
            verifiedOn: checkedDate,
          },
        },
        {
          title: member.id ? '更新家庭成员资料' : '添加家庭成员',
          fields: [
            ['成员', values.name + ' · ' + values.kind],
            ['具体关系', values.relationship || '未填写'],
            ['用途', memberRoles.join('、') || '家庭成员'],
            ['电话', values.phone || '未填写'],
            ['人工拨通日期', checkedDate || '待核实'],
            [
              '联系地址',
              loc
                ? [address.label(), loc.detail].filter(Boolean).join(' · ') || '已清空'
                : member.address || '未填写',
            ],
            ...(values.kind === '子女'
              ? [
                  [
                    '经济支持',
                    [
                      values.supportStatus,
                      values.supportBand
                        ? displayAmount(values.supportBand, values.supportAmount)
                        : '',
                    ]
                      .filter(Boolean)
                      .join(' · '),
                  ],
                ]
              : []),
            ['联络备注', values.note || '未填写'],
          ],
        },
      );
    },
  });
}

export function contactBook(ctx, resident, profile, readOnly = false) {
  const members = profile.familyMembers || [];
  const box = node('div', 'fx-profile');
  if (!readOnly && hasGrant(ctx, 'intake'))
    box.append(choose(btn(ctx, '添加家庭成员', () => edit(ctx, resident))));
  if (resident.contact) box.append(named('原入住登记联系方式', resident.contact));
  if (!members.length) box.append(node('p', 'fx-muted', '尚未逐人登记配偶、子女及其他联系人。'));
  for (const kind of kinds) {
    for (const m of members.filter((item) => item.kind === kind)) {
      const card = node('article', 'family-contact-card', [
        node('header', '', [
          named(m.name, [m.kind, m.relationship].filter(Boolean).join(' · ')),
          node(
            'div',
            'family-contact-tags',
            m.roles.map((r) => badge(ctx, r, r === '紧急联系人' ? 'amber' : 'blue')),
          ),
        ]),
        facts([
          ['联系电话', m.phone],
          ['最后人工拨通', m.verifiedOn || (m.phone ? '尚待核实' : '')],
          ['联系地址', m.address],
          ...(kind === '子女'
            ? [
                ['经济支持', m.supportStatus || '未登记'],
                ['月均支持金额', displayAmount(m.supportBand, m.supportAmount)],
              ]
            : []),
          ['照护分工与备注', m.note],
        ]),
      ]);
      if (!readOnly && hasGrant(ctx, 'intake'))
        card.append(
          choose(
            btn(ctx, '编辑', () => edit(ctx, resident, m)),
            btn(ctx, '移除', () =>
              ctx.command(
                'dossier.profile',
                {
                  residentId: resident.id,
                  name: resident.name,
                  familyContact: { id: m.id, remove: true },
                },
                {
                  title: '移除家庭成员',
                  fields: [
                    ['档案', residentLabel(ctx, resident)],
                    ['移除成员', m.name + ' · ' + m.kind],
                  ],
                },
              ),
            ),
          ),
        );
      box.append(card);
    }
  }
  return disclosure('家庭成员与联系人', box, members.length);
}
