import {internationalDeployment, nameEditor} from './lib/international-profile.js';
import { publicPage } from './public-site.js';

publicPage('访客注册');
const form = document.querySelector('#visitor-register');
let visitorName;
if (internationalDeployment()) {
  visitorName = nameEditor(document.createElement('input'), {}, {optional:true});
  form.prepend(visitorName.element);
}
const submit = form.querySelector('[type=submit]');
const error = document.querySelector('#register-error');
submit.disabled = false;
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submit.disabled) return;
  const { username, password } = form.elements;
  const login = username.value.trim();
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$/.test(login)) {
    error.textContent = '请按提示填写登录名。';
    username.focus();
    return;
  }
  const length = Array.from(password.value).length;
  if (length < 10 || length > 128) {
    error.textContent = '密码长度须为 10–128 个字符。';
    password.focus();
    return;
  }
  submit.disabled = true;
  error.textContent = '';
  try {
    const response = await fetch('/api/public/visitor/register', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({username:login, password:password.value,
        ...(visitorName && Object.keys(visitorName.read()).length && {nameParts:visitorName.read()})}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '无法完成注册，请重试。');
    if (!result.user) throw new Error('未收到账号确认，请先尝试登录。');
    form.reset();
    location.replace('/?workspace=1');
  } catch (cause) {
    error.textContent = cause.message || '连接失败，请稍后重试。';
    submit.disabled = false;
  }
});
