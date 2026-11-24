# 就诊机构补全

`hospitals.tsv.gz` 为无表头 UTF-8 TSV，每行依次为机构名称、省份、医保区划或公示所在地、来源优先级。仅用于录入时提示历史和当前可能使用的名称。原件记载为准，经办人也可手工录入。名录不判断当前执业或医保状态。

- 全国基线取自[国家医保局跨省定点医疗机构第二十三期附件一](https://www.nhsa.gov.cn/art/2020/5/22/art_54_3129.html)，2020 年 4 月口径，保留全国及河南历史数据。
- 河南补量取自[河南省社会保险中心工伤联网结算协议机构名单](https://shbx.hrss.henan.gov.cn/hnsi/fuwu/banshizhinan/ddylunion/webinfo/2025/01/1737520692888748.htm)。
- 平顶山就医机构参考[平顶山市人民政府公开答复](https://www.pds.gov.cn/contents/60917/414239.html)及[平顶山市卫健委会议公开信息](https://wjw.pds.gov.cn/contents/10110/739967.html)。
- 汝州补量取自[汝州市卫健委 2025 年度助产机构名单](https://www.ruzhou.gov.cn/contents/36823/460499.html)。

更新时只需生成同格式数据文件，通过 UTF-8 保留全名与括号内别称。系统不向外部网站发送查询词或病历资料。
