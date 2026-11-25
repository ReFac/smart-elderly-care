export const stops = [
  {
    id: 'reception', name: '接待大厅', place: '室内 · 来访起点',
    description: '从入口到接待台，再到等候座位。可转动视角看看主要通道和庭院窗景。',
    links: [{id:'activity', point:[2.9, .85, .8]}, {id:'garden', point:[-2.5, .8, 1.4]}],
  },
  {
    id: 'activity', name: '公共活动区', place: '室内 · 交流与起居',
    description: '活动桌周围留出通行位置，也可看看靠窗座位和收纳架的示意。',
    links: [{id:'bedroom', point:[2.9, .8, 1.0]}, {id:'reception', point:[-2.7, .8, 1.3]}],
  },
  {
    id: 'bedroom', name: '长辈居室', place: '室内 · 双人居室示范',
    description: '看看床位间距、床旁通道和个人物品收纳的布置示意。',
    links: [{id:'activity', point:[-2.8, .8, 1.25]}, {id:'garden', point:[2.5, .8, .8]}],
  },
  {
    id: 'garden', name: '户外庭院', place: '室外 · 散步路线',
    description: '沿院内步道看看树荫、长椅和休息亭。实际到访时可和接待人员一起看通行路线。',
    links: [{id:'reception', point:[.15, .8, 1.9]}, {id:'activity', point:[3, .85, .65]}],
  },
];
