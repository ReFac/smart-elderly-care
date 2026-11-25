# 就诊机构补全

本地名录供员工填写就诊机构时查找院名，也保留原件上可能出现的旧称。请按原件记载填写，找不到合适的结果时可手工输入。名录无法用来判断机构目前的执业或医保状态。

数据文件 `hospitals.tsv.gz` 使用无表头的 UTF-8 TSV 格式。每行依次记录机构名称、省份、医保区划或公示所在地、来源优先级。

- 全国名录采用[国家医保局跨省定点医疗机构第二十三期附件一](https://www.nhsa.gov.cn/art/2020/5/22/art_54_3129.html)的 2020 年 4 月数据，保留当时全国各地（含河南）的记录。
- 河南省内另收录[河南省社会保险中心工伤联网结算协议机构名单](https://shbx.hrss.henan.gov.cn/hnsi/fuwu/banshizhinan/ddylunion/webinfo/2025/01/1737520692888748.htm)中的机构。
- 平顶山就医机构参考[平顶山市人民政府公开答复](https://www.pds.gov.cn/contents/60917/414239.html)及[平顶山市卫健委会议公开信息](https://wjw.pds.gov.cn/contents/10110/739967.html)。
- 汝州的补充院名来自[汝州市卫健委 2025 年度助产机构名单](https://www.ruzhou.gov.cn/contents/36823/460499.html)。

更新名录时，生成相同格式的 UTF-8 数据文件，保留机构全名和括号里的别称。员工输入时，名称补全在院内完成。


## 就诊地图 / Hospital directory

中文版优先从本地名录补全河南医院名称，地图使用高德。国际版各语种都可通过 Google Maps 按院名和城市查找全球医院。打开公开地图链接无需密钥。

员工点击「联网核对医院」，在单独的搜索框内输入公开院名或城市。请求不会附带诊疗原件、长辈身份、就诊编号或员工凭证。搜索结果只供核对，病例中保存哪个院名，以原件和员工确认的表单为准。

中文版需在服务端设置 `NH_AMAP_WEB_KEY` 才能使用高德 POI 搜索。国际版使用 Places API (New) Text Search，服务端密钥为 `NH_GOOGLE_PLACES_KEY`。查询使用部署语种，限定医院类别，可在名称后加上城市或国家。机构需向相应服务商开通服务和计费。外部服务不可用时，员工仍可手工填写院名并提交病例。地图接口已用合成响应测试，实际密钥和会产生费用的实时查询留到机构环境验收。[高德 POI 搜索](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch) · [高德 URI 搜索](https://lbs.amap.com/api/uri-api/guide/search/search) · [Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search) · [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)

In international deployments, including French and Spanish, staff can search for hospitals worldwide on Google Maps in the institution’s language. Set `NH_GOOGLE_PLACES_KEY` on the server to get results from Places API (New). The Chinese edition uses an offline directory. Set `NH_AMAP_WEB_KEY` to enable AMap’s Places search.

Only the hospital name or city the employee enters in the search box goes to the external service. Search results are temporary. Use the facility name on the original medical document when completing the record. Staff can open public map links and enter names manually without an API key. The Google Maps attribution shown with Places results uses the official image without modification. [Google Maps attribution guidelines and assets](https://developers.google.com/maps/documentation/places/web-service/policies)
