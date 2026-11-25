import { stops } from './features/tour-stops.js';
export { stops };

const palette = {
  oak: '#d7ac78', warm: '#eedcba', green: '#769381', deep: '#426c59', floor: '#e7dac5',
  light: '#f4eddf', glass: '#b3d7dc', frame: '#eee8db', dark: '#566559', accent: '#c17d4d',
};
const faces = [
  {corners:[0,1,2,3], normal:[0,0,-1], shade:.91},
  {corners:[4,7,6,5], normal:[0,0,1], shade:.96},
  {corners:[0,3,7,4], normal:[-1,0,0], shade:.87},
  {corners:[1,5,6,2], normal:[1,0,0], shade:.83},
  {corners:[3,2,6,7], normal:[0,1,0], shade:1},
  {corners:[0,4,5,1], normal:[0,-1,0], shade:.81},
];
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const dot = (a,b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const subtract = (a,b) => a.map((v, i) => v - b[i]);
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];

function cube(x,y,z,w,h,d,color, wall) {
  const xl = x-w/2, xr = x+w/2, yb = y-h/2, yt = y+h/2, zb = z-d/2, zf = z+d/2;
  return {
    x,y,z,color,wall,
    corners: [[xl,yb,zb],[xr,yb,zb],[xr,yt,zb],[xl,yt,zb],[xl,yb,zf],[xr,yb,zf],[xr,yt,zf],[xl,yt,zf]],
  };
}

function furniture(add) {
  return {
    plant(x,z,height=1.15) {
      add(x,.17,z,.43,.34,.43,palette.warm);
      add(x,height*.5,z,.09,height*.65,.09,palette.oak);
      add(x,height*.8,z,.54,height*.46,.58,palette.green);
      add(x-.18,height*.9,z-.12,.46,height*.48,.45,palette.deep);
      add(x+.16,height*1.01,z,.42,height*.48,.46,'#8eab84');
    },
    table(x,z,w=1.45,d=.85) {
      add(x,.70,z,w,.12,d,palette.oak);
      for (const dx of [-1,1]) for (const dz of [-1,1])
        add(x+dx*(w*.38),.31,z+dz*(d*.34),.09,.64,.09,palette.oak);
    },
    seat(x,z,w=1.2,color=palette.green,facing=1) {
      add(x,.18,z,w-.08,.36,.82,palette.oak);
      add(x,.42,z,w,.29,.86,color);
      add(x,.73,z-facing*.34,w,.47,.22,color);
      for (const sign of [-1,1]) add(x+sign*(w*.43),.62,z,.16,.32,.74,color);
    },
    bed(x,z) {
      add(x,.21,z,1.18,.38,2.25,palette.oak);
      add(x,.49,z,1.15,.18,2.18,'#fff6e2');
      add(x,.59,z+.39,1.14,.09,1.31,palette.green);
      add(x,.65,z-.77,.78,.14,.45,'#f7f2e7');
      add(x,.68,z-1.09,1.22,1.30,.12,palette.oak);
    },
    shelf(x,z) {
      add(x,.70,z,1.12,1.40,.48,palette.oak);
      for (const y of [.39,.81,1.14]) add(x,y,z+.25,.90,.21,.11,palette.warm);
    },
  };
}

function interior(add, tint) {
  add(0,-.12,0,8.15,.24,6.15,palette.floor);
  for (let x = -3.55; x < 4; x += .56) add(x,.005,0,.012,.012,5.98,'#d8c9b3');
  const back = 'back', left = 'left';
  add(0,1.46,-3.02,8.16,2.92,.18,tint,back);
  add(0,.12,-2.91,8,.24,.11,palette.oak,back);
  add(-3.96,1.46,0,.18,2.92,6.03,palette.light,left);
  add(-3.83,.09,0,.13,.18,5.88,palette.oak,left);
  for (let i = 0; i < 3; i++) {
    const x = -2.57 + 2.52*i;
    add(x,1.73,-2.90,1.91,1.55,.11,palette.frame,back);
    add(x,1.73,-2.83,1.72,1.35,.04,palette.glass,back);
    add(x,1.74,-2.78,.07,1.39,.06,palette.frame,back);
    add(x,1.74,-2.77,1.76,.06,.08,palette.frame,back);
  }
  add(0,.87,-2.78,7.48,.08,.13,palette.oak,back);
  add(-3.73,.87,0,.12,.08,5.4,palette.oak,left);
  for (const z of [-1.53, .78]) {
    add(-3.80,1.73,z,.15,1.52,1.86,palette.frame,left);
    add(-3.71,1.73,z,.04,1.29,1.65,palette.glass,left);
    add(-3.68,1.73,z,.04,1.34,.07,palette.frame,left);
  }
}

