const { app, BrowserWindow, dialog, session, shell } = require('electron');
const path = require('node:path');
const { registerLeadCalls } = require('./lead-calls.cjs');
const { registerSourceLinks } = require('./public-source.cjs');

function workspaceUrl() {
  const target = new URL(process.env.NH_APP_URL || 'http://127.0.0.1:8765');
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(target.hostname);
  if (
    (target.protocol !== 'https:' && !(target.protocol === 'http:' && loopback)) ||
    target.username ||
    target.password
  ) {
    throw new Error('机构服务需要 HTTPS 地址，或本机开发地址');
  }
  return target;
}

const webPreferences = {
  contextIsolation: true,
  sandbox: true,
  nodeIntegration: false,
  webviewTag: false,
};

async function showWorkspace(target) {
  const win = new BrowserWindow({
    title: '安康医养平台',
    width: 1320,
    height: 900,
    minWidth: 700,
    minHeight: 530,
    backgroundColor: '#f3f6fc',
    autoHideMenuBar: true,
    webPreferences: { ...webPreferences, preload: path.join(__dirname, 'source-preload.cjs') },
  });
  registerLeadCalls(win.webContents, target.origin, url => shell.openExternal(url));
  registerSourceLinks(win.webContents, target.origin, url => shell.openExternal(url));
  try {
    await win.loadURL(target.href);
  } catch {
    dialog.showErrorBox('未连接机构工作台', '请先启动机构服务，并核对 NH_APP_URL 配置。');
    win.close();
  }
}

app
  .whenReady()
  .then(async () => {
    const target = workspaceUrl();
    const sameOrigin = (value) => {
      try {
        return new URL(value).origin === target.origin;
      } catch {
        return false;
      }
    };
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) =>
      callback(false)
    );
    app.on('web-contents-created', (_event, contents) => {
      const guard = (event, url) => {
        if (url !== 'about:blank' && !sameOrigin(url)) event.preventDefault();
      };
      contents.on('will-navigate', guard);
      contents.on('will-redirect', guard);
      contents.setWindowOpenHandler(({ url }) => {
        // Bed-card printouts inherit a blank page. Protected medical originals use the same session.
        if (url !== 'about:blank' && !sameOrigin(url)) return { action: 'deny' };
        return {
          action: 'allow',
          overrideBrowserWindowOptions: { autoHideMenuBar: true, webPreferences },
        };
      });
    });
    app.on('activate', () => {
      if (!BrowserWindow.getAllWindows().length) showWorkspace(target);
    });
    await showWorkspace(target);
  })
  .catch((error) => {
    dialog.showErrorBox('无法启动', error.message);
    app.quit();
  });
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
