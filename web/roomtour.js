import { stops, tourModel } from './roomtour-model.js';

const byId = new Map(stops.map(stop => [stop.id, stop]));
const canvas = document.querySelector('#tour-canvas');
const stage = document.querySelector('#tour-stage');
const hotspots = document.querySelector('#tour-hotspots');
const navigation = document.querySelector('#tour-stops');
const scenes = new Map();
let active, points = [];

function viewButton(title, className, activate) {
  const button = document.createElement('button');
  button.className = className;
  button.type = 'button';
  button.textContent = title;
  button.addEventListener('click', activate);
  return button;
}

const model = tourModel(canvas, project => {
  for (const {point, button} of points) {
    const [x,y,depth] = project(point);
    button.hidden = depth <= 0 || x < 60 || y < 70 || x > stage.clientWidth-60 || y > stage.clientHeight-58;
    if (!button.hidden) {
      button.style.left = x + 'px';
      button.style.top = y + 'px';
    }
  }
});

function visitRoom(stop) {
  active = stop;
  for (const [id, button] of scenes) button.setAttribute('aria-pressed', String(id === stop.id));
  document.querySelector('#scene-name').textContent = stop.name;
  document.querySelector('#scene-place').textContent = stop.place;
  document.querySelector('#scene-description').textContent = stop.description;
  points = model.supported ? stop.links.map(({id, point}) => ({
    point, button: viewButton(byId.get(id).name, 'tour-hotspot', () => {
      visitRoom(byId.get(id));
      scenes.get(id).focus();
    }),
  })) : [];
  for (const {button} of points) button.hidden = true;
  hotspots.replaceChildren(...points.map(({button}) => button));
  model.show(stop.id);
  const url = new URL(location.href);
  if (active.id !== stops[0].id || url.searchParams.has('scene')) {
    url.searchParams.set('scene', active.id);
    history.replaceState(history.state, '', url);
  }
}

for (const stop of stops) {
  const item = viewButton(stop.name, 'tour-stop', () => visitRoom(stop));
  const location = document.createElement('small');
  location.textContent = stop.place;
  item.append(location);
  scenes.set(stop.id, item);
  navigation.append(item);
}
visitRoom(byId.get(new URLSearchParams(location.search).get('scene')) || stops[0]);
if (!model.supported) {
  document.querySelector('#tour-empty').hidden = false;
  document.querySelector('.tour-pad').hidden = true;
}
const turns = {left:() => model.turn(-.31), right:() => model.turn(.31), in:() => model.zoom(.16),
  out:() => model.zoom(-.16), reset:() => model.reset()};
for (const control of document.querySelectorAll('[data-tour-turn]'))
  control.addEventListener('click', turns[control.dataset.tourTurn]);

const access = '/api/public/visitor';
const dialog = document.querySelector('#visitor-dialog');
const login = document.querySelector('#visitor-open');
const phone = document.querySelector('#visitor-phone-form');
const confirm = document.querySelector('#visitor-code-form');
const service = document.querySelector('#visitor-service');
const failure = document.querySelector('#visitor-error');
const demo = document.querySelector('#visitor-demo');
const demoCode = document.querySelector('#visitor-demo-code');
const wechat = document.querySelector('#visitor-wechat');
const noticeKey = 'ankang-tour-visitor-dismissed';
let status, challenge, loading = false, pendingStatus;
let checkedForPrompt = false;

async function query(path, payload) {
  const options = payload ? {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),
  } : {cache:'no-store'};
  const response = await fetch(access + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '暂时无法办理访客登录。');
  return result;
}

function updateStatus(value) {
  status = value;
  login.disabled = Boolean(value?.signedIn);
  login.textContent = value?.signedIn ? value.maskedPhone ? '访客 ' + value.maskedPhone : '已登录' : '访客登录';
  const phoneEnabled = value?.phoneEnabled || value?.demoEnabled;
  phone.hidden = Boolean(challenge) || !phoneEnabled;
  confirm.hidden = !challenge;
  demo.hidden = !value?.demoEnabled || Boolean(challenge);
  const wechatUrl = value?.wechatEnabled && value.wechatUrl ? new URL(value.wechatUrl, location.origin) : null;
  wechat.disabled = !wechatUrl || wechatUrl.origin !== location.origin;
  wechat.textContent = wechat.disabled ? '微信快捷登录暂未开通' : '微信快捷登录';
  wechat.onclick = wechat.disabled ? null : () => location.assign(wechatUrl);
  service.textContent = !value ? '暂时无法读取登录方式。您仍可浏览或提交参观意愿。'
    : value.phoneEnabled ? '请输入能接收短信的本人号码。'
    : value.demoEnabled ? '当前只开放本机演示验证。'
    : '短信登录暂未开通。可以预约参观，或主动留下电话请求回电。';
}

