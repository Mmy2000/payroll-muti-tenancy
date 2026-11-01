// What part of the canvas is on screen. A jump glides there; dragging and scrolling follow at once.
import { bounds } from "./graph.js";
import { between, tween } from "./motion.js";

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 1.5;
const ZOOM_STEP = 1.2;
const READABLE_ZOOM = 0.85;
const GRID = 24;
const SPARSE_GRID_BELOW = 0.5;
const EDGE_MARGIN = 32;
const GLIDE = 280;

const viewport = document.querySelector("[data-canvas]");
const world = viewport.querySelector("[data-world]");
const inspector = document.querySelector("[data-inspector]");
const zoomLabel = document.querySelector("[data-zoom-label]");

export const rtl = document.documentElement.dir === "rtl";
export const camera = { x: 0, y: 0, zoom: 1 };

let onMove = () => {};
let glide = null; // {from, to, run}

export function onCameraMove(callback) {
  onMove = callback;
}

function apply() {
  world.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})`;
  const grid = GRID * camera.zoom * (camera.zoom < SPARSE_GRID_BELOW ? 2 : 1);
  viewport.style.backgroundSize = `${grid}px ${grid}px`;
  viewport.style.backgroundPosition = `${camera.x}px ${camera.y}px`;
  zoomLabel.textContent = `${Math.round(camera.zoom * 100)}%`;
  onMove();
}

function stopGlide() {
  glide?.run.cancel();
  glide = null;
}

function go(to, animate = true) {
  stopGlide();
  if (!animate) {
    Object.assign(camera, to);
    apply();
    return;
  }
  const trip = { from: { ...camera }, to };
  trip.run = tween(GLIDE, (t) => {
    camera.x = between(trip.from.x, trip.to.x, t);
    camera.y = between(trip.from.y, trip.to.y, t);
    camera.zoom = between(trip.from.zoom, trip.to.zoom, t);
    apply();
  }, () => { glide = null; });
  glide = trip;
}

export function panTo(x, y) {
  stopGlide();
  Object.assign(camera, { x, y });
  apply();
}

export function panBy(dx, dy) {
  panTo(camera.x + dx, camera.y + dy);
}

// The page moved under the camera: everything on screen stays put, even in the middle of a glide.
export function shift(dx, dy) {
  camera.x += dx;
  camera.y += dy;
  if (glide) {
    [glide.from, glide.to].forEach((end) => {
      end.x += dx;
      end.y += dy;
    });
  }
  apply();
}

const clampZoom = (zoom) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));

function zoomedAt(x, y, zoom) {
  const next = clampZoom(zoom);
  return { x: x - ((x - camera.x) * next) / camera.zoom, y: y - ((y - camera.y) * next) / camera.zoom, zoom: next };
}

export function zoomAt(x, y, zoom) {
  go(zoomedAt(x, y, zoom), false);
}

export function zoomIn(steps = 1) {
  go(zoomedAt(viewport.clientWidth / 2, viewport.clientHeight / 2, camera.zoom * ZOOM_STEP ** steps));
}

// The part of the canvas the details panel doesn't cover.
function freeArea() {
  const area = { left: EDGE_MARGIN, top: EDGE_MARGIN, right: viewport.clientWidth - EDGE_MARGIN, bottom: viewport.clientHeight - EDGE_MARGIN };
  if (!inspector.offsetWidth) return area;
  if (inspector.offsetWidth > viewport.clientWidth * 0.7) area.bottom -= inspector.offsetHeight;
  else if (rtl) area.left += inspector.offsetWidth;
  else area.right -= inspector.offsetWidth;
  return area;
}

function fitted(nodes) {
  const area = freeArea();
  const box = bounds(nodes);
  const width = box.right - box.left;
  const height = box.bottom - box.top;
  const zoom = clampZoom(Math.min(1, (area.right - area.left) / width, (area.bottom - area.top) / height));
  return {
    zoom, x: (area.left + area.right - width * zoom) / 2 - box.left * zoom,
    y: (area.top + area.bottom - height * zoom) / 2 - box.top * zoom,
  };
}

function centered(item, zoom) {
  const area = freeArea();
  return {
    zoom, x: (area.left + area.right) / 2 - (item.x + item.width / 2) * zoom,
    y: (area.top + area.bottom) / 2 - (item.y + item.height / 2) * zoom,
  };
}

export function fit(nodes) {
  if (nodes.length && viewport.clientWidth) go(fitted(nodes));
}

export function centerOn(item) {
  go(centered(item, Math.max(camera.zoom, READABLE_ZOOM)));
}

export function bringIntoView(item) {
  const area = freeArea();
  const left = item.x * camera.zoom + camera.x;
  const top = item.y * camera.zoom + camera.y;
  const right = left + item.width * camera.zoom;
  const bottom = top + item.height * camera.zoom;
  let { x, y } = camera;
  if (left < area.left) x += area.left - left;
  else if (right > area.right) x -= right - area.right;
  if (top < area.top) y += area.top - top;
  else if (bottom > area.bottom) y -= bottom - area.bottom;
  if (x !== camera.x || y !== camera.y) go({ x, y, zoom: camera.zoom });
}

// A view to start from: all of it if that can be read, or the company in the middle if not.
export function overview(nodes, root, { animate = true } = {}) {
  if (!viewport.clientWidth) return;
  const whole = fitted(nodes);
  go(whole.zoom < READABLE_ZOOM ? centered(root, READABLE_ZOOM) : whole, animate);
}
