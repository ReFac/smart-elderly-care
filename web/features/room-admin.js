import { node, field, select, runForm } from './shared.js';
import { button, statusText, pathName } from './room-elements.js';

function addBuilding(ctx) {
  runForm(ctx, {
    title: '新增楼栋',
    action: 'facility.addBuilding',
    fields: [field('name', '楼栋名称', { placeholder: '例如：二期护理楼', maxLength: 60 })],
    submitLabel: '保存楼栋',
  });
}

function addFloor(ctx, building) {
  runForm(ctx, {
    title: '新增楼层',
    action: 'facility.addFloor',
    description: building.name,
    fields: [field('number', '楼层号', { type: 'number', min: 1, max: 199, step: 1 })],
    map: (values) => ({ buildingId: building.id, number: Number(values.number) }),
    submitLabel: '保存楼层',
  });
}

const rectangleFields = { x: '横向起点', y: '纵向起点', w: '宽度', h: '高度' };

function addRoom(ctx, building, floor) {
  const coords = floor.layoutSource === 'registered' ? Object.entries(rectangleFields) : [];
  runForm(ctx, {
    title: '新增房间与床位',
    action: 'facility.addRoom',
    description: pathName(building.name, floor.label),
    fields: [
      field('number', '房间号', { placeholder: '例如：501', maxLength: 32 }),
      field('ward', '所属照护区', { placeholder: '填写实际照护区名称', maxLength: 60 }),
      field('bedCount', '初始床位数', { type: 'number', min: 0, max: 12, step: 1, value: 2 }),
      field('dailyRate', '单床日价（元）', {
        type: 'number',
        min: 0,
        max: 99999,
        step: '0.01',
        value: 60,
      }),
      ...coords.map(([key, label]) =>
        field(key, label + '（%）', { type: 'number', min: 0, max: 100, step: 'any' })
      ),
    ],
    map: (values) => ({
      ...values,
      ...Object.fromEntries(coords.map(([key]) => [key, Number(values[key])])),
      floorId: floor.id,
      bedCount: Number(values.bedCount),
      dailyRate: Number(values.dailyRate),
    }),
    submitLabel: '保存房间与床位',
  });
}

function addBeds(ctx, room) {
  runForm(ctx, {
    title: '扩充房间床位',
    action: 'facility.addBeds',
    description:
      pathName(room.buildingName, room.floorLabel, room.number + ' 房') +
      ' · 已有 ' +
      room.bedCount +
      ' 张床',
    fields: [
      field('count', '新增床位数', {
        type: 'number',
        min: 1,
        max: 12 - room.bedCount,
        step: 1,
        value: 1,
      }),
      field('dailyRate', '新增床位日价（元）', {
        type: 'number',
        min: 0,
        max: 99999,
        step: '0.01',
        value: 60,
      }),
    ],
    map: (values) => ({
      roomId: room.id,
      count: Number(values.count),
      dailyRate: Number(values.dailyRate),
    }),
    submitLabel: '保存新增床位',
  });
}

