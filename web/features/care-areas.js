import { badge, btn, choose, named, node, table } from './shared.js';

const endpoint = '/api/care/areas';

function label(title, input) {
  return node('label', 'field', [node('span', '', title), input]);
}

function select(options, value) {
  const result = node('select');
  for (const [id, name] of options) result.add(new Option(name, id));
  if (value != null) result.value = value;
  return result;
}

function checkbox(checked) {
  const control = node('input');
  control.type = 'checkbox';
  control.checked = checked;
  return control;
}

function areaForm(ctx, title, parts, submit) {
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const button = node('button', 'btn btn-primary', '核对并保存');
  button.type = 'submit';
  const form = node('form', 'care-area-editor', [...parts, error]);
  const dialog = ctx.detail(title, form);
  dialog.classList.add('care-area-dialog');
  form.append(node('footer', 'care-area-form-actions', [btn(ctx, '返回', () => dialog.close()), button]));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled || !form.reportValidity()) return;
    error.textContent = '';
    button.disabled = true;
    try {
      if (await submit()) dialog.close();
    } catch (cause) {
      error.textContent = cause.message || '暂时无法保存区域设置。';
    } finally {
      button.disabled = false;
    }
  });
  return dialog;
}

function spacePicker(data, area) {
  const floorIds = new Set(area?.floorIds || []);
  const roomIds = new Set(area?.roomIds || []);
  const areaById = new Map(data.areas.map(row => [row.id, row]));
  const roomsByFloor = Map.groupBy(data.rooms, room => room.floorId);
  const count = node('p', 'care-area-selection');
  count.setAttribute('role', 'status');

  function owner(place) {
    if (!place.areaId || place.areaId === area?.id) return '';
    return areaById.get(place.areaId)?.path || '其他区域';
  }

  function refresh() {
    count.textContent = '已选 ' + floorIds.size + ' 个整层、' + roomIds.size + ' 间单独房间';
  }

  function mapCheck(place, title, ids) {
    const control = checkbox(ids.has(place.id));
    control.addEventListener('change', () => {
      if (control.checked) ids.add(place.id);
      else ids.delete(place.id);
      refresh();
    });
    const previous = owner(place);
    return node('label', 'care-area-check', [control, named(title, previous ? '原分区 · ' + previous : '')]);
  }

  const sections = data.floors.map((floor, index) => {
    const rooms = roomsByFloor.get(floor.id) || [];
    const details = node('details', 'care-area-spaces', [
      node('summary', '', '单独划分房间 · ' + rooms.length + ' 间'),
      node('div', 'care-area-room-options', rooms.map(room => mapCheck(room, room.number + ' 房', roomIds))),
    ]);
    details.open = index === 0 || rooms.some(room => roomIds.has(room.id));
    details.hidden = !rooms.length;
    return node('div', 'care-area-floor-card', [mapCheck(floor, '整层 · ' + floor.label, floorIds), details]);
  });

  refresh();
  return {
    element: node('section', 'care-area-space-editor', [
      node('div', 'care-area-section-heading', [node('h3', '', '楼层和房间'), count]),
      node('p', 'fx-muted', '整层包含未单独分区的房间。为某个房间单独选区后，优先使用该房间的区域。'),
      ...sections,
      sections.length ? null : node('p', 'fx-muted', '楼栋暂无登记楼层。'),
    ]),
    read() {
      const selectedFloors = data.floors.filter(floor => floorIds.has(floor.id));
      const selectedRooms = data.rooms.filter(room => roomIds.has(room.id));
      const floorNames = new Map(data.floors.map(floor => [floor.id, floor.label]));
      const roomName = room => [floorNames.get(room.floorId), room.number + ' 房'].filter(Boolean).join(' · ');
      const realigned = [
        ...selectedFloors.filter(owner).map(floor => floor.label + '（原属' + owner(floor) + '）'),
        ...selectedRooms.filter(owner).map(room => roomName(room) + '（原属' + owner(room) + '）'),
      ];
      return {
        floorIds: selectedFloors.map(floor => floor.id),
        roomIds: selectedRooms.map(room => room.id),
        fields: [
          ['整层', selectedFloors.map(floor => floor.label).join('、') || '未选'],
          ['单独房间', selectedRooms.map(roomName).join('、') || '未选'],
          ...(realigned.length ? [['改归本区', realigned.join('、')]] : []),
        ],
      };
    },
  };
}

