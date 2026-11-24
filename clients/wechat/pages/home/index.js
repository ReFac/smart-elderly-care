const { workspaceOrigin } = require('../../config');
Page({
  data: { url: '', failed: false },
  onLoad() {
    if (/^https:\/\/[a-z\d.-]+(?::\d+)?\/?$/i.test(workspaceOrigin)) {
      this.setData({ url: workspaceOrigin.replace(/\/$/, '') + '/' });
    }
  },
  onFailure() {
    this.setData({ failed: true });
  },
  reconnect() {
    this.setData({ failed: false });
  },
});
