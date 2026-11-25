import { detail } from '../lib/dialogs.js';
import { node } from './shared.js';
import { api, field, wizard } from './identity.js';

const endpoint = 'passkeys';
const supported = () => window.isSecureContext && window.PublicKeyCredential && navigator.credentials;

function decode(value) {
  return Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0));
}

function encode(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function marshal(options, enroll) {
  const parser = enroll ? 'parseCreationOptionsFromJSON' : 'parseRequestOptionsFromJSON';
  if (typeof window.PublicKeyCredential[parser] === 'function') return window.PublicKeyCredential[parser](options);
  const converted = { ...options, challenge: decode(options.challenge) };
  if (enroll) converted.user = { ...options.user, id: decode(options.user.id) };
  for (const key of ['excludeCredentials', 'allowCredentials'])
    if (options[key]) converted[key] = options[key].map((item) => ({ ...item, id: decode(item.id) }));
  return converted;
}

function serialize(credential) {
  if (!credential) throw Error('通行密钥操作未完成');
  if (credential.toJSON) return credential.toJSON();
  const response = credential.response;
  const fields = ['clientDataJSON', 'attestationObject', 'authenticatorData', 'signature', 'userHandle'];
  return {
    id: credential.id, type: credential.type, rawId: encode(credential.rawId),
    response: Object.fromEntries(fields.filter((key) => response[key]).map((key) => [key, encode(response[key])])),
  };
}

async function ceremony(mode, data = {}) {
  const enroll = mode === 'enroll';
  const { ticket, options } = await api(endpoint + '/' + mode + '-options', enroll ? { currentPassword: data.currentPassword } : {});
  let credential;
  try {
    credential = await navigator.credentials[enroll ? 'create' : 'get']({ publicKey: marshal(options, enroll) });
  } catch (error) {
    if (error.name === 'NotAllowedError') throw Error('通行密钥请求已取消或超时');
    throw error;
  }
  return api(endpoint + '/' + mode, { ticket, credential: serialize(credential), ...(enroll ? { label: data.label } : {}) });
}

export function passkeyButton(label, action) {
  const button = node('button', 'btn btn-ghost', label);
  button.type = 'button';
  button.hidden = true;
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const content = node('div', 'access-passkey', [button, error]);
  if (!supported()) return content;
  api(endpoint).then(({ enabled }) => { button.hidden = !enabled; }).catch(() => {});
  button.addEventListener('click', async () => {
    button.disabled = true;
    error.textContent = '';
    try {
      await action();
    } catch (cause) {
      error.textContent = cause.message;
    } finally {
      button.disabled = false;
    }
  });
  return content;
}

export async function passkeySignIn(complete) {
  await ceremony('signin');
  await complete();
}

export async function passkeySettings() {
  const info = await api(endpoint);
  if (!info.enabled) throw Error('当前地址不支持通行密钥');
  const body = node('div', 'access-form');
  const dialog = detail('通行密钥（Passkey）', body);
  const password = () => field('currentPassword', '当前账号密码', 'password');
  const action = (label, press) => {
    const button = node('button', 'btn btn-ghost', label);
    button.addEventListener('click', press);
    return button;
  };
  const done = (view, text) => {
    view.message(text);
    view.dialog.addEventListener('close', () => { passkeySettings().catch(() => {}); }, { once: true });
  };
  body.append(node('p', 'fx-muted', '可使用设备解锁或安全密钥登录。'));
  if (!info.phoneVerified) body.append(node('p', 'fx-muted', '请先验证本人手机号。'));
  for (const key of info.keys) {
    body.append(node('div', 'access-field-pair', [node('strong', '', key.label), action('移除', () => {
      dialog.close();
      const view = wizard('移除通行密钥');
      view.step('移除 ' + key.label + ' 后无法再用这把通行密钥登录。', [password()], '确认移除', async (values) => {
        await api(endpoint + '/revoke', { ...values, id: key.id });
        done(view, '通行密钥已移除。');
      });
    })]));
  }
  if (info.phoneVerified) body.append(action('添加通行密钥', () => {
    dialog.close();
    const view = wizard('添加通行密钥');
    view.step('验证当前账号密码后，按设备提示完成注册。', [field('label', '设备名称', 'text'), password()], '确认添加', async (values) => {
      await ceremony('enroll', values);
      done(view, '通行密钥已添加。');
    });
  }));
}