function editArea(ctx, data, area, parentId) {
  const name = node('input');
  name.type = 'text';
  name.required = true;
  name.maxLength = 60;
  name.value = area?.name || '';
  name.placeholder = '例如 东区、失能照护区';
  const subtree = new Set();
  if (area) {
    const groups = Map.groupBy(data.areas, item => item.parentId);
    const pending = [area];
    while (pending.length) {
      const item = pending.pop();
      if (subtree.has(item.id)) continue;
      subtree.add(item.id);
      pending.push(...(groups.get(item.id) || []));
    }
  }
  const parent = select([
    ['', '顶层区域'],
    ...data.areas.filter(item => !subtree.has(item.id)).map(item => [item.id, item.path]),
  ], area?.parentId || parentId || '');
  const mapping = spacePicker(data, area);
  const building = data.buildings.find(item => item.id === data.buildingId);
  const title = area ? '编辑区域' : '新建区域';
  return areaForm(ctx, title, [
    node('p', 'care-area-place', [ctx.ui.icon('building', 16), buildingLabel(building)]),
    node('div', 'care-area-form-grid', [label('区域名称', name), label('上级区域', parent)]),
    mapping.element,
  ], () => {
    const clean = name.value.trim();
    if (!clean) throw new Error('请输入区域名称。');
    const {floorIds, roomIds, fields} = mapping.read();
    return ctx.command('care.areaSave', {
      buildingId: data.buildingId,
      ...(area ? { id: area.id } : {}),
      name: clean, parentId: parent.value, floorIds, roomIds,
    }, {
      title, target: clean,
      fields: [['楼栋', buildingLabel(building)], ['上级区域', parent.selectedOptions[0].text], ...fields],
    });
  });
}

function buildingLabel(building) {
  return building ? [building.campusName, building.name].filter(Boolean).join(' · ') : '当前楼栋';
}

function tree(data, check) {
  const children = Map.groupBy(data.areas, row => row.parentId || '');
  const ids = new Set(data.areas.map(item => item.id));
  const roots = data.areas.filter(item => !ids.has(item.parentId));
  function branch(items) {
    return node('ul', 'care-area-tree', items.map(item => {
      const zones = children.get(item.id) || [];
      return node('li', '', [
        check(item),
        zones.length ? branch(zones) : null,
      ]);
    }));
  }
  return branch(roots);
}

function chooseAreas(ctx, data, person) {
  const chosen = new Set(data.areas.filter(area => person.areaIds.includes(area.id)).map(area => area.id));
  const count = node('strong', 'care-area-selection');
  count.setAttribute('role', 'status');
  function sync() { count.textContent = '已选 ' + chosen.size + ' 个区域'; }
  const list = tree(data, item => {
    const control = checkbox(chosen.has(item.id));
    control.addEventListener('change', () => {
      if (control.checked) chosen.add(item.id);
      else chosen.delete(item.id);
      sync();
    });
    return node('label', 'care-area-check', [control, item.name]);
  });
  sync();
  const building = data.buildings.find(row => row.id === data.buildingId);
  return areaForm(ctx, '分配护理区域', [
    node('div', 'care-area-section-heading', [
      named(staffName(person), buildingLabel(building)), count,
    ]),
    node('p', 'fx-muted', '选择上级区域会覆盖其全部子区域。这次保存仅应用于当前楼栋。'),
    data.areas.length ? list : node('p', 'fx-muted', '本栋暂无区域，请先新建区域。'),
  ], () => {
    const areaIds = data.areas.filter(row => chosen.has(row.id)).map(row => row.id);
    return ctx.command('care.areaAssign', { buildingId: data.buildingId, staffId: person.id, areaIds }, {
      title: '确认分配护理区域',
      target: staffName(person),
      fields: [
        ['楼栋', buildingLabel(building)],
        ['负责区域', areaIds.map(id => data.areas.find(row => row.id === id)?.path).join('、') || '清除当前楼栋分配'],
      ],
    });
  });
}