function models(id) {
  const items = [];
  const add = (...args) => items.push(cube(...args));
  const f = furniture(add);
  if (id === 'garden') {
    add(0,-.13,0,8.5,.26,6.15,'#89a57a');
    add(0,.025,1.29,8.12,.05,1.2,'#e3d1ac');
    add(.63,.055,-.35,1.07,.06,4.36,'#eedbbe');
    for (const [x,z] of [[-3,-1.95],[2.45,-1.9],[-2.7,2.15],[3.04,2.1]]) f.plant(x,z,2.1);
    f.seat(-1.88,-.95,1.53,palette.oak);
    f.seat(2.37,-.43,1.45,palette.oak,-1);
    f.table(-.6,-1.67,1.5,.78);
    for (const x of [-1.75,.54]) for (const z of [-2.72,-.68])
      add(x,1.2,z,.15,2.4,.15,palette.oak);
    add(-.59,2.45,-1.69,2.65,.17,2.43,palette.warm,'roof');
    return items;
  }
  interior(add, id === 'bedroom' ? '#e6e8d7' : '#edf0e3');
  if (id === 'reception') {
    f.seat(-2.42,-1.51,1.57,palette.green);
    f.seat(-2.42,.39,1.53,'#a6ad90',-1);
    f.table(-2.41,-.54,1.22,.68);
    add(1.10,.47,-1.45,3.10,.94,.92,palette.oak);
    add(1.10,1,-1.45,3.21,.14,1.03,palette.warm);
    add(1.46,1.18,-1.44,.58,.28,.11,palette.dark);
    f.plant(3.1,-2.45);
    f.plant(-3.38,-2.44);
    add(0,.024,1.86,2.0,.032,1.55,'#b5bf9c');
  } else if (id === 'activity') {
    for (const x of [-1.51,1.52]) {
      f.table(x,-.48,1.8,1.22);
      f.seat(x,-1.54,.65,palette.green);
      f.seat(x,.60,.65,'#b2a17c',-1);
    }
    f.shelf(-2.70,-2.35);
    f.plant(3.18,-2.43);
    add(2.76,.024,1.7,1.37,.034,1.31,'#b1c6a0');
    add(-1.50,.78,-.48,.28,.055,.22,palette.accent);
    add(1.65,.78,-.25,.33,.06,.28,'#b2c985');
  } else {
    for (const x of [-1.85,1.86]) {
      f.bed(x,-.73);
      add(x+.81,.28,-1.42,.44,.57,.52,palette.warm);
    }
    f.shelf(3.05,-2.21);
    add(.10,.025,1.83,2.53,.035,1.12,'#b7c6a2');
    f.seat(-2.76,1.46,.64,palette.green,-1);
    f.plant(-3.25,-2.51);
  }
  return items;
}

function tint(hex, factor) {
  const value = parseInt(hex.slice(1), 16);
  const channels = [value >> 16, (value >> 8) & 255, value & 255];
  return 'rgb(' + channels.map(value => Math.round(value*factor)).join(',') + ')';
}

