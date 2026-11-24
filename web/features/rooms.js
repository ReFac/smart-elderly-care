import { active, canAct, choose, node, page } from './shared.js';
import { admit, profile, transfer } from './residency.js';
import { chooseAdmin } from './room-admin.js';
import { openFacilityTour } from './room-tour.js';
import { button, statusText, pathName, heading, lookup, failure } from './room-elements.js';
export { tourPage, openFacilityTour } from './room-tour.js';

const memory = new Map();

function scopedAgent(ctx, place, label) {
  return ctx.available('assistants') && ctx.startScopedAgent
    ? ctx.ui.button(
        place.roomId ? '房间协作' : place.floorId ? '楼层协作' : '分院协作',
        () => ctx.startScopedAgent({ ...place, label }),
        'secondary',
        'spark'
      )
    : null;
}

function searchBox(ctx, openRoom, campusId) {
  const search = node('input', '');
  search.type = 'search';
  search.placeholder = '搜索长者姓名或房号';
  search.maxLength = 64;
  search.setAttribute('aria-label', '搜索长者姓名或房号');
  const matches = node('div', 'room-matches');
  matches.hidden = true;
  const form = node('form', 'room-search', [
    node('label', 'room-search-box', [ctx.ui.icon('search', 17), search]),
    matches
  ]);
  let generation = 0,
    timer;
  function hide() {
    clearTimeout(timer);
    generation++;
    matches.hidden = true;
    matches.replaceChildren();
  }
  async function find() {
    clearTimeout(timer);
    const term = search.value.trim();
    if (!term) {
      hide();
      return;
    }
    const ticket = ++generation;
    matches.hidden = false;
    matches.replaceChildren(statusText('正在搜索…'));
    try {
      const result = await lookup(ctx, '/search', { q: term, limit: 12, campusId });
      if (ticket !== generation || !form.isConnected) return;
      const list = node('div', 'room-matches-list');
      if (!result.results.length) list.append(statusText('没有匹配的长者或房间'));
      for (const room of result.results) {
        const text = room.matchedNames.length ? room.matchedNames.join('、') : '房间';
        const entry = button(
          pathName(room.campusName, room.buildingName, room.floorLabel, room.number, text),
          async () => {
            hide();
            await openRoom(room.buildingId, room.floorId, room.roomId, room.matchedNames);
          },
          'room-match',
          [
            ctx.ui.icon(room.matchedNames.length ? 'people' : 'bed', 18),
            node('span', '', [
              node('strong', '', room.number + ' 房 · ' + text),
              node('small', '', pathName(room.campusName, room.buildingName, room.floorLabel))
            ]),
            ctx.ui.icon('chevron', 14)
          ]
        );
        const direct =
          room.matchedNames.length === 1 && ctx.available('residents')
            ? button(
                '直接打开' + text + '的档案',
                async () => {
                  hide();
                  const data = await openRoom(
                    room.buildingId,
                    room.floorId,
                    room.roomId,
                    room.matchedNames
                  );
                  if (!data) return;
                  const beds = data.beds.filter((bed) => bed.residentName === text);
                  if (beds.length !== 1) {
                    ctx.toast('请按房内床号核对同名长者');
                    return;
                  }
                  const person = ctx.state.residents.find((r) => r.id === beds[0].residentId);
                  if (person) profile(ctx, person);
                },
                'room-direct-profile',
                '打开档案'
              )
            : null;
        list.append(node('div', 'room-match-row', [entry, direct]));
      }
      matches.replaceChildren(list);
      if (result.hasMore) matches.append(statusText('还有更多结果，可继续输入姓名或房号。'));
    } catch (error) {
      if (ticket === generation) failure(ctx, matches, error, find);
    }
  }
  const schedule = () => {
    hide();
    if (search.value.trim()) timer = setTimeout(find, 180);
  };
  search.addEventListener('input', (event) => {
    if (!event.isComposing) schedule();
  });
  search.addEventListener('compositionend', schedule);
  search.addEventListener('focus', () => {
    if (search.value.trim() && matches.hidden) schedule();
  });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    find();
  });
  form.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      hide();
      search.focus();
      return;
    }
    if (!['ArrowUp', 'ArrowDown'].includes(e.key) || matches.hidden) return;
    const buttons = [...matches.querySelectorAll('button')];
    if (!buttons.length) return;
    e.preventDefault();
    const current = buttons.indexOf(document.activeElement);
    buttons[(current + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
  });
  form.addEventListener('focusout', (e) => {
    if (!form.contains(e.relatedTarget)) hide();
  });
  return form;
}

