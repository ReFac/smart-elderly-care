import { detail } from '../lib/dialogs.js';
import { node } from './shared.js';

const names = { email: '邮箱', sms: '手机' };
const labels = (items) => items.map((key) => [key, names[key]]);

export async function api(path, body) {
  const response = await fetch(
    '/api/auth/' + path,
    body === undefined
      ? { cache: 'no-store' }
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
  );
  const result = await response.json();
  if (!response.ok) throw Error(result.error || '操作未完成');
  return result;
}

export function wizard(title) {
  const form = node('form', 'access-form');
  const dialog = detail(title, form);
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  function step(note, controls, label, action) {
    error.textContent = '';
    const submit = node('button', 'btn btn-primary', label);
    submit.type = 'submit';
    form.replaceChildren(
      node('p', 'fx-muted', note),
      ...controls.map((c) => c.label),
      error,
      submit,
    );
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      submit.disabled = true;
      error.textContent = '';
      try {
        await action(Object.fromEntries(controls.map((c) => [c.input.name, c.input.value])));
      } catch (e) {
        error.textContent = e.message;
      } finally {
        submit.disabled = false;
      }
    };
  }
  function message(text) {
    form.replaceChildren(node('p', 'fx-muted', text));
  }
  return { step, message, dialog };
}

export function field(name, title, type, opts = {}) {
  const input = node(type === 'select' ? 'select' : 'input');
  input.name = name;
  input.required = true;
  if (type === 'select')
    for (const [value, label] of opts.choices) input.add(new Option(label, value));
  else Object.assign(input, { type, maxLength: 128, autocomplete: 'off' });
  if (opts.value) input.value = opts.value;
  if (opts.readOnly) input.readOnly = true;
  if (name === 'code' || name === 'existingCode')
    Object.assign(input, {
      inputMode: 'numeric',
      pattern: '[0-9]{8}',
      maxLength: 8,
      autocomplete: 'one-time-code',
    });
  if (name === 'destination') input.maxLength = 254;
  if (type === 'password')
    input.autocomplete = name === 'currentPassword' ? 'current-password' : 'new-password';
  return { input, label: node('label', 'field', [node('span', '', title), input]) };
}

function receipt(view, note, complete) {
  view.step(note, [field('code', '8 位验证码', 'text')], '确认核验', (v) => complete(v.code));
}

export async function passwordFlow({ username = '', locked = false } = {}) {
  const view = wizard(locked ? '验证身份并修改密码' : '首次设置 / 找回密码');
  try {
    const { channels } = await api('channels');
    if (!channels.length) {
      view.message('机构尚未配置验证码投递渠道。请联系机构开通邮件或短信服务。');
      return;
    }
    view.step(
      '验证码将发送至账号登记的联系方式。',
      [
        field('username', '登录账号', 'text', { value: username, readOnly: locked }),
        field('channel', '验证方式', 'select', { choices: labels(channels) }),
      ],
      '申请验证码',
      async (v) => {
        const { challenge } = await api('code', { ...v, purpose: 'password' });
        view.step(
          '如账号已登记此渠道，请在 10 分钟内输入收到的验证码。确认后，原有登录会话和通行密钥将失效。',
          [
            field('code', '8 位验证码', 'text'),
            field('newPassword', '新密码（10 至 128 字符）', 'password'),
            field('repeat', '确认新密码', 'password'),
          ],
          '确认设置密码',
          async (values) => {
            if (values.newPassword !== values.repeat) throw Error('两次输入的新密码不一致');
            await api('verify', {
              purpose: 'password',
              challenge,
              code: values.code,
              newPassword: values.newPassword,
            });
            if (locked) location.reload();
            else view.message('密码已设置。关闭此窗口后，可使用新密码登录。');
          },
        );
      },
    );
  } catch (e) {
    view.message(e.message);
  }
}

export function sendPasswordReset(account) {
  const view = wizard('发送密码重置链接');
  view.step(
    '将链接发给 ' + account.displayName + '（' + account.username + '）。账号本人通过链接设置新密码，链接在 10 分钟内有效。',
    [],
    '确认发送',
    async () => {
      const result = await api('reset-link/send', { id: account.id });
      view.message('已发送至' + names[result.channel] + ' ' + result.masked + '。');
    },
  );
}

export function redeemPasswordReset(token, setUsername) {
  const view = wizard('设置新密码');
  view.step(
    '请输入本人用于登录的新密码。保存后，原有登录会话和通行密钥将失效。',
    [field('newPassword', '新密码（10 至 128 字符）', 'password'),
     field('repeat', '确认新密码', 'password')],
    '确认设置密码',
    async ({ newPassword, repeat }) => {
      if (newPassword !== repeat) throw Error('两次输入的新密码不一致');
      const { username } = await api('reset-link/redeem', { token, newPassword });
      setUsername(username);
      view.message('密码已设置。你的登录名是 ' + username + '。关闭此窗口即可使用新密码登录。');
    },
  );
}

export function bindFlow(ctx) {
  const view = wizard('验证本人联系方式');
  const choices = ctx.state.identityChannels || [];
  if (!choices.length) {
    view.message('机构尚未配置验证码投递渠道，请先由部署人员接通邮件或短信。');
    return;
  }
  const registered = (ctx.state.identityContacts || []).filter((c) => c.verified);
  function enter(prior) {
    const channel = field('channel', '新的验证方式', 'select', { choices: labels(choices) });
    const dst = field('destination', '接收验证码的联系方式', 'text');
    const adapt = () => {
      dst.input.type = channel.input.value === 'email' ? 'email' : 'tel';
    };
    channel.input.onchange = adapt;
    adapt();
    const controls = [field('currentPassword', '当前密码', 'password'), channel, dst];
    if (prior) controls.unshift(field('existingCode', '原验证渠道收到的验证码', 'text'));
    view.step(
      '核实本人当前密码，并使用实际收到的验证码完成绑定。',
      controls,
      '发送至新联系方式',
      async (v) => {
        const result = await api('code', {
          ...v,
          purpose: 'bind',
          ...(prior ? { existingChallenge: prior } : {}),
        });
        receipt(view, '请输入新的联系方式实际收到的验证码。', async (code) => {
          await api('verify', { purpose: 'bind', challenge: result.challenge, code });
          view.dialog.close();
          await ctx.refreshWorkspace();
          ctx.toast('验证联系方式已保存');
        });
      },
    );
  }
  if (!registered.length) {
    enter(null);
    return;
  }
  const eligible = registered.filter((c) => choices.includes(c.channel));
  if (!eligible.length) {
    view.message('原验证渠道暂未接通，请联系机构恢复该渠道后再更新。');
    return;
  }
  view.step(
    '更新恢复方式需先核验已绑定的联系方式。',
    [
      field('channel', '已有验证方式', 'select', {
        choices: eligible.map((c) => [c.channel, names[c.channel] + ' · ' + c.masked]),
      }),
    ],
    '发送到原联系方式',
    async (v) => {
      const r = await api('code', { purpose: 'verifyContact', channel: v.channel });
      enter(r.challenge);
    },
  );
}
