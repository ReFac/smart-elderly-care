process.env.NH_DEPLOYMENT_LANGUAGE = 'zh-CN';
// Run using Electron as an app entry point. Keep external browser handoffs in a test recorder.
const { app, BrowserWindow, shell } = require('electron');
const assert = require('node:assert/strict');
const dns = require('node:dns/promises');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const root = path.resolve(__dirname,'../..');
const fixture = [
  '<!doctype html><html lang="zh-CN"><body><dialog open id="medical"><main></main></dialog><script type="module">',
  "import {hospitalMapLink} from '/features/medical-hospital-map.js';",
  "window.NH_DEPLOYMENT={language:'zh-CN',edition:'china',mapProvider:'amap'};",
  "const link=hospitalMapLink('北京市测试医院');link.id='china';",
  "document.querySelector('main').append(link);window.ready=true;</script></body></html>",
].join('\n');
const server = http.createServer((req,res) => {
  const pathname = new URL(req.url,'http://localhost').pathname;
  if (pathname === '/') {res.setHeader('Content-Type','text/html;charset=utf-8');return res.end(fixture);}
  if (['/features/medical-hospital-map.js','/features/shared.js','/features/people-labels.js','/lib/locale.js','/lib/international-profile.js'].includes(pathname)) {
    res.setHeader('Content-Type','application/javascript;charset=utf-8');
    return res.end(fs.readFileSync(path.join(root, 'web', pathname)));
  }
  res.writeHead(404).end();
});
const opened = [];
shell.openExternal = async url=>{opened.push(url);};
const lookup = dns.lookup;
dns.lookup = async (host,...args) => host === 'uri.amap.com' ? [{address:'8.8.8.8',family:4}] : lookup(host,...args);
const wait = ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.once('browser-window-created',(_event,win)=>{
  const web = win.webContents;
  web.once('did-finish-load',async()=>{
    try {
      for (let i=0;i<80 && !await web.executeJavaScript('Boolean(window.ready)');i++) await wait(50);
      await web.executeJavaScript("document.querySelector('#china').click()");
      await wait(60);
      assert.equal(opened.length,0);
      win.focus();web.focus();
      const point = await web.executeJavaScript("(()=>{const r=document.getElementById('china').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()");
      web.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,...point});
      web.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,...point});
      for (let i=0;i<40 && !opened.length;i++) await wait(30);
      assert.equal(opened.length,1);
      const map = new URL(opened[0]);
      assert.equal(map.hostname,'uri.amap.com');
      assert.equal(map.searchParams.get('keyword'),'北京市测试医院');
      assert.equal(BrowserWindow.getAllWindows().length,1);
      console.log('Electron '+process.versions.electron+' 在用户点击后向系统浏览器转交了一条高德医院地图链接。');
      server.close();app.exit(0);
    } catch(error) {console.error(error);server.close();app.exit(1);}
  });
});
server.listen(0,'127.0.0.1',()=>{
  process.env.NH_APP_URL='http://127.0.0.1:'+server.address().port;
  require(path.join(root,'clients/desktop/main.cjs'));
});
setTimeout(()=>{console.error('Electron handoff validation timed out');app.exit(2);},18000).unref();
