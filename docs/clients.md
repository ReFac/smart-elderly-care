# PC、手机与微信小程序

三端打开同一个机构 Web 工作台，共用后端会话、岗位授权、人工确认和审计。服务端为每次请求重新检查当前账号的权限。手机 App 和小程序的会话分别保存在各自的 WebView，各终端独立登录后可以同时办事。数据库与设备密钥放在机构服务端。手机和小程序工程只需要机构网站地址。

## 连接机构服务

本机演示的固定入口是 [工作台登录页](http://localhost:8765/?workspace=1)。旧预览标签显示“连接被拒绝”时，可先在服务所在电脑打开[健康检查](http://localhost:8765/api/health)。如果这里返回 `status: ok`，再检查标签页使用的端口。通过 SSH 开发的预览还依赖浏览器所在电脑的本地端口转发；重连后用当前转发的地址打开工作台。

同一台 PC 调试可先执行 `python3 server.py`。服务监听 `127.0.0.1:8765`。手机、微信和其他 PC 需要可达的正式 HTTPS 地址及有效证书。机构反向代理应把该域名的请求转给本地 Python 服务，并转发实际的 `Host`。服务启动时设置同一外部源，例如：

```bash
python3 server.py --public-origin https://care.your-institution.example
```

请将示例域名替换为机构实际地址。通过设备浏览器打开机构地址，先验证机构登录、长辈档案和确认队列能正常使用，再分别配置三端。外部源模式下，服务使用 Secure、HttpOnly 会话 Cookie。客户端不会直接调用 DeepSeek、OCR 或设备网关。

## PC 桌面

Electron 主进程使用 `clients/desktop/main.cjs`，桌面可以连接本机调试服务或机构 HTTPS 服务。默认访问本机的 8765 端口。项目通过锁文件固定运行时。以下命令使用 Node.js 22.12 或更高的受支持版本。

```bash
cd clients/desktop
npm ci
npm start
```

若使用机构后端，在启动时设置 `NH_APP_URL` 为机构完整 HTTPS 地址。主窗口和用于打印床头卡、查看授权图片的子窗口共用登录会话。渲染页面启用 Electron 沙箱、上下文隔离和同源导航约束。

助理的联网回答会列出网页来源。点击来源标题后，桌面端会核对链接和域名解析地址，再用系统默认浏览器打开公开网页。床头卡打印和医疗原件继续在机构桌面窗口内打开。在 `clients/desktop` 运行 `npm test` 可检查来源点击和地址约束。[Electron 安全指南](https://www.electronjs.org/docs/latest/tutorial/security)

创建当前操作系统及 CPU 架构的独立桌面目录：

```bash
npm run package
# 或指定新的输出位置
npm run package -- /path/to/new/yihe-desktop
```

命令会把锁定版本的运行时和应用入口组装到新目录。默认位置为 `clients/desktop/dist/yihe-版本-系统-架构/`。如已生成同名目录，指定一个新的输出位置即可保留旧包。Linux 启动其中的 `electron`，Windows 启动 `electron.exe`，macOS 打开 `Electron.app`。运行包时仍可传入 `NH_APP_URL`。在目标系统上组装该系统的包，正式分发前由机构完成签名和安装测试。Linux 主机须能运行 Chromium 沙箱，部分发行版需要管理员配置对应的沙箱辅助程序。[Electron 官方打包说明](https://www.electronjs.org/docs/latest/tutorial/application-distribution)

## Android 与 iOS

`clients/mobile/` 是独立 Expo/React Native App。首次连接前用环境变量注入机构 HTTPS 地址，或把相同的变量放进该目录本地的 `.env`。公开构建变量只适合保存机构地址。

```bash
cd clients/mobile
npm ci
export EXPO_PUBLIC_WORKSPACE_URL=https://care.your-institution.example
npm start
```

调试机可以使用与工程 SDK 版本兼容的 Expo Go，或在具备平台原生工具链的机器上运行下列命令。修改地址后重新载入开发构建，已分发 App 需使用新的构建配置。

```bash
npm run android
# 在安装 Xcode 的 macOS 主机
npm run ios
# 同时核对 iOS 与 Android 的发布模式 JavaScript / Hermes 资源
npm run bundle
```

导出后两个平台的资源写入 `dist/_expo/`，`dist/metadata.json` 记录各自的入口。安装到设备需要对应原生构建，Android 使用 Android SDK 与 JDK，iOS 使用 Xcode 及相应签名。框架已声明医疗照片拍摄和选片所需的应用配置。拍照、选片、后台返回与登录失效提示仍需在目标机型验收。[Expo 本地原生构建](https://docs.expo.dev/guides/local-app-development/) [Expo CLI 导出](https://docs.expo.dev/more/expo-cli/)

## 微信小程序

1. 用微信开发者工具将 `clients/wechat/` 作为小程序工程导入。使用机构实际 AppID 替换 `project.config.json` 中的开发占位值 `touristappid`。
2. 在具备 `web-view` 资格的机构小程序后台，为机构 H5 地址设置业务域名，按后台指引将校验文件放到该 HTTPS 域名根目录并完成校验。[腾讯业务域名配置说明](https://cloud.tencent.com/document/practice/1301/100434)
3. 在 `config.js` 中给 `workspaceOrigin` 填写已经校验的 HTTPS 根地址。用开发者工具「编译」和「真机调试」，在手机微信验证登录、图片归档、工单确认及断网重试。
4. 与另一个已登录的 PC 或手机 App 同时打开确认队列。由有权限的一端确认，再回到另一端刷新，核对申请已移出待办及对应日志只产生一次。

小程序通过同域 H5 的登录页面建立机构员工或亲属会话。小程序首次启动时读取配置，未填写域名会显示配置提示，加载失败可点「重新连接」。

## 本次验证范围

| 终端 | 已验证 | 机构现场待验收 |
| --- | --- | --- |
| PC | 已组装 Linux x64 桌面包。在启用主机 Chromium 沙箱的测试包中实际启动 Electron，通过桌面登录表单进入工作台，以护士模板创建员工、保存机构品牌，核对同源子窗口、会话及渲染进程的 Node.js 隔离。登录、账号授权和设置页已在 1440 × 900 实际截图验收。 | Windows/macOS 桌面签名与安装、生产域名和证书、打印机及相机外设 |
| 手机 App | Expo 使用已锁定依赖，成功导出 Android、iOS 两套 Hermes 资源及元数据。 | 原生安装包、手机真机拍摄、选片、登录和系统级退后台恢复 |
| 微信 | 已核对原生项目清单、首页资源和事件绑定，在本地执行配置读取、无效地址处理、HTTPS 页面加载参数和失败重试逻辑。 | 机构 AppID 与已核验的业务域名，微信开发者工具及真机编译、体验版验收 |
