// The small map of the canvas: where everything is, what is on screen, and a quick way to get there.
import { bounds } from "./graph.js";
import { camera, onCameraMove, panTo } from "./camera.js";

const WIDTH = 176;
const HEIGHT = 112;
const PADDING = 8;

const map = document.querySelector("[data-map]");
const cardsPath = map.querySelector("[data-map-cards]");
const selectedPath = map.querySelector("[data-map-selected]");
const frame = map.querySelector("[data-map-frame]");
const viewport = document.querySelector("[data-canvas]");

let scale = 1;
let originX = 0;
let originY = 0;

const outline = (item) => {
  const x = item.x * scale + originX;
  const y = item.y * scale + originY;
  return `M${x} ${y}h${item.width * scale}v${item.height * scale}h${-item.width * scale}z`;
};

function drawFrame() {
  frame.setAttribute("x", -camera.x / camera.zoom * scale + originX);
  frame.setAttribute("y", -camera.y / camera.zoom * scale + originY);
  frame.setAttribute("width", viewport.clientWidth / camera.zoom * scale);
  frame.setAttribute("height", viewport.clientHeight / camera.zoom * scale);
}

export function drawMap(nodes, selectedKey) {
  if (!nodes.length) return;
  const box = bounds(nodes);
  const width = box.right - box.left;
  const height = box.bottom - box.top;
  scale = Math.min((WIDTH - PADDING * 2) / width, (HEIGHT - PADDING * 2) / height);
  originX = (WIDTH - width * scale) / 2 - box.left * scale;
  originY = (HEIGHT - height * scale) / 2 - box.top * scale;
  cardsPath.setAttribute("d", nodes.map(outline).join(""));
  selectedPath.setAttribute("d", nodes.filter((item) => item.key === selectedKey).map(outline).join(""));
  drawFrame();
}

function lookAt(event) {
  const box = map.getBoundingClientRect();
  const x = (event.clientX - box.left - originX) / scale;
  const y = (event.clientY - box.top - originY) / scale;
  panTo(viewport.clientWidth / 2 - x * camera.zoom, viewport.clientHeight / 2 - y * camera.zoom);
}

map.addEventListener("pointerdown", (event) => {
  map.setPointerCapture(event.pointerId);
  lookAt(event);
});

map.addEventListener("pointermove", (event) => {
  if (map.hasPointerCapture(event.pointerId)) lookAt(event);
});

onCameraMove(drawFrame);
