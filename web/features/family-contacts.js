import { node, choose, btn, badge, disclosure, facts, named, today, hasGrant } from './shared.js';

const roles = ['推荐联系人', '常用联系人', '紧急联系人'];
const kinds = ['配偶', '子女', '其他'];

function edit(ctx, resident, member = {}) {
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
    description: resident.name + ' · 添加配偶、每一位子女或其他联系人。',
    content: rolePicker,
    fields: [
      entry('kind', '成员类别', {
        type: 'select',
        options: kinds,
        value: member.kind || '子女',
      }),
      entry('name', '姓名', { required: true, maxLength: 60 }),
      entry('relationship', '与长者的具体关系', {
        placeholder: '例如：次女、侄子',
        maxLength: 50,
      }),
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
      entry('address', '成员联系地址', { maxLength: 300 }),
      entry('note', '照护分工与联络备注', { type: 'textarea', maxLength: 300 }),
    ],
    onSubmit: ({ verification, verifiedOn, ...values }) => {
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
            ['联系地址', values.address || '未填写'],
            ['联络备注', values.note || '未填写'],
          ],
        },
      );
    },
  });
}

export function contactBook(ctx, resident, profile) {
  const members = profile.familyMembers || [];
  const box = node('div', 'fx-profile');
  if (hasGrant(ctx, 'intake'))
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
          ['照护分工与备注', m.note],
        ]),
      ]);
      if (hasGrant(ctx, 'intake'))
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
                    ['档案', resident.name],
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