function floorPlan(ctx, data, chooseRoom) {
  const switches = [];
  const map = node('div', 'room-plan-map');
  map.setAttribute('role', 'group');
  map.setAttribute('aria-label', data.label + '平面图，选择房间');
  const board = node('div', 'room-plan-canvas', [map]);
  let mapStatus;
  if (data.planMediaUrl) {
    const underlay = node('img', 'room-plan-image');
    underlay.alt = data.label + '登记平面图';
    underlay.referrerPolicy = 'no-referrer';
    underlay.draggable = false;
    underlay.addEventListener(
      'load',
      () => {
        const ratio = underlay.naturalWidth / underlay.naturalHeight;
        map.style.aspectRatio = String(ratio);
        map.style.width = 'min(100%, ' + 65 * ratio + 'vh)';
        board.classList.add('survey-loaded');
      },
      { once: true }
    );
    underlay.addEventListener(
      'error',
      () => {
        underlay.remove();
        mapStatus.textContent = '登记的底图无法加载，可按房号定位。';
        mapStatus.hidden = false;
      },
      { once: true }
    );
    mapStatus = statusText('', true);
    mapStatus.hidden = true;
    map.append(underlay);
    underlay.src = data.planMediaUrl;
  }
  const numbers = node('div', 'room-numbers');
  const many = data.rooms.length > 12;
  if (many) board.classList.add('room-plan-large');
  const collection = node('section', 'room-map-card', [
    heading(
      ctx,
      'layers',
      data.label + '平面图',
      scopedAgent(
        ctx,
        { buildingId: data.buildingId, floorId: data.id },
        pathName(data.buildingName, data.label)
      )
    ),
    board,
    mapStatus,
    node('div', 'room-number-picker', [node('h3', '', '按房号选择'), numbers])
  ]);
  if (!data.rooms.length) {
    board.append(
      node('div', 'room-plan-empty', [ctx.ui.icon('layers', 28), node('p', '', '本层尚未登记房间')])
    );
    numbers.append(node('span', 'room-context', '暂无房号'));
  }
  for (const room of data.rooms) {
    const roomLabel = room.number + ' 房';
    const tile = button(roomLabel, () => chooseRoom(room.id), 'room-plan-tile', [
      node('strong', '', room.number),
      node('span', '', [ctx.ui.icon('bed', 14), room.occupiedCount + ' / ' + room.bedCount + ' 床'])
    ]);
    tile.title = roomLabel + ' · ' + room.occupiedCount + ' 张床已入住';
    tile.setAttribute('aria-label', tile.title);
    for (const [name, key] of [
      ['left', 'x'],
      ['top', 'y'],
      ['width', 'w'],
      ['height', 'h']
    ])
      tile.style[name] = room[key] + '%';
    tile.dataset.occupied = String(room.occupiedCount > 0);
    const number = button(roomLabel, () => chooseRoom(room.id), 'room-number', room.number);
    switches.push([room.id, tile, number]);
    map.append(tile);
    numbers.append(number);
  }
  if (data.rooms.length) {
    collection.insertBefore(
      node('div', 'room-map-caption', [
        node('span', 'room-key', [node('i', 'room-dot filled'), '已入住']),
        node('span', 'room-key', [node('i', 'room-dot'), '空房']),
        node(
          'span',
          'room-context',
          data.layoutSource === 'schematic' ? '位置为示意排列' : '房间位置以登记数据为准'
        )
      ]),
      collection.lastChild
    );
  }
  return {
    element: collection,
    select(id) {
      for (const [key, ...controls] of switches)
        for (const item of controls) item.setAttribute('aria-pressed', String(key === id));
    }
  };
}

function placeInBed(ctx, room, bed) {
  const actions = choose();
  const dialog = ctx.detail(
    pathName(room.campusName, room.buildingName, room.floorLabel, bed.label + ' 床'),
    actions
  );
  if (canAct(ctx, 'care.admit'))
    actions.append(
      ctx.ui.button(
        '办理新入住',
        () => {
          dialog.close();
          admit(ctx, { bedId: bed.id });
        },
        'primary'
      )
    );
  if (canAct(ctx, 'care.transfer') && active(ctx).length)
    actions.append(
      ctx.ui.button('转入在住长者', () => {
        dialog.close();
        transfer(ctx, null, bed);
      })
    );
}

