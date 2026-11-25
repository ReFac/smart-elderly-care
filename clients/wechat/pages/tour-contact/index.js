const { workspaceOrigin } = require('../../config');
const { institutionOrigin } = require('../../entry');
Page({
  data: { busy: false, done: false, manual: false, error: '', phone: '' },
  useManual() { this.setData({ manual: true }); },
  onInput(event) { this.setData({ phone: event.detail.value }); },
  onPhone(event) {
    if (!event.detail.code) {
      this.setData({ manual: true, error: '未取得微信手机号，您可以手动填写或返回参观。' });
      return;
    }
    this.submit('/api/public/visitor/wechat-contact', { code: event.detail.code, consent: true });
  },
  sendPhone() {
    if (!/^1[3-9]\d{9}$/.test(this.data.phone)) {
      this.setData({ error: '请填写 11 位中国大陆手机号。' });
      return;
    }
    this.submit('/api/public/leads', { phone: this.data.phone, source: 'consent', consent: true });
  },
  submit(path, data) {
    if (this.data.busy || this.data.done) return;
    const origin = institutionOrigin(workspaceOrigin);
    if (!origin) {
      this.setData({ error: '院方暂未开通此入口，请返回导览网页填写。', manual: true });
      return;
    }
    this.setData({ busy: true, error: '' });
    wx.request({
      url: origin + path, method: 'POST', data,
      success: result => {
        if (result.statusCode === 202 && result.data && result.data.received) this.setData({ done: true, phone: '' });
        else this.setData({ manual: true, error: (result.data && result.data.error) || '提交未成功，请手动填写。' });
      },
      fail: () => this.setData({ manual: true, error: '连接失败，请手动填写或稍后重试。' }),
      complete: () => this.setData({ busy: false }),
    });
  },
  leave() {
    if (getCurrentPages().length > 1) wx.navigateBack();
    else wx.exitMiniProgram();
  },
});
