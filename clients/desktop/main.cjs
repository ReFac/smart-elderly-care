const { app, BrowserWindow, dialog, session, shell } = require('electron');
const path = require('node:path');
const words = require('./native-text.cjs');
const { registerLeadCalls } = require('./lead-calls.cjs');
const { configureMicrophone } = require('./microphone.cjs');
const { registerPaymentLinks } = require('./payment-links.cjs');
const { registerSourceLinks } = require('./public-source.cjs');

function workspaceUrl() {
  const target = new URL(process.env.NH_APP_URL || 'http://localhost:8765');
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(target.hostname);
  if (
    (target.protocol !== 'https:' && !(target.protocol === 'http:' && loopback)) ||
    target.username ||
    target.password
  ) {
    throw new Error(words.invalid);
  }
  if (target.pathname === '/' && !target.hash) target.searchParams.set('workspace', '1');
  return target;
}

const webPreferences = {
  contextIsolation: true,
  sandbox: true,
  nodeIntegration: false,
  webviewTag: false,
};
const workspaceWindows = new WeakSet();

async function showWorkspace(target) {
  const win = new BrowserWindow({
    title: words.app,
    width: 1320,
    height: 900,
    minWidth: 700,
    minHeight: 530,
    backgroundColor: '#f3f6fc',
    autoHideMenuBar: true,
    webPreferences: { ...webPreferences, preload: path.join(__dirname, 'source-preload.cjs') },
  });
  workspaceWindows.add(win.webContents);
  registerPaymentLinks(win.webContents, target.origin, url => shell.openExternal(url));
  registerLeadCalls(win.webContents, target.origin, url => shell.openExternal(url));
  registerSourceLinks(win.webContents, target.origin, url => shell.openExternal(url));
  try {
    await win.loadURL(target.href);
  } catch {
    dialog.showErrorBox(words.offline, words.reconnect);
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
    configureMicrophone(session.defaultSession, target, workspaceWindows, async contents => {
      const { response } = await dialog.showMessageBox(BrowserWindow.fromWebContents(contents), {
        type: 'question', message: words.microphone,
        detail: words.purpose, buttons: [words.allow, words.cancel],
        defaultId: 1, cancelId: 1,
      });
      return response === 0;
    });
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
    dialog.showErrorBox(words.startup, error.message);
    app.quit();
  });
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