function roomDetails(ctx, room, canRead, highlighted, openTour) {
  const people = node('div', 'room-bed-rows');
  for (const bed of room.beds) {
    const resident =
      canRead &&
      bed.residentId &&
      ctx.available('residents') &&
      ctx.state.residents.find((r) => r.id === bed.residentId);
    const allocatable =
      bed.status === '空闲' &&
      (canAct(ctx, 'care.admit') || (canAct(ctx, 'care.transfer') && active(ctx).length));
    const name =
      canRead && bed.residentName ? bed.residentName : allocatable ? '空闲 · 办理分配' : bed.status;
    const body = [
      ctx.ui.icon('bed', 18),
      node('span', '', [node('small', '', bed.label + ' 床'), node('strong', '', name)]),
      resident || allocatable ? ctx.ui.icon('chevron', 14) : null
    ];
    const row = resident
      ? button('查看' + name + '的档案', () => profile(ctx, resident), 'room-bed-row', body)
      : allocatable
        ? button('分配空床 ' + bed.label, () => placeInBed(ctx, room, bed), 'room-bed-row', body)
        : node('div', 'room-bed-row', body);
    if (canRead && highlighted.includes(bed.residentName)) row.classList.add('matched');
    people.append(row);
  }
  return node('div', 'room-inspector', [
    node('header', 'room-detail-head', [
      node('span', 'room-pin', ctx.ui.icon('location', 22)),
      node('div', '', [
        node('small', '', pathName(room.campusName, room.buildingName, room.floorLabel)),
        node('h2', '', room.number + ' 房')
      ])
    ]),
    node('div', 'room-detail-meta', [node('span', '', '照护区'), node('strong', '', room.ward)]),
    node('div', 'room-detail-meta', [
      node('span', '', '入住床位'),
      node('strong', '', room.occupiedCount + ' / ' + room.bedCount + ' 床')
    ]),
    node('section', 'room-bed-list', [
      node('h3', '', '床位明细'),
      room.beds.length ? people : statusText('尚未设置床位')
    ]),
    node('div', 'room-room-actions', [
      ctx.available('tour')
        ? ctx.ui.button('查看房间环境', openTour, 'secondary', 'location')
        : null,
      scopedAgent(
        ctx,
        { buildingId: room.buildingId, floorId: room.floorId, roomId: room.id },
        pathName(room.campusName, room.buildingName, room.floorLabel, room.number + ' 房')
      )
    ])
  ]);
}

