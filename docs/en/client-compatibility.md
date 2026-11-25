# Browser and mini-program delivery

[Documentation](README.md) · [中文](../client-compatibility.md)

Serve the institution from one HTTPS site. Staff and families sign in at `/?workspace=1`. Visitors can go directly to `/visit`, `/roomtour` or `/faq`. The mobile app and mini-programs open the same web workflows. Each host maintains its own session, and the server checks the account and its access within the institution on each host.

## Verification matrix

Use Simplified Chinese test institutions and Chinese builds for future browser, mini-app and device acceptance. Include capabilities shared across hosts. [Repository testing scope](../../AGENTS.md)

The checks on 26 November 2026 used fictional accounts and temporary databases. The browsers connected over loopback. Check production DNS and the certificate chain on the devices the institution will use.

| Client | Verified here | On-site acceptance |
| --- | --- | --- |
| Desktop Chrome | Official Chrome for Testing 158.0.8127.88 on Linux. Exercised desktop navigation, permissions and tabs for the owner, reception and finance accounts | Managed devices, printers and card readers |
| Mobile Chrome | Same Chrome engine at 390 × 844 with touch emulation. Exercised nurse, family and registered visitor routes and restricted records | Android hardware, keyboard, photos, microphone and system navigation |
| Safari | Real WebKitGTK 2.52.6 at 1440 and 390 pixels. Signed in, opened the resident registration form, navigated to beds and read the authenticated revision | Safari on macOS, iPhone and iPad, including microphone access, camera, downloads and returning from the background |
| WeChat mini-program | Generated the native source project. Tested configured entry routes, invalid configurations, retries and the public share target. Includes a native opt-in tour callback page | Institution AppID, verified business and request domains, official IDE build and a device trial |
| Douyin mini-program | Generated native TTML, TTSS, JavaScript and platform manifests. Tested entry routes and retries | Institution AppID, verified domain, official IDE build and a device trial |
| Android and iOS app | Expo exported both Hermes release bundles. An HTTPS origin opens the workspace sign-in page. The Android wrapper handles WebView history | Signed installation, keyboard, system back and media permissions |
| Electron | Uses the shared H5 workspace. See the client guide for desktop packaging and prior checks | OS-specific signing, installation and peripherals |

[Chrome for Testing](https://developer.chrome.com/docs/automation-and-testing/chrome-for-testing) · [Desktop and mobile client guide](../clients.md)

## Prepare a native project

From the repository root, run the command for the target platform with Node.js 18 or newer. Supply the institution’s verified origin, its real public AppID and a new output directory. The command writes the native pages, scripts, styles and manifests for the official IDE. It needs only the public AppID and origin.

```bash
node clients/build-miniapp.cjs wechat "$INSTITUTION_HTTPS_ORIGIN" "$WECHAT_APP_ID" .local/release-wechat
node clients/build-miniapp.cjs douyin "$INSTITUTION_HTTPS_ORIGIN" "$DOUYIN_APP_ID" .local/release-douyin
```

1. Register the institution’s HTTPS business domain in the platform console. Serve the verification file that the platform issues at the domain root, using the filename it supplied. A reverse proxy can serve it. On a phone, check DNS, the certificate chain and the origin you reach at sign-in. For WeChat’s native callback, register the request domain as well. [Tencent domain setup](https://cloud.tencent.com/document/practice/1301/100434) · [Douyin domain verification](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/tutorial/basic-ability/web-view-component/)
2. Import the output directory into the official IDE. The launch page, `pages/home/index`, opens the workspace by default. Use `entry=visit`, `entry=tour` or `entry=faq` to open the visitor site, tour or FAQ. On hosts that expose a share callback, sharing links to the public visitor page. [Douyin project configuration](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/framework/general-configuration)
3. On a device, try browsing anonymously, signing in as staff, opening a family account’s permitted records and signing out. Interrupt the network connection and reconnect. WeChat phone callbacks require visitor consent and the platform entitlement. The billing interface and existing collection channels are available. In-app Douyin payments require a native Douyin payment page, and that integration is still pending. [WeChat callback setup](../clients.md#roomtour-访客回电) · [Douyin web-view payments](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/component/open-capacity/web-view)

## Voice, files and repeatable checks

To record speech, the host must provide microphone access, AudioContext and AudioWorklet. People can type if recording is unavailable or they decline permission. The mobile wrapper declares the applicable microphone and photo permissions. On each device, try selecting an image, downloading PDF and Excel files, playing audio, using system navigation and reconnecting. Staff review submissions. Use the payment provider’s receipt to confirm a payment.

```bash
export NH_DEPLOYMENT_LANGUAGE=zh-CN
node --test tests/miniapp-clients.test.cjs
BROWSER_BIN=/path/to/chrome python3 tests/browser/workspace_roles.py
BROWSER_BIN=/path/to/chrome python3 tests/browser/public_visitors.py
python3 tests/browser/webkit_workspace.py
```

For the WebKit check, provide a GTK display, PyGObject and WebKit2GTK 4.1. Set `WEBKIT_PYTHON` to the Python installation with those bindings. The check opens an offscreen window for a temporary session.

### Offline mini-app language

To set the institution’s locale, pass it after the output directory, for example `node clients/build-miniapp.cjs wechat https://care.example wx123456789abcdef0 /tmp/wechat-fr fr`, or set `NH_DEPLOYMENT_LANGUAGE`. The default is Simplified Chinese. The Chinese, English, French and Spanish bundles include the native home and sharing titles, missing-domain message, connection errors and retry label. Other registered international locales fall back to English. Only Chinese WeChat builds include the native mainland phone callback page. International visitors use the H5 visit page. Acceptance for the Chinese release requires the vendors’ devices and the institution’s deployment settings.

Set `EXPO_PUBLIC_DEPLOYMENT_LANGUAGE` for the Expo app’s native connection and retry messages. After connection, the H5 workspace uses the locale and business edition configured on the server. Electron reads `NH_DEPLOYMENT_LANGUAGE` at launch for native dialogs and microphone prompts in the same four languages.
