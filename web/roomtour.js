import { stops, tourModel } from './roomtour-model.js';
import { publicPage } from './public-site.js';
import { inviteVisitor } from './roomtour-invite.js';

publicPage('3D 环境导览');

const byId = new Map(stops.map(stop => [stop.id, stop]));
const canvas = document.querySelector('#tour-canvas');
const stage = document.querySelector('#tour-stage');
const hotspots = document.querySelector('#tour-hotspots');
const navigation = document.querySelector('#tour-stops');
const scenes = new Map();
let active, points = [];

function viewButton(title, className, activate) {
  const button = document.createElement('button');
  button.className = className;
  button.type = 'button';
  button.textContent = title;
  button.addEventListener('click', activate);
  return button;
}

const model = tourModel(canvas, project => {
  for (const {point, button} of points) {
    const [x,y,depth] = project(point);
    button.hidden = depth <= 0 || x < 60 || y < 70 || x > stage.clientWidth-60 || y > stage.clientHeight-58;
    if (!button.hidden) {
      button.style.left = x + 'px';
      button.style.top = y + 'px';
    }
  }
});

function visitRoom(stop) {
  active = stop;
  for (const [id, button] of scenes) button.setAttribute('aria-pressed', String(id === stop.id));
  document.querySelector('#scene-name').textContent = stop.name;
  document.querySelector('#scene-place').textContent = stop.place;
  document.querySelector('#scene-description').textContent = stop.description;
  points = model.supported ? stop.links.map(({id, point}) => ({
    point, button: viewButton(byId.get(id).name, 'tour-hotspot', () => {
      visitRoom(byId.get(id));
      scenes.get(id).focus();
    }),
  })) : [];
  for (const {button} of points) button.hidden = true;
  hotspots.replaceChildren(...points.map(({button}) => button));
  model.show(stop.id);
  const url = new URL(location.href);
  if (active.id !== stops[0].id || url.searchParams.has('scene')) {
    url.searchParams.set('scene', active.id);
    history.replaceState(history.state, '', url);
  }
}

for (const stop of stops) {
  const item = viewButton(stop.name, 'tour-stop', () => visitRoom(stop));
  const location = document.createElement('small');
  location.textContent = stop.place;
  const preview = document.createElement('img');
  preview.src = '/assets/visit/' + stop.id + '.webp';
  preview.alt = '';
  preview.width = 74;
  preview.height = 46;
  const label = document.createElement('span');
  label.append(stop.name, location);
  item.replaceChildren(preview, label);
  scenes.set(stop.id, item);
  navigation.append(item);
}
visitRoom(byId.get(new URLSearchParams(location.search).get('scene')) || stops[0]);
if (!model.supported) {
  document.querySelector('#tour-empty').hidden = false;
  document.querySelector('.tour-pad').hidden = true;
}
const turns = {left:() => model.turn(-.31), right:() => model.turn(.31), in:() => model.zoom(.16),
  out:() => model.zoom(-.16), reset:() => model.reset()};
for (const control of document.querySelectorAll('[data-tour-turn]'))
  control.addEventListener('click', turns[control.dataset.tourTurn]);

inviteVisitor(stage);