export function tourModel(canvas, onDraw) {
  const context = canvas.getContext('2d');
  const initial = {yaw:.57, pitch:.51, zoom:1};
  let camera = {...initial}, items = models(stops[0].id), frame = 0;
  let drag;
  function requestDraw() {
    if (!frame && context) frame = requestAnimationFrame(draw);
  }
  function draw() {
    frame = 0;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const scale = Math.min(devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width*scale) || canvas.height !== Math.round(height*scale)) {
      canvas.width = Math.round(width*scale);
      canvas.height = Math.round(height*scale);
    }
    context.setTransform(scale, 0, 0, scale, 0, 0);
    context.clearRect(0, 0, width, height);
    const {yaw,pitch,zoom} = camera;
    const dist = 12.2 / zoom;
    const target = [0,.48,0];
    const eye = [Math.sin(yaw)*Math.cos(pitch)*dist, target[1]+Math.sin(pitch)*dist, Math.cos(yaw)*Math.cos(pitch)*dist];
    const forward = subtract(target, eye).map(v => v/dist);
    const right = [Math.cos(yaw),0,-Math.sin(yaw)];
    const up = cross(right, forward);
    const focal = Math.min(width*.94, height*1.22);
    function project(point) {
      const delta = subtract(point, eye);
      const depth = dot(delta, forward);
      return [width*.5 + focal*dot(delta,right)/depth, height*.51 - focal*dot(delta,up)/depth, depth];
    }
    const shape = [];
    for (const item of items) {
      if ((item.wall === 'back' && eye[2] < .1) || (item.wall === 'left' && eye[0] < .15) ||
          (item.wall === 'roof' && pitch > .67)) continue;
      const corners = item.corners.map(project);
      const toward = subtract(eye, [item.x,item.y,item.z]);
      for (const part of faces) {
        if (dot(toward, part.normal) <= 0) continue;
        const points = part.corners.map(index => corners[index]);
        if (points.some(point => point[2] <= .12)) continue;
        shape.push({
          points,
          foundation: item.y <= .07,
          depth: points.reduce((sum, point) => sum + point[2], 0)*.25,
          fill: tint(item.color, part.shade),
        });
      }
    }
    shape.sort((a,b) => Number(b.foundation)-Number(a.foundation) || b.depth-a.depth);
    context.lineWidth = .7;
    context.strokeStyle = '#243f3332';
    context.lineJoin = 'round';
    for (const {points,fill} of shape) {
      context.beginPath();
      for (const [x,y] of points) context.lineTo(x,y);
      context.closePath();
      context.fillStyle = fill;
      context.fill();
      context.stroke();
    }
    onDraw(project);
  }
  function turn(horizontal, vertical=0) {
    camera.yaw += horizontal;
    camera.pitch = clamp(camera.pitch + vertical, .22, 1.16);
    requestDraw();
  }
  function zoom(amount) {
    camera.zoom = clamp(camera.zoom+amount, .70, 1.48);
    requestDraw();
  }
  canvas.addEventListener('pointerdown', event => {
    if (event.button !== 0 || drag) return;
    canvas.setPointerCapture(event.pointerId);
    drag = {id:event.pointerId, x:event.clientX, y:event.clientY};
    canvas.classList.add('dragging');
  });
  canvas.addEventListener('pointermove', event => {
    if (drag?.id !== event.pointerId) return;
    turn((event.clientX-drag.x)*.014, (event.clientY-drag.y)*.009);
    drag.x = event.clientX;
    drag.y = event.clientY;
  });
  canvas.addEventListener('lostpointercapture', () => {
    drag = undefined;
    canvas.classList.remove('dragging');
  });
  canvas.addEventListener('keydown', event => {
    const actions = {
      ArrowLeft: () => turn(-.17), ArrowRight: () => turn(.17),
      ArrowUp: () => turn(0,.11), ArrowDown: () => turn(0,-.11),
      '+': () => zoom(.12), '=': () => zoom(.12), '-': () => zoom(-.12),
    };
    if (!actions[event.key]) return;
    event.preventDefault();
    actions[event.key]();
  });
  new ResizeObserver(requestDraw).observe(canvas);
  return {
    supported: Boolean(context), turn, zoom,
    reset() { camera = {...initial}; requestDraw(); },
    show(id) { items = models(id); camera = {...initial}; requestDraw(); },
  };
}
