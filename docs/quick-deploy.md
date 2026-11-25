# 机构部署

[English](en/quick-deploy.md) · [Owner 控制台](deployment-console.md) · [持证机构交付](medical-commercial.md) · [员工手册](workspace-manual.md)

推荐从一院一实例开始。为每家机构分配域名、服务账户、加密库、凭据库和单独的恢复密钥。在同一机构库内建立分院并配置岗位范围。服务由 systemd 托管，通过 HTTPS 反向代理供电脑、手机和小程序访问。

## 1. 安装

以下示例在使用 apt、systemd 的 Linux 上执行。使用支持 Python 3.11 及以上的发行版，将经过验收的源代码部署在 /opt/care-workspace。正式发布从已经评审的提交或签名制品安装，在独立中文测试机构验证升级及回滚。

```sh
sudo apt-get install python3-venv python3-dev build-essential pkg-config libsqlcipher-dev poppler-utils caddy
sudo useradd --system --user-group --home-dir /var/lib/care-workspace --shell /usr/sbin/nologin care-workspace
sudo install -d -m 700 -o care-workspace -g care-workspace /var/lib/care-workspace
sudo install -d -m 750 /etc/care-workspace
cd /opt/care-workspace
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements-storage.txt -r requirements-payments.txt -r requirements-harness.txt -r requirements-a2a.txt
sudo install -m 600 deploy/linux/service.env.example /etc/care-workspace/service.env
sudoedit /etc/care-workspace/service.env
```

把 NH_PUBLIC_ORIGIN 改为机构的真实 HTTPS 域名。NH_DEPLOYMENT_LANGUAGE 选 zh-CN、en、fr 或 es；首次建库时锁定，后续启动会核对。已有中文机构库保持中文。不同语种的机构可各自部署独立实例。中国版使用高德，其他语种默认使用国际版的 Google Maps。医院的在线检索需要运营方配置相应地图服务。只输入医院或城市名称，选择结果后由员工核实。界面词典在本机加载。原始病历、姓名和员工笔记保留原文。现有账务以人民币记账，营业日沿用机构系统的上海时区；其他币种或税务规则需单独适配。

## 2. 正式建库

以下以英文持证机构为例。中文机构使用 zh-CN，两处参数与服务环境保持一致。普通养老机构可选 residential。首次执行会在终端要求输入 Owner 密码。数据库文件必须是新路径。

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

工作台入口为 /?workspace=1，访客入口为 /visit。用 owner 及首次设置的密码登录。进入「系统管理 → 项目部署」检查版本、模型、套餐、HTTP 设备连接和监听端口。托管机构使用平台套餐。由平台自营并允许该机构管理凭据时，运营人员可在部署环境明确设 NH_DEPLOYMENT_MODE=operator 后重启。端口由 systemd 环境固定时，变更需同步代理上游和服务配置。微信/抖音 AppID、业务域名和上线审核见[多端交付](client-compatibility.md)。

## 3. 交付和恢复

在独立的简体中文验收库（`zh-CN`）中，以测试角色走完建档、排床、护理签认、跨分院访问拒绝、支付对账及告警回执。用合成附件做 OCR 和 Agent 测试，核对用量回执。将业务库及快照主密钥、平台凭据库的密钥、设备凭据按职责分别保管，验证运维人员能够在另一台干净主机恢复样本数据和原件。业务快照不包含外置平台凭据。确定自动快照周期、异地目标、恢复时间、停机联系办法，提交首份恢复演练记录。签名升级会先建立并校验完整快照，再切换版本。第三方模型、短信、商户终端及设备分别用正式供应商账户联调。[快照与恢复](backups.md) · [发布升级](updates.md) · [Agent 对接](agent-handbook.md)

### 语言包与业务规则

在同一版本中可以部署中文 zh-CN、英文 en、法文 fr 或西班牙文 es。法文和西班牙文当前包含登录、导航、姓名等基础译文，其余文案回落英文。每个机构仅在首次安装时选择一次。个人中心的主题和字体不影响部署语言。

新增语言时，在 [语言目录](../web/assets/deployment-locales.json) 登记语言标签和显示名，并在 web/assets/locales/<语言标签>.json 放置界面词条。缺省继承 international 规则，包括全球医院查询、Google Maps、结构化国际姓名和邮政地址；中国区使用 china 规则及高德。加载本地静态词典，不转译用户原件。将词典纳入签名发布。仓库回归只运行简体中文版和语言无关的用例。部署的语言描述可从 /api/public/deployment 取得。Google Places 配置 NH_GOOGLE_PLACES_KEY，高德地点检索配置 NH_AMAP_WEB_KEY。服务端保管密钥。

### 医院地图服务配置

工作台的就诊资料支持按原件手动填写医院。中国版提供河南优先的本地名录，在「联网核对医院」输入公开院名或城市，可用高德 POI 查询。国际版在同一位置使用 Google Places，按安装语种请求全球医院。只需打开地图时，无需提供服务密钥。[高德网页搜索 URI](https://lbs.amap.com/api/uri-api/guide/search/search) · [Google Maps 搜索 URL](https://developers.google.com/maps/documentation/urls/get-started)

需要在表单内查看联网结果时，中国版由机构开通高德 Web 服务并在服务器设置 `NH_AMAP_WEB_KEY`。国际版启用 Places API (New) 及计费，然后在服务器设置 `NH_GOOGLE_PLACES_KEY`。将密钥限制为对应 API 和机构服务器地址，重启服务。中文部署验收使用虚构示例或公开院名，核对地址、高德地图跳转与供应商调用记录。断网或未设置密钥时，员工仍可按原件保存病例。[高德 POI 搜索](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch) · [Google Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search)

桌面客户端在员工点击医院链接时调用系统默认浏览器。在线结果只作临时核对。Google Maps 署名图取自官方素材包的 `GoogleMaps_Logo_DarkGray_2x.png`，保持原样并随地点搜索结果展示。该商标的使用遵循 Google Maps 的署名规则。项目的开源许可证不授予该标识的商标权。[Google Maps 署名与使用要求](https://developers.google.com/maps/documentation/places/web-service/policies) · [官方署名素材包](https://developers.google.com/static/maps/documentation/images/Google_Maps_Attribution_Assets.zip)