function editLayout(ctx, floor) {
  const form = node('form', 'room-layout-editor');
  const rows = [];
  const image = node('input', 'fx-input');
  image.type = 'text';
  image.name = 'planMediaUrl';
  image.value = floor.planMediaUrl || '';
  image.placeholder = '/tour-media/floor-plan.png';
  const planField = node('label', 'field', [node('span', '', '实测底图地址（选填）'), image]);
  const grid = node('table', 'room-layout-table');
  grid.append(
    node(
      'thead',
      '',
      node(
        'tr',
        '',
        ['房间', '横向起点', '纵向起点', '宽度', '高度'].map((label) => node('th', '', label))
      )
    )
  );
  const body = node('tbody');
  for (const room of floor.rooms) {
    const controls = {};
    const row = node('tr', '', node('th', '', room.number));
    for (const [key, label] of Object.entries(rectangleFields)) {
      const input = node('input', 'fx-input');
      input.required = true;
      input.type = 'number';
      input.min = '0';
      input.max = '100';
      input.step = 'any';
      input.value = room[key];
      input.setAttribute('aria-label', room.number + ' 房 ' + label + '百分比');
      controls[key] = input;
      row.append(node('td', '', input));
    }
    rows.push({ roomId: room.id, controls });
    body.append(row);
  }
  grid.append(body);
  const err = statusText('', true);
  err.hidden = true;
  const save = node('button', 'btn btn-primary', '保存全层布局');
  save.type = 'submit';
  form.append(
    node('p', 'room-context', '以平面图左上角为原点，各项使用 0–100 的百分比。'),
    planField,
    node('div', 'room-layout-wrap', grid),
    err,
    save
  );
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (save.disabled) return;
    const rooms = rows.map(({ roomId, controls }) => ({
      roomId,
      ...Object.fromEntries(
        Object.entries(controls).map(([key, input]) => [key, Number(input.value)])
      ),
    }));
    save.disabled = true;
    try {
      if (
        !(await ctx.command('facility.setLayout', {
          floorId: floor.id,
          rooms,
          planMediaUrl: image.value.trim(),
        }))
      ) {
        err.textContent = document.getElementById('announcer').textContent || '布局未保存';
        err.hidden = false;
      }
    } finally {
      save.disabled = false;
    }
  });
  ctx.detail('登记' + floor.label + '实际房间位置', form);
}

function addScene(ctx, scope) {
  runForm(ctx, {
    title: '登记导览视点',
    action: 'facility.setScene',
    description: scope.label,
    fields: [
      field('title', '视点名称', { placeholder: '例如：公共活动区' }),
      select('kind', '素材类型', [
        { value: 'photo', label: '环境照片' },
        { value: 'panorama', label: '全景照片' },
      ]),
      field('mediaUrl', '机构环境图片地址', { placeholder: '/tour-media/activity-room.jpg' }),
      field('sortOrder', '导览顺序', { type: 'number', min: 0, max: 9999, step: 1, value: 0 }),
    ],
    map: (values) => ({ ...values, [scope.key]: scope.id, sortOrder: Number(values.sortOrder) }),
    submitLabel: '保存导览视点',
  });
}

export function chooseAdmin(ctx, building, floor, room) {
  const group = (label, actions) =>
    node('section', 'room-admin-group', [node('h3', '', label), ...actions]);
  let dialog;
  const item = (title, icon, fn) =>
    button(
      title,
      () => {
        dialog.close();
        fn();
      },
      'room-admin-link',
      [ctx.ui.icon(icon, 16), node('span', '', title), ctx.ui.icon('chevron', 14)]
    );
  const places = [{ key: 'buildingId', id: building.id, label: building.name }];
  if (floor)
    places.push({ key: 'floorId', id: floor.id, label: pathName(building.name, floor.label) });
  if (room)
    places.push({
      key: 'roomId',
      id: room.id,
      label: pathName(building.name, floor?.label, room.number + ' 房'),
    });
  dialog = ctx.detail(
    '空间管理',
    node('div', 'room-admin', [
      group('院区扩建', [
        item('新增楼栋', 'building', () => addBuilding(ctx)),
        item('在' + building.name + '新增楼层', 'layers', () => addFloor(ctx, building)),
        floor &&
          item('在' + floor.label + '新增房间与床位', 'bed', () => addRoom(ctx, building, floor)),
        room &&
          room.bedCount < 12 &&
          item('为' + room.number + '房扩充床位', 'bed', () => addBeds(ctx, room)),
        floor?.rooms?.length > 0 &&
          item('登记' + floor.label + '实际房间位置', 'layers', () => editLayout(ctx, floor)),
      ]),
      group(
        '登记环境导览视点',
        places.map((place) => item(place.label, 'location', () => addScene(ctx, place)))
      ),
    ])
  );
}