async function loadStatus() {
  if (pendingStatus) return pendingStatus;
  pendingStatus = query('/status')
    .then(status => updateStatus(status))
    .catch(() => updateStatus(null))
    .finally(() => { pendingStatus = null; });
  return pendingStatus;
}

function dismissed() {
  try { return sessionStorage.getItem(noticeKey) === 'yes'; }
  catch { return false; }
}
function rememberDismissal() {
  checkedForPrompt = true;
  try { sessionStorage.setItem(noticeKey, 'yes'); }
  catch { /* Browser storage can be unavailable in private sessions. */ }
}
async function openLogin() {
  if (loading || dialog.open) return;
  loading = true;
  failure.textContent = '';
  try {
    if (!status) await loadStatus();
    if (!status?.signedIn) dialog.showModal();
  } finally { loading = false; }
}
login.addEventListener('click', openLogin);
dialog.addEventListener('close', rememberDismissal);
document.querySelector('#visitor-close').addEventListener('click', () => dialog.close());
document.querySelector('#visitor-continue').addEventListener('click', () => dialog.close());
document.querySelector('#visitor-demo-fill').addEventListener('click', () => {
  phone.elements.phone.value = '13900000000';
  phone.elements.phone.focus();
});
document.querySelector('#visitor-restart').addEventListener('click', () => {
  failure.textContent = '';
  challenge = null;
  confirm.reset();
  updateStatus(status);
  phone.elements.phone.focus();
});

async function submit(form, callback) {
  const send = form.querySelector('[type=submit]');
  if (send.disabled) return;
  send.disabled = true;
  failure.textContent = '';
  try { await callback(); }
  catch (error) { failure.textContent = error.message || '暂时无法登录，请稍后再试。'; }
  finally { send.disabled = false; }
}
phone.addEventListener('submit', event => {
  event.preventDefault();
  submit(phone, async () => {
    const result = await query('/code', {phone:phone.elements.phone.value.trim()});
    if (!result.challengeId) throw new Error('未取得验证码请求编号，请稍后重试。');
    challenge = result.challengeId;
    demoCode.hidden = !result.demoCode;
    demoCode.textContent = result.demoCode ? '本机演示验证码 ' + result.demoCode : '';
    updateStatus(status);
    confirm.elements.code.focus();
  });
});
confirm.addEventListener('submit', event => {
  event.preventDefault();
  submit(confirm, async () => {
    const result = await query('/verify', {challengeId:challenge, code:confirm.elements.code.value});
    if (!result.signedIn) throw new Error('尚未完成访客验证，请重新输入验证码。');
    updateStatus(result);
    challenge = null;
    phone.reset();
    confirm.reset();
    demoCode.hidden = true;
    demoCode.textContent = '';
    dialog.close();
  });
});

const minimum = 10_000;
let visibleTime = 0, startedAt, timer;
function updateClock() {
  clearTimeout(timer);
  if (startedAt != null) visibleTime += performance.now()-startedAt;
  startedAt = undefined;
  if (status?.signedIn || checkedForPrompt || dismissed()) return;
  if (document.visibilityState !== 'visible' || !document.hasFocus()) return;
  if (visibleTime >= minimum) {
    checkedForPrompt = true;
    openLogin();
    return;
  }
  startedAt = performance.now();
  timer = setTimeout(updateClock, minimum-visibleTime);
}
document.addEventListener('visibilitychange', updateClock);
window.addEventListener('focus', updateClock);
window.addEventListener('blur', updateClock);
loadStatus().finally(updateClock);
updateClock();

fetch('/api/public/reception', {credentials:'omit'})
  .then(response => response.ok ? response.json() : null)
  .then(data => {
    if (!data?.institutionName) return;
    document.querySelector('[data-tour-brand]').textContent = data.institutionName;
    document.title = '3D 环境导览 · ' + data.institutionName;
  })
  .catch(() => {});
