# 浏览器与小程序交付

[English](en/client-compatibility.md)

机构只需部署一套 HTTPS 网站。员工和家属通过 `/?workspace=1` 登录，访客从 `/visit` 进入，`/roomtour` 和 `/faq` 可以直接访问。小程序与 App 打开同一套业务界面。每个宿主独立登录，服务器按正在使用的账号和机构检查权限。

## 客户端验证矩阵

后续客户端检查及真机验收只使用中文测试机构和中文构建，覆盖简体中文界面及公共宿主能力。[仓库测试约定](../AGENTS.md)

2026-11-26 使用临时数据库和合成账号进行以下检查。浏览器自动化使用本机回环地址，生产域名和证书需在交付环境检验。

| 客户端 | 实际验证 | 交付时再验 |
| --- | --- | --- |
| 桌面 Chrome | Linux 上的官方 Chrome for Testing 158.0.8127.88。桌面窗口测试 Owner、接待和财务的导航、权限及页签 | 机构受管设备、打印机和硬件读卡器 |
| 手机 Chrome | 同一 Chrome 内核以 390 × 844 和触控模拟运行。护士、家属、注册访客逐一测试菜单、页面和无权访问的档案 | Android 真机软键盘、拍照选片、录音和系统返回 |
| Safari | WebKitGTK 2.52.6 在 1440 和 390 像素窗口实际登录，打开建档窗口，转到床位页，并通过带会话的接口读取 | macOS Safari、iPhone/iPad Safari 的真机操作，尤其是麦克风、相机、下载和退后台恢复 |
| 微信小程序 | 生成微信原生工程，执行入口与配置检查、错误重连测试及公开分享路径测试。另有原生 Roomtour 自愿留号页面 | 配置机构 AppID、正式业务域名与 request 合法域名。在微信开发者工具编译，使用体验版真机验证 |
| 抖音小程序 | 生成带 TTML、TTSS、页面脚本和配置的抖音原生工程，执行入口与重连测试 | 配置机构 AppID 和业务域名，用抖音开发者工具编译、预览，再在手机抖音体验版验收 |
| Android / iOS App | Expo 导出两端 Hermes 发布资源。配置为 HTTPS 根域名时默认进入登录页，Android 支持 WebView 内返回 | 签名安装、软键盘、系统返回、相册及麦克风授权 |
| Electron | 使用与 H5 相同的工作台入口。桌面包的验证范围及启动命令见客户端说明 | 目标操作系统的签名、安装与外设 |

[Chrome 官方测试版本](https://developer.chrome.com/docs/automation-and-testing/chrome-for-testing) · [桌面和手机 App 运行说明](clients.md)

## 生成微信或抖音工程

需要 Node.js 18 或更新版本。在仓库根目录执行对应命令。将环境变量换成机构已校验的域名与实际 AppID，输出目录应为新目录。输出包含平台清单、原生页面、样式和必要的客户端配置，可直接导入对应开发者工具。构建只需要公开的 AppID 和域名。

```bash
node clients/build-miniapp.cjs wechat "$INSTITUTION_HTTPS_ORIGIN" "$WECHAT_APP_ID" .local/release-wechat
node clients/build-miniapp.cjs douyin "$INSTITUTION_HTTPS_ORIGIN" "$DOUYIN_APP_ID" .local/release-douyin
```

1. 在对应平台的机构账号中配置 HTTPS 业务域名。将平台下载的校验文件以原文件名放在该域名根目录，可由反向代理直接提供。核对手机访问时的公共 DNS、证书链和 H5 登录后的实际域名。微信的原生回电请求另需配置 request 合法域名。[腾讯业务域名文档](https://cloud.tencent.com/document/practice/1301/100434) · [抖音业务域名配置](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/tutorial/basic-ability/web-view-component/)
2. 在开发者工具导入新输出目录。在「编译模式」设置首页为 `pages/home/index`。默认进入工作台。可用启动参数 `entry=visit`、`entry=tour`、`entry=faq` 分别打开访客首页、环境导览和常见问题。分享回调只提供公开参观入口，平台是否展示分享能力取决于宿主。[抖音原生项目配置](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/framework/general-configuration)
3. 用体验版分别测试访客浏览、员工登录、家属绑定范围、断网后重试及退出登录。微信取号需开通相应能力并由用户确认。抖音内付款需经抖音原生支付页，本项目当前使用机构的账单界面和既有收款渠道，未接入抖音原生支付。[微信回电配置](clients.md#roomtour-访客回电) · [抖音 web-view 支付说明](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/component/open-capacity/web-view)

## 语音、文件与现场复测

健康助理在浏览器提供麦克风权限、AudioContext 和 AudioWorklet 时录制语音。缺少能力或拒绝授权可改用文本。App 已声明相机、相册及所需麦克风用途。用机构真实设备复核选片、PDF、Excel 下载、系统返回、朗读音频及断线后的重试。每次提交仍由员工核对，款项以支付渠道回执为准。

```bash
export NH_DEPLOYMENT_LANGUAGE=zh-CN
node --test tests/miniapp-clients.test.cjs
BROWSER_BIN=/path/to/chrome python3 tests/browser/workspace_roles.py
BROWSER_BIN=/path/to/chrome python3 tests/browser/public_visitors.py
python3 tests/browser/webkit_workspace.py
```

WebKit 回归需要可连接的 GTK 显示服务、PyGObject 与 WebKit2GTK 4.1。可通过 `WEBKIT_PYTHON` 指定装有系统绑定的 Python。测试窗口使用临时会话，无需实际机构资料。

### 小程序离线提示语言

构建小程序时可在输出目录后追加部署语种，例如 `node clients/build-miniapp.cjs wechat https://care.example wx123456789abcdef0 /tmp/wechat-fr fr`。也可设置 `NH_DEPLOYMENT_LANGUAGE`。缺省为简体中文。公共入口和分享参数不改变机构语种。原生首页、分享标题、未配置域名、连接失败和重试在发包前写入，断网时可显示简中、英语、法语或西班牙语。其他已登记国际语种回退为英文。只有中国版微信包内含适用于大陆手机号的原生回电页。国际版的访客使用 H5 预约。

Expo 设置 `EXPO_PUBLIC_DEPLOYMENT_LANGUAGE` 选择应用断网和重试提示的语言。连到机构后，小程序与 App 均使用机构服务的语言及业务版本。 Electron 原生窗口及权限询问读取启动环境的 `NH_DEPLOYMENT_LANGUAGE`，支持同样四种语言。
