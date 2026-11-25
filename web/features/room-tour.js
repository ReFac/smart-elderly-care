import { stops } from './tour-stops.js';
import { node, page, canAct, runForm } from './shared.js';
import { button, statusText, pathName, heading, lookup, failure } from './room-elements.js';

function tourViewer(ctx, scope, initialLabel) {
  const container = node('div', 'room-tour', statusText('正在读取环境导览…'));
  const changed = (controls, i) =>
    controls.forEach((item, index) => item.setAttribute('aria-pressed', String(index === i)));
  async function load() {
    container.replaceChildren(statusText('正在读取环境导览…'));
    try {
      const data = await lookup(ctx, '/tour', scope);
      if (!data.scenes.length) {
        container.replaceChildren(
          node('div', 'room-tour-empty', [
            node('span', 'room-tour-empty-icon', ctx.ui.icon('building', 32)),
            node('h2', '', initialLabel || ctx.state.uiSettings.institutionName),
            node('p', '', '此范围尚未发布环境照片或全景视点。')
          ])
        );
        return;
      }
      const photo = node('div', 'room-scene-frame');
      const text = node('div', 'room-scene-title');
      const count = node('span', 'room-context');
      const places = node('div', 'room-tour-stops');
      const controls = [];
      const memory = ctx.workspaceState ||= {};
      const positions = memory.tourPositions ||= {};
      const scopeKey = JSON.stringify(scope);
      let active = 0;
      const move = (delta) => show(active + delta);
      const prev = ctx.ui.button('上一站', () => move(-1));
      const next = ctx.ui.button('下一站', () => move(1));
      const withdraw =
        canAct(ctx, 'facility.withdrawScene') &&
        ctx.ui.button('撤下视点', () => {
          const scene = data.scenes[active];
          runForm(ctx, {
            title: '撤下导览视点',
            action: 'facility.withdrawScene',
            description: '确认从环境导览中撤下“' + scene.title + '”。',
            map: () => ({ sceneId: scene.id }),
            submitLabel: '确认撤下'
          });
        });
      for (const [index, scene] of data.scenes.entries()) {
        const entry = button(scene.title, () => show(index), 'room-tour-stop', [
          node(
            'span',
            'room-scene-icon',
            ctx.ui.icon(scene.kind === 'panorama' ? 'layers' : 'location', 17)
          ),
          node('span', '', [
            node('strong', '', scene.title),
            node(
              'small',
              '',
              pathName(scene.campusName, scene.buildingName, scene.floorLabel, scene.roomNumber)
            )
          ])
        ]);
        places.append(entry);
        controls.push(entry);
      }
      function show(index) {
        if (index < 0 || index >= data.scenes.length) return;
        active = index;
        positions[scopeKey] = data.scenes[index].id;
        const scene = data.scenes[index];
        const panoramic = scene.kind === 'panorama';
        const image = node('img', 'room-scene-photo');
        image.alt = scene.title;
        image.referrerPolicy = 'no-referrer';
        image.draggable = false;
        image.decoding = 'async';
        const frame = node('div', 'room-scene-media' + (panoramic ? ' panorama' : ''));
        if (panoramic) {
          frame.tabIndex = 0;
          frame.setAttribute('role', 'region');
          frame.setAttribute('aria-label', '全景原图，可左右拖动或使用方向键浏览');
          let anchor = null;
          frame.addEventListener('pointerdown', (e) => {
            if (e.button !== 0) return;
            anchor = { x: e.clientX, scroll: frame.scrollLeft };
            frame.setPointerCapture(e.pointerId);
          });
          frame.addEventListener('pointermove', (e) => {
            if (anchor) frame.scrollLeft = anchor.scroll - (e.clientX - anchor.x);
          });
          frame.addEventListener('lostpointercapture', () => {
            anchor = null;
          });
        }
        image.addEventListener(
          'error',
          () => {
            frame.replaceChildren(
              statusText('无法加载这张环境图片，请核对素材地址或访问权限。', true)
            );
          },
          { once: true }
        );
        frame.append(image);
        photo.replaceChildren(frame);
        image.src = scene.mediaUrl;
        text.replaceChildren(
          node('h2', '', scene.title),
          node(
            'p',
            '',
            pathName(scene.campusName, scene.buildingName, scene.floorLabel, scene.roomNumber)
          )
        );
        count.textContent =
          active + 1 + ' / ' + data.scenes.length + (panoramic ? ' · 可左右浏览全景' : '');
        prev.disabled = active === 0;
        next.disabled = active === data.scenes.length - 1;
        changed(controls, active);
      }
      container.replaceChildren(
        node('div', 'room-tour-grid', [
          node('section', 'room-tour-view', [
            text,
            photo,
            node('div', 'room-tour-move', [count, withdraw, prev, next])
          ]),
          node('aside', 'room-tour-index', [
            heading(
              ctx,
              'location',
              '导览视点',
              node('span', 'room-context', data.scenes.length + ' 站')
            ),
            places
          ])
        ])
      );
      show(Math.max(0, data.scenes.findIndex(scene => scene.id === positions[scopeKey])));
    } catch (error) {
      failure(ctx, container, error, load);
    }
  }
  load();
  return container;
}

export function openFacilityTour(ctx, scope = {}, label = '') {
  return ctx.detail('房间环境导览', tourViewer(ctx, scope, label));
}

function publicTourEntry() {
  const places = node('div', 'family-tour-places');
  for (const {id, name, place} of stops) {
    const preview = node('img');
    preview.src = '/assets/visit/' + id + '.webp';
    preview.width = 320;
    preview.height = 154;
    preview.decoding = 'async';
    preview.alt = '';
    const link = node('a', 'family-tour-stop', [preview,
      node('div', '', [node('strong', '', name), node('small', '', place)])]);
    link.href = '/roomtour?scene=' + id;
    link.setAttribute('aria-label', '在 3D 环境导览中查看' + name);
    places.append(link);
  }
  const start = node('a', 'btn btn-primary', '打开 3D 环境导览');
  start.href = '/roomtour';
  return node('section', 'fx-panel family-tour-demo', [
    node('header', 'fx-toolbar', [node('div', '', [
      node('h2', '', '3D 示范空间'), node('p', 'fx-muted', '选择起点，拖动或使用方向键参观设计示意。'),
    ]), start]),
    places,
  ]);
}

export function tourPage(ctx) {
  const registered = ctx.state.user.registeredCustomer;
  const manage = !registered && canAct(ctx, 'facility.setScene') && ctx.available('beds')
    ? ctx.ui.button('前往楼层平面图', () => ctx.go('beds', 'plan'), 'secondary', 'building')
    : null;
  const pageRoot = page(ctx, '环境导览', '', manage,
    !registered ? node('section', 'family-tour-published', [
      node('h2', '', '机构已发布视点'), tourViewer(ctx, {}),
    ]) : null,
    publicTourEntry(),
  );
  pageRoot.classList.add('family-tour-desk');
  return pageRoot;
}
