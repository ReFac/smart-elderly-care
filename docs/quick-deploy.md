# 机构部署

[文档导航](README.md) · [English](en/quick-deploy.md) · [Owner 控制台](deployment-console.md) · [持证机构交付](medical-commercial.md) · [员工手册](workspace-manual.md)

建议每家机构部署一个实例，分别配置域名、服务账号、加密业务库、凭据库和恢复密钥。同一家机构的分院可以建在同一业务库中，再按岗位划定访问范围。电脑、手机和小程序都通过 HTTPS 反向代理访问这套服务，进程由 systemd 托管。

## 1. 安装

准备一台使用 apt 和 systemd 的 Linux 主机，院务服务需 Python 3.11 及以上版本，DeerFlow 的独立运行环境需 Python 3.12 及以上版本。把经过验收的代码放在 /opt/care-workspace。正式环境使用已评审的提交或签名制品，先在独立中文测试机构验证升级和回滚。

```sh
sudo apt-get install git python3-venv python3-dev build-essential pkg-config libsqlcipher-dev poppler-utils caddy
sudo useradd --system --user-group --home-dir /var/lib/care-workspace --shell /usr/sbin/nologin care-workspace
sudo install -d -m 700 -o care-workspace -g care-workspace /var/lib/care-workspace
sudo install -d -m 750 /etc/care-workspace
cd /opt/care-workspace
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements-storage.txt -r requirements-payments.txt -r requirements-harness.txt -r requirements-a2a.txt
sudo install -m 600 deploy/linux/service.env.example /etc/care-workspace/service.env
sudoedit /etc/care-workspace/service.env
```

将 NH_PUBLIC_ORIGIN 设为机构实际使用的 HTTPS 域名。NH_DEPLOYMENT_LANGUAGE 可选 zh-CN、en、fr 或 es，首次建库时锁定，以后每次启动都会核对。已有中文机构库仍用中文。需要另一种语言的机构可独立部署。

中国版使用高德，其他语言默认使用 Google Maps。在线查医院需要运营方先配置相应的地图服务。员工输入医院名或城市，选中结果后核实。界面从本机加载词典，病历原件、姓名和员工笔记保留原文。现有账务以人民币记账，营业日按上海时区划分。其他币种或税务规则须另行适配。

完成下方建库前，请按独立安装清单预置 DeerFlow v2.2.0。主对话、文书和定期复核都需要它；在 Owner 部署控制台可查安装状态。[安装步骤](../deploy/deerflow/README.md) · [各组件职责](agent-components.md)

## 2. 正式建库

下面的命令以英文持证机构为例。中文机构请将两处语言参数都改为 zh-CN，并与服务环境一致。普通养老机构可选 residential。请指定尚不存在的数据库路径，首次执行时按终端提示设置 Owner 密码。

```sh
sudo -u care-workspace .venv/bin/python manage_deployment.py init --db /var/lib/care-workspace/institution.sqlite3 --profile licensed-medical --language en
sudo -u care-workspace .venv/bin/python manage_deployment.py check --db /var/lib/care-workspace/institution.sqlite3 --profile licensed-medical --language en --public-origin https://care.example.org --full
sudo install -m 644 deploy/linux/care-workspace.service /etc/systemd/system/care-workspace.service
sudo systemctl daemon-reload
sudo systemctl enable --now care-workspace.service
```

使用部署包中的 Caddyfile.example 新增机构站点，保留同一域名和上游监听端口。通过 Caddy 配置验证后 reload。公开 DNS 和有效证书就绪后执行以下检查。

```sh
curl --fail https://care.example.org/api/health
curl --fail https://care.example.org/api/public/deployment
journalctl -u care-workspace.service -n 60
```

工作台入口为 /?workspace=1，访客从 /visit 进入。用 owner 和首次设置的密码登录，在「系统管理 → 项目部署」核对版本、模型、套餐、HTTP 设备连接及监听端口。托管机构使用平台提供的套餐。平台自营且授权机构管理凭据时，由运维人员显式设置 NH_DEPLOYMENT_MODE=operator，再重启服务。若端口由 systemd 环境固定，变更时须同步修改服务配置和代理上游。微信和抖音的 AppID、业务域名及上线审核见[多端交付](client-compatibility.md)。

## 3. 交付和恢复

准备一个独立的简体中文验收库（`zh-CN`）。用对应岗位的测试账号走完建档、排床、护理签认、支付对账和告警回执，并确认跨分院访问会被拒绝。用合成附件测试 OCR 和 Agent，核对用量回执。

按职责分别保管业务库及快照主密钥、平台凭据库密钥和设备凭据。业务快照不包含外置的平台凭据。让运维人员在另一台干净主机上恢复样本数据和原件，记录第一次演练的结果，并确定自动快照周期、异地目标、恢复时间和停机联系方式。签名升级会先建立并校验完整快照，再切换版本。第三方模型、短信、商户终端和设备仍须分别用正式供应商账号联调。[快照与恢复](backups.md) · [发布升级](updates.md) · [Agent 对接](agent-handbook.md)

### 语言包与业务规则

在同一版本中可以部署中文 zh-CN、英文 en、法文 fr 或西班牙文 es。法文和西班牙文当前包含登录、导航、姓名等基础译文，其余文案回落英文。每个机构仅在首次安装时选择一次。个人中心的主题和字体不影响部署语言。

新增语言时，在 [语言目录](../web/assets/deployment-locales.json) 登记语言标签和显示名，并在 web/assets/locales/<语言标签>.json 放置界面词条。缺省继承 international 规则，包括全球医院查询、Google Maps、结构化国际姓名和邮政地址；中国区使用 china 规则及高德。加载本地静态词典，不转译用户原件。将词典纳入签名发布。仓库回归只运行简体中文版和语言无关的用例。部署的语言描述可从 /api/public/deployment 取得。Google Places 配置 NH_GOOGLE_PLACES_KEY，高德地点检索配置 NH_AMAP_WEB_KEY。服务端保管密钥。

### 医院地图服务配置

员工可以对照就诊原件手工填写医院。中国版的本地名录优先列出河南医院。在「联网核对医院」输入公开院名或城市，可以查高德 POI。国际版在同一处通过 Google Places 按安装语种检索全球医院。只打开地图时，无需配置服务密钥。[高德网页搜索 URI](https://lbs.amap.com/api/uri-api/guide/search/search) · [Google Maps 搜索 URL](https://developers.google.com/maps/documentation/urls/get-started)

需要在表单内查看联网结果时，中国版由机构开通高德 Web 服务并在服务器设置 `NH_AMAP_WEB_KEY`。国际版启用 Places API (New) 及计费，然后在服务器设置 `NH_GOOGLE_PLACES_KEY`。将密钥限制为对应 API 和机构服务器地址，重启服务。中文部署验收使用虚构示例或公开院名，核对地址、高德地图跳转与供应商调用记录。断网或未设置密钥时，员工仍可按原件保存病例。[高德 POI 搜索](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch) · [Google Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search)

桌面客户端在员工点击医院链接时调用系统默认浏览器。在线结果只作临时核对。Google Maps 署名图取自官方素材包的 `GoogleMaps_Logo_DarkGray_2x.png`，保持原样并随地点搜索结果展示。该商标的使用遵循 Google Maps 的署名规则。项目的开源许可证不授予该标识的商标权。[Google Maps 署名与使用要求](https://developers.google.com/maps/documentation/places/web-service/policies) · [官方署名素材包](https://developers.google.com/static/maps/documentation/images/Google_Maps_Attribution_Assets.zip)
