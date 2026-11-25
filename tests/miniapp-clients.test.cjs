process.env.NH_DEPLOYMENT_LANGUAGE = 'zh-CN';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {build} = require('../clients/build-miniapp.cjs');
const {entryUrl, institutionOrigin} = require('../clients/wechat/entry');

test('only configured HTTPS origins and known destinations can open', () => {
  for (const value of ['', 'http://care.example', 'https://x.test/?workspace=1', 'https://user@care.example',
    'https://care.example#token', 'https://care.example:66000', 'https://care..example', 'https://evil.test\\@care.example'])
    assert.equal(institutionOrigin(value), '', value);
  assert.equal(institutionOrigin('https://HOME.Example:8443/'), 'https://home.example:8443');
  for (const entry of [undefined, '__proto__', 'toString', 'https://evil.test/'])
    assert.equal(entryUrl('https://care.example', entry), 'https://care.example/?workspace=1');
});

for (const platform of ['wechat', 'douyin']) test(platform + ' builds a complete, isolated IDE project', t => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'care-mini-'));
  t.after(() => fs.rmSync(parent, {recursive:true, force:true}));
  const destination = path.join(parent, platform);
  const id = platform === 'wechat' ? 'wx00abc123456789de' : 'tt00abc123456789de';
  const dir = build(platform, 'https://care.example', id, destination);
  assert.equal(require(path.join(dir,'project.config.json')).appid, id);
  assert.equal(require(path.join(dir,'config.js')).edition, 'china');
  assert.throws(() => build(platform, 'https://care.example', id, destination), /已存在/);
  assert.throws(() => build(platform, 'http://care.example', id, destination + '2'), /HTTPS/);
  const pages = require(path.join(dir, 'app.json')).pages;
  assert.equal(pages.includes('pages/tour-contact/index'), platform === 'wechat');
  const ext = platform === 'wechat' ? ['.wxml', '.wxss'] : ['.ttml', '.ttss'];
  for (const route of pages)
    for (const suffix of ['.js','.json',...ext]) assert.ok(fs.statSync(path.join(dir, route + suffix)).size);
  let def;
  global.Page = page => { def = page; };
  t.after(() => {delete global.Page;});
  require(path.join(dir, 'pages/home/index.js'));
  const page = {...def, data:{...def.data}, setData(fields) {Object.assign(this.data,fields);}};
  for (const [entry, suffix] of [['workspace','/?workspace=1'], ['tour','/roomtour'], ['faq','/faq'], ['visit','/visit']]) {
    page.onLoad({entry});
    assert.equal(page.data.url, 'https://care.example' + suffix);
  }
  page.onLoad({entry:'https://evil.test', url:'https://evil.test'});
  page.onFailure();
  assert.ok(page.data.failed);
  assert.equal(page.data.words.retry, '重新连接');
  assert.equal(page.data.words.offline, '机构工作台暂时无法访问');
  page.reconnect();
  assert.equal(page.data.failed, false);
  assert.equal(page.data.url, 'https://care.example/?workspace=1');
  assert.equal(page.onShareAppMessage({webViewUrl:'https://care.example/#dossier?work=private'}).path, '/pages/home/index?entry=visit');
  const template = fs.readFileSync(path.join(dir, 'pages/home/index' + ext[0]), 'utf8');
  assert.ok(template.includes(platform === 'wechat' ? 'wx:if=' : 'tt:if='));
  assert.match(template, /binderror="onFailure"/);
  assert.match(template, /bindtap="reconnect"/);
});
