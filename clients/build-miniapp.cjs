// Prepare a standalone source project for the selected platform's official developer tools.
const fs = require('node:fs');
const path = require('node:path');
const {institutionOrigin} = require('./wechat/entry');
const {nativeText} = require('./wechat/native-text');
const locales = require('../web/assets/deployment-locales.json');

function build(platform, address, appId, destination, language = process.env.NH_DEPLOYMENT_LANGUAGE || 'zh-CN') {
  const [locale] = Intl.getCanonicalLocales(language);
  if (!Object.hasOwn(locales, locale)) throw Error('Unknown deployment language: ' + locale);
  const edition = locales[locale].edition || 'international';
  const text = nativeText(locale);
  if (!['wechat','douyin'].includes(platform)) throw Error('平台请选择 wechat 或 douyin');
  const origin = institutionOrigin(address);
  if (!origin) throw Error('请填写已校验的机构 HTTPS 业务域名根地址');
  if (typeof appId !== 'string' || !new RegExp('^' + (platform === 'wechat' ? 'wx' : 'tt') + '[a-zA-Z0-9]+$').test(appId))
    throw Error('请填写对应平台的机构 AppID');
  const out = path.resolve(destination);
  // Only create new projects. An existing IDE checkout may contain local configuration or signing material.
  if (fs.existsSync(out)) throw Error('输出目录已存在，请指定新目录');
  const platformDir = path.join(__dirname, platform);
  const sharedDir = path.join(__dirname, 'wechat');
  const app = JSON.parse(fs.readFileSync(path.join(platformDir, 'app.json'), 'utf8'));
  const project = JSON.parse(fs.readFileSync(path.join(platformDir, 'project.config.json'), 'utf8'));
  project.appid = appId;
  app.window.navigationBarTitleText = text.app;
  if (edition === 'international') app.pages = app.pages.filter(page => page !== 'pages/tour-contact/index');
  const files = new Map();
  files.set('app.json', JSON.stringify(app, null, 2) + '\n');
  files.set('project.config.json', JSON.stringify(project, null, 2) + '\n');
  files.set('config.js', 'module.exports = ' + JSON.stringify({workspaceOrigin:origin, language:locale, edition}) + ';\n');
  const copy = (name, dest=name) => files.set(dest, fs.readFileSync(path.join(sharedDir, name)));
  copy('app.js');
  copy('entry.js');
  copy('native-text.js');
  if (app.sitemapLocation) copy(app.sitemapLocation);
  for (const page of app.pages) {
    if (page === 'pages/home/index') files.set(page + '.json', JSON.stringify({navigationBarTitleText:text.home}) + '\n');
    else copy(page + '.json');
    copy(page + '.js');
    const markup = fs.readFileSync(path.join(sharedDir, page + '.wxml'), 'utf8');
    if (platform === 'douyin') {
      files.set(page + '.ttml', markup.replaceAll('wx:if=', 'tt:if=').replaceAll('wx:else', 'tt:else'));
      copy(page + '.wxss', page + '.ttss');
    } else {
      files.set(page + '.wxml', markup);
      copy(page + '.wxss');
    }
  }
  fs.mkdirSync(path.dirname(out), {recursive: true});
  const stage = fs.mkdtempSync(path.join(path.dirname(out), '.miniapp-'));
  try {
    for (const [relative, contents] of files) {
      const target = path.join(stage, relative);
      fs.mkdirSync(path.dirname(target), {recursive:true});
      fs.writeFileSync(target, contents);
    }
    fs.renameSync(stage, out);
  } finally {
    fs.rmSync(stage, {recursive:true, force:true});
  }
  return out;
}

if (require.main === module) {
  try {
    const [platform, origin, appId, output, language] = process.argv.slice(2);
    if (!output) throw Error('用法 node clients/build-miniapp.cjs wechat|douyin HTTPS域名 AppID 新输出目录 [语言]');
    console.log(build(platform, origin, appId, output, language));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = {build};