function staffName(person) {
  return person.name + (person.role ? '（' + person.role + '）' : '');
}

function assignments(ctx, data) {
  return table(ctx, {
    title: '护工区域分配',
    rows: data.staff,
    empty: '此楼栋暂时没有可查看的护理人员。',
    search: { placeholder: '搜索姓名、岗位或登录账号', value: row => [row.name, row.role, row.username] },
    cols: [
      { label: '护理人员', view: row => named(staffName(row), row.username) },
      { label: '本楼栋负责区域', view: row => {
        const names = data.areas.filter(item => row.areaIds.includes(item.id));
        return names.length ? node('div', 'care-area-tags', names.map(item => node('span', '', item.path))) :
          node('span', 'fx-muted', '待分配');
      } },
      { label: '操作', align: 'end', view: row => {
        if (!data.canManage || !data.areas.length) return '—';
        if (row.selectable) return btn(ctx, '分配区域', () => chooseAreas(ctx, data, row));
        return row.areaIds.length ? btn(ctx, '清除本楼栋分配', () => ctx.command('care.areaAssign', {
          buildingId: data.buildingId, staffId: row.id, areaIds: [],
        }, { title: '清除本楼栋分配', target: staffName(row) })) : '—';
      } },
    ],
  });
}

function coverage(data, area) {
  const floors = data.floors.filter(floor => area.floorIds.includes(floor.id));
  const rooms = data.rooms.filter(room => room.effectiveAreaId === area.id);
  const directRooms = new Set(area.roomIds);
  const groups = Map.groupBy(rooms, room => room.floorId);
  const floorLabel = new Map(data.floors.map(floor => [floor.id, floor.label]));
  return node('div', 'care-area-coverage', [
    node('div', 'care-area-section-heading', [
      node('h4', '', '直接覆盖房间'),
      node('span', 'fx-muted', floors.length + ' 个整层设为本区 · ' + rooms.length + ' 间房实际归本区'),
    ]),
    groups.size ? node('div', 'care-area-position-list', [...groups].map(([floor, places]) =>
      node('div', 'care-area-position-row', [
        node('strong', '', floorLabel.get(floor) || '楼层'),
        node('div', 'care-area-tags', places.map(room =>
          node('span', directRooms.has(room.id) ? 'care-area-direct' : '', room.number + ' 房'))),
      ]))) : node('p', 'fx-muted', '该区域暂无直接覆盖的房间。可在编辑区域中选择整层或具体房间。'),
  ]);
}

function areaDetails(ctx, data, zone) {
  if (!zone) return ctx.ui.empty('本栋暂无可显示的区域。');
  const children = data.areas.filter(item => item.parentId === zone.id);
  const team = data.staff.filter(row => row.areaIds.includes(zone.id));
  const ledger = node('a','btn btn-ghost','查看区域床位台账');
  ledger.href = '#beds?' + new URLSearchParams({tab:'all',building:data.buildingId,area:zone.id});
  const heading = node('div', 'care-area-detail-heading', [
    node('div', '', [
      node('p', 'fx-muted', zone.path),
      node('h3', '', zone.name),
    ]),
    ledger, data.canManage ? choose(
      btn(ctx, '编辑区域', () => editArea(ctx, data, zone)),
      btn(ctx, '新增子区域', () => editArea(ctx, data, null, zone.id)),
      children.length ? null : btn(ctx, '归档区域', () => ctx.command('care.areaArchive', {
        buildingId: data.buildingId, id: zone.id,
      }, {
        title: '归档护理区域', target: zone.path, confirmLabel: '确认归档',
        fields: [['归档范围', '解除本区域的空间划分和人员分配']],
      })),
    ) : null,
  ]);
  return node('article', 'care-area-detail', [
    heading, coverage(data, zone),
    node('div', 'care-area-coverage', [
      node('h4', '', '直接分配的护理人员'),
      team.length ? node('div', 'care-area-tags', team.map(person => node('span', '', staffName(person)))) :
        node('p', 'fx-muted', '可在下方为护理人员分配本区。'),
    ]),
    children.length ? node('p', 'care-area-child-note', '含 ' + children.length + ' 个下级区域。上级区域的护理人员可负责其子区域。') : null,
  ]);
}

