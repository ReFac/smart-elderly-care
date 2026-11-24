import { node, field, select, runForm, canAct } from './shared.js';
import { button, statusText, pathName } from './room-elements.js';
import { roomVector, drawRooms } from './room-vector.js';

function editCampus(ctx, campus) {
  runForm(ctx, {
    title: campus ? '编辑分院资料' : '新增分院',
    action: campus ? 'facility.updateCampus' : 'facility.addCampus',
    fields: [
      field('name', '分院名称', { value: campus?.name || '', maxLength: 60 }),
      field('address', '分院地址（选填）', {
        value: campus?.address || '',
        required: false,
        maxLength: 150
      })
    ],
    map: (values) => (campus ? { ...values, campusId: campus.id } : values),
    submitLabel: '保存分院'
  });
}

function renameBuilding(ctx, building) {
  runForm(ctx, {
    title: '修改楼栋名称',
    action: 'facility.renameBuilding',
    description: building.campusName,
    fields: [field('name', '楼栋名称', { value: building.name, maxLength: 60 })],
    map: (values) => ({ ...values, buildingId: building.id }),
    submitLabel: '保存楼栋名称'
  });
}

function addBuilding(ctx, campus) {
  runForm(ctx, {
    title: '新增楼栋',
    action: 'facility.addBuilding',
    description: campus.name,
    map: (values) => ({ ...values, campusId: campus.id }),
    fields: [field('name', '楼栋名称', { placeholder: '例如：二期护理楼', maxLength: 60 })],
    submitLabel: '保存楼栋'
  });
}

function addFloor(ctx, building) {
  runForm(ctx, {
    title: '新增楼层',
    action: 'facility.addFloor',
    description: building.name,
    fields: [field('number', '楼层号', { type: 'number', min: 1, max: 199, step: 1 })],
    map: (values) => ({ buildingId: building.id, number: Number(values.number) }),
    submitLabel: '保存楼层'
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
        value: 60
      }),
      ...coords.map(([key, label]) =>
        field(key, label + '（%）', { type: 'number', min: 0, max: 100, step: 'any' })
      )
    ],
    map: (values) => ({
      ...values,
      ...Object.fromEntries(coords.map(([key]) => [key, Number(values[key])])),
      floorId: floor.id,
      bedCount: Number(values.bedCount),
      dailyRate: Number(values.dailyRate)
    }),
    submitLabel: '保存房间与床位'
  });
}

export function editRoom(ctx, room) {
  const types = Array.from({ length: 13 }, (_, count) => ({
    value: String(count),
    label: ['不设床位', '单人间', '双人间', '三人间'][count] || count + ' 人间',
  }));
  runForm(ctx, {
    title: '编辑房型',
    action: 'facility.updateRoom',
    description: pathName(room.campusName, room.buildingName, room.floorLabel, room.number + ' 房') +
      ' · 已入住 ' + room.occupiedCount + ' 人。减配仅停用空床，历史记录保留。',
    fields: [
      select('bedCount', '房间类型', types, { value: String(room.bedCount) }),
      ...(room.canSetBedRate ? [field('dailyRate', '新增床位日价（元）', {
        value: room.defaultBedDailyRate ?? 60, type: 'number', min: 0, max: 99999,
        required: false, step: '0.01',
      })] : []),
    ],
    map: (values) => {
      const bedCount = Number(values.bedCount);
      return {
        roomId: room.id, bedCount,
        ...(bedCount > room.bedCount && 'dailyRate' in values ? { dailyRate: Number(values.dailyRate) } : {}),
      };
    },
    submitLabel: '保存房型',
  });
}

export function editLayout(ctx, floor) {
  if (!canAct(ctx, 'facility.setLayout') || !floor.vector?.editable) {
    ctx.toast('当前账号没有整层平面图维护权限');
    return;
  }
  const form = node('form', 'room-layout-editor');
  const rows = [];
  const preview = roomVector(floor.vector.viewBox);
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
    rows.push({ room, controls });
    body.append(row);
  }
  grid.append(body);
  const err = statusText('', true);
  err.hidden = true;
  const save = node('button', 'btn btn-primary', '保存全层布局');
  save.type = 'submit';
  form.append(
    node('p', 'room-context', '以平面图左上角为原点，各项使用 0–100 的百分比。'),
    node('div', 'room-layout-preview', preview),
    planField,
    node('div', 'room-layout-wrap', grid),
    err,
    save
  );
  function coordinates() {
    return rows.map(({ room, controls }) => ({
      roomId: room.id,
      ...Object.fromEntries(
        Object.entries(controls).map(([key, input]) => [key, input.valueAsNumber]),
      ),
    }));
  }
  function renderPreview() {
    drawRooms(preview, coordinates().map((rect, index) => ({...rows[index].room, ...rect})), {labels: true});
  }
  form.addEventListener('input', renderPreview);
  renderPreview();
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (save.disabled) return;
    const rooms = coordinates();
    save.disabled = true;
    try {
      if (
        !(await ctx.command('facility.setLayout', {
          floorId: floor.id,
          rooms,
          planMediaUrl: image.value.trim()
        }))
      ) {
        err.textContent = document.getElementById('announcer').textContent || '布局未保存';
        err.hidden = false;
      }
    } finally {
      save.disabled = false;
    }
  });
  ctx.detail('编辑' + floor.label + '矢量平面图', form);
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
        { value: 'panorama', label: '全景照片' }
      ]),
      field('mediaUrl', '机构环境图片地址', { placeholder: '/tour-media/activity-room.jpg' }),
      field('sortOrder', '导览顺序', { type: 'number', min: 0, max: 9999, step: 1, value: 0 })
    ],
    map: (values) => ({ ...values, [scope.key]: scope.id, sortOrder: Number(values.sortOrder) }),
    submitLabel: '保存导览视点'
  });
}

export function chooseAdmin(ctx, building, floor, room, campus, canManage) {
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
  const places = building ? [{ key: 'buildingId', id: building.id, label: building.name }] : [];
  if (floor)
    places.push({ key: 'floorId', id: floor.id, label: pathName(building.name, floor.label) });
  if (room)
    places.push({
      key: 'roomId',
      id: room.id,
      label: pathName(building.name, floor?.label, room.number + ' 房')
    });
  dialog = ctx.detail(
    '空间管理',
    node('div', 'room-admin', [
      group(campus.name + ' · 空间管理', [
        canManage && item('新增分院', 'location', () => editCampus(ctx)),
        canManage && item('编辑分院资料', 'location', () => editCampus(ctx, campus)),
        canManage && item('新增楼栋', 'building', () => addBuilding(ctx, campus)),
        canManage && building && item('修改楼栋名称', 'building', () => renameBuilding(ctx, building)),
        canManage && building &&
          item('在' + building.name + '新增楼层', 'layers', () => addFloor(ctx, building)),
        canManage && floor &&
          item('在' + floor.label + '新增房间与床位', 'bed', () => addRoom(ctx, building, floor)),
        canAct(ctx, 'facility.updateRoom') && room?.canEdit &&
          item('编辑' + room.number + '房房型', 'bed', () => editRoom(ctx, room)),
        canAct(ctx, 'facility.setLayout') && floor?.vector?.editable && floor.rooms.length > 0 &&
          item('编辑' + floor.label + '矢量平面图', 'layers', () => editLayout(ctx, floor))
      ]),
      canManage && places.length > 0 &&
        group(
          '登记环境导览视点',
          places.map((place) => item(place.label, 'location', () => addScene(ctx, place)))
        )
    ])
  );
}