export function roomsPage(ctx) {
  const stage = node('div', 'room-stage', statusText('正在读取楼栋…'));
  const controls = node('div', 'room-controls');
  const area = node('div', 'room-area');
  const root = page(
    ctx,
    '房间工作台',
    '选择分院、楼栋和楼层，可通过平面图、房号或长者姓名定位房间。',
    controls,
    stage
  );
  const actor = ctx.state.user.id;
  const saved = memory.get(actor) || {};
  let directory, campus, building, floor, room, floorMap, detailPanel;
  let floorRequest = 0,
    detailRequest = 0;
  function remember() {
    memory.set(actor, {
      campusId: campus?.id,
      buildingId: building?.id,
      floorId: floor?.id,
      roomId: room?.id
    });
  }
  async function chooseRoom(id, names = []) {
    const ticket = ++detailRequest;
    floorMap?.select(id);
    room = null;
    detailPanel.replaceChildren(statusText('正在读取房间…'));
    try {
      const data = await lookup(ctx, '/rooms/' + encodeURIComponent(id));
      if (ticket !== detailRequest || !root.isConnected) return;
      room = data;
      remember();
      detailPanel.replaceChildren(
        roomDetails(ctx, room, directory.canReadResidents, names, () => {
          openFacilityTour(
            ctx,
            { roomId: data.id },
            pathName(data.campusName, data.buildingName, data.floorLabel, data.number + ' 房')
          );
        })
      );
      return data;
    } catch (error) {
      if (ticket === detailRequest) failure(ctx, detailPanel, error, () => chooseRoom(id, names));
    }
  }
  function nav() {
    const branch = node('select', 'room-building-select');
    branch.setAttribute('aria-label', '选择分院');
    if (campus.address) branch.title = campus.address;
    for (const item of directory.campuses)
      branch.add(new Option(item.name, item.id, false, campus.id === item.id));
    branch.addEventListener('change', () => switchCampus(branch.value));
    const pick = node('select', 'room-building-select');
    pick.setAttribute('aria-label', '选择楼栋');
    for (const item of directory.buildings.filter((b) => b.campusId === campus.id))
      pick.add(new Option(item.name, item.id, false, building?.id === item.id));
    pick.addEventListener('change', () => switchLevel(pick.value));
    const chips = node('div', 'room-floors');
    chips.setAttribute('aria-label', '选择楼层');
    for (const lv of building?.floors || []) {
      const chip = button(lv.label, () => switchLevel(building.id, lv.id), 'room-floor-btn');
      chip.setAttribute('aria-pressed', String(lv.id === floor?.id));
      chips.append(chip);
    }
    return node('div', 'room-locator', [
      node('label', 'room-building', [node('span', '', '分院'), branch]),
      building ? node('label', 'room-building', [node('span', '', '楼栋'), pick]) : null,
      chips,
      scopedAgent(ctx, { campusId: campus.id }, campus.name)
    ]);
  }
  async function switchLevel(buildingId, floorId, roomId, names = []) {
    if (
      roomId &&
      floorMap &&
      buildingId === building?.id &&
      floorId === floor?.id &&
      floor.rooms.some((r) => r.id === roomId)
    ) {
      return chooseRoom(roomId, names);
    }
    const ticket = ++floorRequest;
    detailRequest++;
    const next = directory.buildings.find((b) => b.id === buildingId);
    if (!next) return;
    building = next;
    floor = building.floors.find((f) => f.id === floorId) || building.floors[0];
    room = null;
    floorMap = null;
    remember();
    const main = node('div', 'room-content', statusText('正在读取楼层…'));
    area.replaceChildren(nav(), main);
    if (!floor) {
      main.replaceChildren(statusText('此楼栋尚未登记楼层'));
      return;
    }
    try {
      const data = await lookup(ctx, '/floors/' + encodeURIComponent(floor.id));
      if (ticket !== floorRequest || !root.isConnected) return;
      floor = data;
      floorMap = floorPlan(ctx, data, chooseRoom);
      detailPanel = node('aside', 'room-detail');
      main.replaceChildren(floorMap.element, detailPanel);
      const first = data.rooms.find((r) => r.id === roomId) || data.rooms[0];
      if (first) return await chooseRoom(first.id, names);
      else
        detailPanel.replaceChildren(
          heading(ctx, 'bed', '房间详情'),
          statusText('选择有房间的楼层查看明细')
        );
    } catch (error) {
      if (ticket === floorRequest)
        failure(ctx, main, error, () => switchLevel(buildingId, floorId, roomId, names));
    }
  }
  async function switchCampus(id, initial = {}) {
    ++floorRequest;
    ++detailRequest;
    campus = directory.campuses.find((item) => item.id === id) || directory.campuses[0];
    const buildings = directory.buildings.filter((b) => b.campusId === campus.id);
    building = floor = room = floorMap = detailPanel = null;
    controls.replaceChildren(searchBox(ctx, switchLevel, campus.id));
    if (directory.canManage)
      controls.append(
        ctx.ui.button(
          '空间管理',
          () => chooseAdmin(ctx, building, floor, room, campus),
          'secondary',
          'building'
        )
      );
    if (!buildings.length) {
      remember();
      area.replaceChildren(nav(), statusText('此分院尚未登记楼栋'));
      return;
    }
    const first = buildings.find((b) => b.id === initial.buildingId) || buildings[0];
    await switchLevel(first.id, initial.floorId, initial.roomId);
  }
  async function load() {
    stage.replaceChildren(statusText('正在读取分院…'));
    try {
      directory = await lookup(ctx, '');
      if (!root.isConnected) return;
      if (!directory.campuses.length) {
        stage.replaceChildren(statusText('当前账号没有获授权的分院'));
        return;
      }
      stage.replaceChildren(area);
      await switchCampus(saved.campusId, saved);
    } catch (error) {
      failure(ctx, stage, error, load);
    }
  }
  load();
  return root;
}