export function careAreas(ctx) {
  const userId = ctx.state.user?.id;
  const memory = ctx.workspaceState ||= {};
  let selection = memory.areaDesk && memory.areaDesk.userId === userId ? memory.areaDesk : { userId };
  const panel = node('section', 'care-areas');
  let serial = 0;

  function render(data) {
    const area = data.areas.find(item => item.id === selection.areaId) || data.areas[0];
    const current = data.buildings.find(item => item.id === data.buildingId);
    selection = { userId, buildingId: data.buildingId, areaId: area?.id };
    memory.areaDesk = selection;
    const buildings = select(data.buildings.map(item => [item.id, buildingLabel(item)]), data.buildingId);
    buildings.setAttribute('aria-label', '选择楼栋');
    buildings.addEventListener('change', () => load(buildings.value, true));
    const header = node('header', 'care-area-workspace-header', [
      node('div', 'care-area-heading', [
        node('span', 'care-area-workspace-icon', ctx.ui.icon('layers', 22)),
        node('div', '', [
          node('h2', '', '区域设置'),
          node('p', 'fx-muted', current ? [current.name, data.floors.length + ' 层', data.rooms.length + ' 间房',
            data.areas.length + ' 个区域'].join(' · ') : ''),
        ]),
      ]),
      node('div', 'care-area-workspace-actions', [
        data.buildings.length ? label('当前楼栋', buildings) : null,
        data.canManage && current ? btn(ctx, '新建区域', () => editArea(ctx, data), 'primary') : null,
      ]),
    ]);
    if (!current) {
      panel.replaceChildren(header, ctx.ui.empty('当前账号没有可查看的楼栋。'));
      return;
    }
    const side = node('nav', 'care-area-sidebar');
    side.setAttribute('aria-label', '本楼栋区域');
    const detail = node('div', 'care-area-main');
    function update(selected) {
      selection = { ...selection, areaId: selected?.id };
      memory.areaDesk = selection;
      const items = tree(data, row => {
        const control = btn(ctx, row.name, () => {
          update(row);
          [...side.querySelectorAll('[data-area]')].find(button => button.dataset.area === row.id)?.focus();
        }, 'ghost');
        control.dataset.area = row.id;
        if (row.id === selected?.id) control.setAttribute('aria-current', 'true');
        control.prepend(ctx.ui.icon('location', 15));
        return control;
      });
      side.replaceChildren(
        node('div', 'care-area-sidebar-title', [node('h3', '', '区域与子区域'), badge(ctx, data.areas.length + ' 个', 'neutral')]),
        data.areas.length ? items : node('p', 'fx-muted', '点击「新建区域」从整栋开始规划。'),
      );
      detail.replaceChildren(areaDetails(ctx, data, selected));
    }
    update(area);
    panel.replaceChildren(header, node('div', 'care-area-office', [side, detail]), assignments(ctx, data));
  }

  async function load(buildingId, focusBuilding = false) {
    const attempt = ++serial;
    const loading = node('p', 'fx-muted', '正在读取楼栋区域…');
    loading.setAttribute('role', 'status');
    panel.replaceChildren(loading);
    try {
      const query = buildingId ? '?' + new URLSearchParams({ buildingId }) : '';
      const data = await ctx.get(endpoint + query);
      if (attempt !== serial) return;
      render(data);
      if (focusBuilding && panel.isConnected) panel.querySelector('select')?.focus();
    } catch (error) {
      if (attempt === serial)
        panel.replaceChildren(node('p', 'form-error', error.message || '无法读取楼栋区域'), btn(ctx, '重新读取', () => load()));
    }
  }

  load(selection.buildingId);
  return panel;
}
