// Canonical dial strings from the institution's phone-number normalizer.
const DIAL = /^tel:(?:1[3-9][0-9]{9}|0[1-9][0-9]{8,10}|\+[1-9][0-9]{7,14})$/;

function registerLeadCalls(contents, origin, openExternal) {
  contents.ipc.handle('leads:call-customer', async (event, value) => {
    try {
      const frame = event.senderFrame;
      if (contents.isDestroyed() || !frame || frame !== contents.mainFrame || frame.origin !== origin) return false;
      const page = new URL(frame.url);
      if (page.origin !== origin || page.hash !== '#leads' || !['/', '/index.html'].includes(page.pathname)) return false;
      if (typeof value !== 'string' || !DIAL.test(value) || /\s/.test(value)) return false;
      await openExternal(value);
      return true;
    } catch {
      return false;
    }
  });
}

module.exports = { registerLeadCalls };
