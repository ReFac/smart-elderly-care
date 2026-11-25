const { workspaceOrigin, language } = require('../../config');
const { entryUrl } = require('../../entry');
const { nativeText } = require('../../native-text');
const words = nativeText(language);
Page({
  data: { url: '', failed: false, words },
  onLoad(options) {
    this.setData({url: entryUrl(workspaceOrigin, options && options.entry), failed: false});
  },
  onFailure() {
    this.setData({failed: true});
  },
  reconnect() {
    this.setData({failed: false});
  },
  onShareAppMessage() {
    return {title: words.share, path: '/pages/home/index?entry=visit'};
  },
});
