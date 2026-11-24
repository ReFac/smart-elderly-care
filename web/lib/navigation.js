export const groups = [
  [
    '工作空间',
    [
      ['overview', '运营总览', 'grid'],
      ['inbox', '预警与确认', 'bell'],
      ['history', '最近改动', 'history'],
    ],
  ],
  [
    '照护业务',
    [
      ['beds', '床位管理', 'bed'],
      ['residents', '入住管理', 'people'],
      ['dossier', '个人与医疗档案', 'folder'],
      ['assessments', '能力评估', 'assessment'],
      ['care', '照护服务', 'care'],
      ['medications', '用药管理', 'pill'],
    ],
  ],
  [
    '机构运营',
    [
      ['leads', '意向客户', 'intake'],
      ['inventory', '物资仓储', 'box'],
      ['billing', '财务结算', 'wallet'],
      ['longCare', '长期护理保险', 'shield'],
      ['shifts', '人员排班', 'shifts'],
      ['reports', '统计报送', 'reports'],
    ],
  ],
  [
    '系统管理',
    [
      ['activity', '操作日志', 'list'],
      ['integrations', '设备与接口', 'layers'],
      ['access', '账号与权限', 'shield'],
      ['settings', '机构设置', 'building'],
    ],
  ],
  [
    '院内服务',
    [
      ['family', '家属服务', 'people'],
      ['tour', '环境导览', 'building'],
      ['faq', '常见问题', 'info'],
      ['account', '个人中心', 'people'],
    ],
  ],
];
export const routes = new Map(
  groups.flatMap(([group, items]) => items.map(([id, label, icon]) => [id, { group, label, icon }]))
);

// Saved desktop links and existing account settings retain these keys.
routes.set('rooms', routes.get('beds'));
routes.set('intake', routes.get('residents'));
