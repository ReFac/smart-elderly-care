const svgNamespace = 'http://www.w3.org/2000/svg';

export const roomTypeLabel = count =>
  ['未配置床位', '单人间', '双人间', '三人间'][count] || count + ' 人间';

function svgElement(name, attributes) {
  const element = document.createElementNS(svgNamespace, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

export function roomVector(viewBox = [0, 0, 100, 100]) {
  return svgElement('svg', {
    class: 'room-vector',
    viewBox: viewBox.join(' '),
    preserveAspectRatio: 'none',
    'aria-hidden': 'true',
    focusable: 'false',
  });
}

export function drawRooms(svg, rooms, { labels = false } = {}) {
  const shapes = rooms.flatMap(({ x, y, w, h, roomId, number, occupiedCount }) => {
    if (![x, y, w, h].every(Number.isFinite) || w <= 0 || h <= 0) return [];
    const rectangle = svgElement('rect', {
      x, y, width: w, height: h, rx: .35, 'data-room-id': roomId,
      class: occupiedCount > 0 ? 'occupied' : '',
      'vector-effect': 'non-scaling-stroke',
    });
    if (!labels) return [rectangle];
    const name = svgElement('text', {
      x: x + w / 2, y: y + h / 2, 'text-anchor': 'middle', 'dominant-baseline': 'middle',
    });
    name.textContent = number;
    return [rectangle, name];
  });
  svg.replaceChildren(...shapes);
}
