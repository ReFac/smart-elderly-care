# 就诊机构补全

`hospitals.tsv.gz` 为无表头 UTF-8 TSV，每行依次为机构名称、省份、医保区划或公示所在地、来源优先级。仅用于录入时提示历史和当前可能使用的名称。原件记载为准，经办人也可手工录入。名录不判断当前执业或医保状态。

- 全国基线取自[国家医保局跨省定点医疗机构第二十三期附件一](https://www.nhsa.gov.cn/art/2020/5/22/art_54_3129.html)，2020 年 4 月口径，保留全国及河南历史数据。
- 河南补量取自[河南省社会保险中心工伤联网结算协议机构名单](https://shbx.hrss.henan.gov.cn/hnsi/fuwu/banshizhinan/ddylunion/webinfo/2025/01/1737520692888748.htm)。
- 平顶山就医机构参考[平顶山市人民政府公开答复](https://www.pds.gov.cn/contents/60917/414239.html)及[平顶山市卫健委会议公开信息](https://wjw.pds.gov.cn/contents/10110/739967.html)。
- 汝州补量取自[汝州市卫健委 2025 年度助产机构名单](https://www.ruzhou.gov.cn/contents/36823/460499.html)。

更新时只需生成同格式数据文件，通过 UTF-8 保留全名与括号内别称。本地名称补全在院内完成。


## 就诊地图 / Hospital directory

中文版使用河南优先的离线名称补全，地图指向高德。所有国际版语种均可按医院和城市名在全球范围查找，地图指向 Google Maps。公开地图链接无需密钥。员工点击「联网核对医院」后，在独立的搜索框输入公开院名或城市。诊疗原件、长辈身份、就诊编号和员工凭证均不随请求发送。联网结果供核对，病例中保存的机构名称以原件和员工确认的表单为准。

中文环境配置服务端 `NH_AMAP_WEB_KEY` 后可调用高德 POI 搜索。国际版配置服务端 `NH_GOOGLE_PLACES_KEY` 后可调用 Places API (New) Text Search。国际版查询使用部署语种与医院类别，支持名称加城市或国家。两者均需机构自行开通对应服务和账单。外部服务不可用时，仍可手动填写并提交病例。官方地图联调使用合成响应测试，密钥与产生实际费用的实时查询需在机构环境验收。[高德 POI 搜索](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch) · [高德 URI 搜索](https://lbs.amap.com/api/uri-api/guide/search/search) · [Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search) · [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)

All international deployments, including French and Spanish, use a worldwide Google Maps search in the institutional locale. Set `NH_GOOGLE_PLACES_KEY` on the server to enable Places API (New) results. The Chinese edition uses the offline institution directory and can use AMap's Places search with `NH_AMAP_WEB_KEY`. An external request sends only the hospital or city term explicitly entered by the employee. Results are transient. Record the facility printed on the medical source. Both public map links and manual entry work without an API key. The Google Maps attribution image is an unmodified official asset used in Places search results. [Google Maps attribution guidelines and assets](https://developers.google.com/maps/documentation/places/web-service/policies)
