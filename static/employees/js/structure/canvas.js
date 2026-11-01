// The canvas view of the company structure page, a workspace in the manner of n8n: cards joined by
// wires on an endless grid. Drag the background to look around, and a card to arrange it. Dropped on
// a place it can go, a card opens the move for that place. A branch's "+" draws a wire to a
// department to place it there too, and a department's own wire end pulls it to another branch.
import { el, icon } from "./dom.js";
import { drawCard } from "./card.js";
import { bounds, buildGraph, flatten, inPoint, layOut, outPoint, showMore, wirePath } from "./graph.js";
import { dropAllowed, dropOn, openAddDepartment, openRemoveDepartment, peopleToCarry } from "./moves.js";
import { changed, select, state, toggleChecked, toggleOpen, words } from "./store.js";

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 1.5;
const ZOOM_STEP = 1.2;
const READABLE_ZOOM = 0.85;
const GRID = 24;
const SPARSE_GRID_BELOW = 0.5;
const DRAG_FROM = 4; // pixels before a press becomes a drag
const EDGE_MARGIN = 32;
const SVG = "http://www.w3.org/2000/svg";

const viewport = document.querySelector("[data-canvas]");
const world = viewport.querySelector("[data-world]");
const wiresBox = viewport.querySelector("[data-wires]");
const nodesBox = viewport.querySelector("[data-nodes]");
const cut = viewport.querySelector("[data-cut]");
const inspector = document.querySelector("[data-inspector]");
const zoomLabel = document.querySelector("[data-zoom-label]");

const rtl = document.documentElement.dir === "rtl";
const storageKey = `structure.layout.${rtl ? "rtl" : "ltr"}`;

const camera = { x: 0, y: 0, zoom: 1 };
const offsets = readOffsets();
const cards = new Map(); // key → its card
const wires = new Map(); // key → the wire into that node
let root = null;
let nodes = [];
let byKey = new Map();
let cutting = null; // the node whose wire the cut button is on
let ignoreClick = false; // the click that ends a drag

// --- what was arranged (this browser only; "Tidy up" forgets it) ----------------------------------

function readOffsets() {
  try {
    return new Map(JSON.parse(localStorage.getItem(storageKey)) ?? []);
  } catch {
    return new Map();
  }
}

function saveOffsets() {
  try {
    localStorage.setItem(storageKey, JSON.stringify([...offsets]));
  } catch {
    // the arrangement just lasts until the page closes
  }
}

// --- the camera -------------------------------------------------------------------------------

function applyCamera() {
  world.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})`;
  const grid = GRID * camera.zoom * (camera.zoom < SPARSE_GRID_BELOW ? 2 : 1);
  viewport.style.backgroundSize = `${grid}px ${grid}px`;
  viewport.style.backgroundPosition = `${camera.x}px ${camera.y}px`;
  zoomLabel.textContent = `${Math.round(camera.zoom * 100)}%`;
}

const clampZoom = (zoom) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));

function zoomAt(x, y, zoom) {
  const next = clampZoom(zoom);
  camera.x = x - ((x - camera.x) * next) / camera.zoom;
  camera.y = y - ((y - camera.y) * next) / camera.zoom;
  camera.zoom = next;
  applyCamera();
}

function zoomBy(factor) {
  zoomAt(viewport.clientWidth / 2, viewport.clientHeight / 2, camera.zoom * factor);
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

function fit() {
  if (!nodes.length || !viewport.clientWidth) return;
  const area = freeArea();
  const box = bounds(nodes);
  const width = box.right - box.left;
  const height = box.bottom - box.top;
  camera.zoom = clampZoom(Math.min(1, (area.right - area.left) / width, (area.bottom - area.top) / height));
  camera.x = (area.left + area.right - width * camera.zoom) / 2 - box.left * camera.zoom;
  camera.y = (area.top + area.bottom - height * camera.zoom) / 2 - box.top * camera.zoom;
  applyCamera();
}

function centerOn(item) {
  const area = freeArea();
  camera.zoom = Math.max(camera.zoom, READABLE_ZOOM);
  camera.x = (area.left + area.right) / 2 - (item.x + item.width / 2) * camera.zoom;
  camera.y = (area.top + area.bottom) / 2 - (item.y + item.height / 2) * camera.zoom;
  applyCamera();
}

function bringIntoView(item) {
  const area = freeArea();
  const left = item.x * camera.zoom + camera.x;
  const top = item.y * camera.zoom + camera.y;
  const right = left + item.width * camera.zoom;
  const bottom = top + item.height * camera.zoom;
  if (left < area.left) camera.x += area.left - left;
  else if (right > area.right) camera.x -= right - area.right;
  if (top < area.top) camera.y += area.top - top;
  else if (bottom > area.bottom) camera.y -= bottom - area.bottom;
  applyCamera();
}

// A view to start from: all of it if that can be read, or the company in the middle if not.
function overview() {
  fit();
  if (camera.zoom < READABLE_ZOOM) centerOn(root);
}

// --- drawing ----------------------------------------------------------------------------------

function positionNodes() {
  layOut(root, offsets, rtl);
  nodes.forEach((item) => {
    const card = cards.get(item.key);
    card.style.transform = `translate(${item.x}px, ${item.y}px)`;
    card.style.width = `${item.width}px`;
    card.style.height = `${item.height}px`;
    if (!item.parent) return;
    const path = wirePath(outPoint(item.parent, rtl), inPoint(item, rtl), rtl);
    wires.get(item.key).forEach((line) => line.setAttribute("d", path));
  });
}

function canCut(item) {
  return item.kind === "department" && item.branch.can_manage_departments && item.department.branch_ids.length > 1;
}

function drawWires(lit) {
  wires.clear();
  const lines = [];
  nodes.filter((item) => item.parent).forEach((item) => {
    const line = document.createElementNS(SVG, "path");
    line.setAttribute("class", `flow-wire${lit.has(item.key) ? " is-lit" : ""}`);
    wires.set(item.key, [line]);
    lines.push(line);
    if (!canCut(item)) return;
    const reach = document.createElementNS(SVG, "path");
    reach.setAttribute("class", "flow-wire-reach");
    reach.dataset.wire = item.key;
    wires.get(item.key).push(reach);
    lines.push(reach);
  });
  wiresBox.replaceChildren(...lines);
}

// The selected node and the way back to the company.
function pathToSelected() {
  const lit = new Set();
  for (let item = byKey.get(state.selected?.key); item; item = item.parent) lit.add(item.key);
  return lit;
}

function isTwin(item) {
  const selected = state.selected;
  return selected?.kind === "department" && item.kind === "department" && item.key !== selected.key
    && item.department.id === selected.department.id;
}

function setTabStop() {
  const current = cards.get(state.selected?.key) ?? cards.get(root.key);
  current.tabIndex = 0;
}

export function drawCanvas({ keep, reveal, center, fit: fitAll } = {}) {
  const kept = byKey.get(keep);
  const before = kept && { x: kept.x, y: kept.y };
  const focused = viewport.contains(document.activeElement) ? document.activeElement.closest(".flow-node")?.dataset.key : null;

  root = buildGraph();
  layOut(root, offsets, rtl);
  nodes = flatten(root);
  byKey = new Map(nodes.map((item) => [item.key, item]));
  cards.clear();
  nodes.forEach((item) => cards.set(item.key, drawCard(item, { selected: state.selected?.key === item.key, twin: isTwin(item) })));
  nodesBox.replaceChildren(...cards.values());
  drawWires(pathToSelected());
  positionNodes();
  cut.hidden = true;
  setTabStop();

  const anchor = byKey.get(keep);
  if (before && anchor) {
    camera.x += (before.x - anchor.x) * camera.zoom;
    camera.y += (before.y - anchor.y) * camera.zoom;
    applyCamera();
  }
  if (fitAll) overview();
  const target = byKey.get(reveal);
  if (target) (center ? centerOn : bringIntoView)(target);
  cards.get(focused)?.focus({ preventScroll: true });
}

// --- pressing a card --------------------------------------------------------------------------

function toggleNode(item) {
  toggleOpen(item.key, item.branch, item.kind === "branch" ? undefined : item.department ?? null);
}

function activate(item, event) {
  if (item.kind === "more") {
    showMore(item.group);
    changed({ keep: item.group });
  } else if (item.kind === "none") toggleNode(item);
  else if (item.kind === "company") select(null);
  else if (item.kind === "employee") {
    if (item.canCarry && (event.shiftKey || event.ctrlKey || event.metaKey)) {
      toggleChecked(item.person, !state.checked.has(item.person.id));
    } else {
      select({ key: item.key, kind: "employee", branch: item.branch, person: item.person, department: item.departmentId });
    }
  } else {
    select({ key: item.key, kind: item.kind, branch: item.branch, department: item.department });
    if (!item.open) toggleNode(item);
  }
}

nodesBox.addEventListener("click", (event) => {
  const item = byKey.get(event.target.closest(".flow-node")?.dataset.key);
  if (!item || ignoreClick || item.kind === "hint") return;
  if (event.target.closest('[data-port="out"]')) openAddDepartment(item.branch);
  else if (event.target.matches("[data-check]")) toggleChecked(item.person, event.target.checked);
  else if (event.target.closest("[data-toggle]")) toggleNode(item);
  else activate(item, event);
});

// --- gestures: each is an object with from, and optional begin, move and end -----------------------

let gesture = null;
const pressed = new Map(); // pointer → where it is, for pinching
let pinch = null;

function worldPoint(event) {
  const box = viewport.getBoundingClientRect();
  return { x: (event.clientX - box.left - camera.x) / camera.zoom, y: (event.clientY - box.top - camera.y) / camera.zoom };
}

function targetAt(targets, point) {
  return targets.find((item) => point.x >= item.x && point.x <= item.x + item.width
    && point.y >= item.y && point.y <= item.y + item.height);
}

function panning(from) {
  const start = { x: camera.x, y: camera.y };
  return {
    from,
    begin: () => viewport.classList.add("is-panning"),
    move(dx, dy) {
      camera.x = start.x + dx;
      camera.y = start.y + dy;
      applyCamera();
    },
    end(moved) {
      viewport.classList.remove("is-panning");
      if (!moved && state.selected) select(null);
    },
  };
}

// Marks the places something can land, and follows the pointer over them.
function landing(carried) {
  const targets = nodes.filter((item) => dropAllowed(carried, item));
  let over = null;
  return {
    show() {
      viewport.classList.add("is-carrying");
      targets.forEach((item) => cards.get(item.key).classList.add("can-drop"));
    },
    follow(point) {
      const next = targetAt(targets, point) ?? null;
      if (next === over) return;
      if (over) cards.get(over.key).classList.remove("is-drop");
      if (next) cards.get(next.key).classList.add("is-drop");
      over = next;
    },
    finish() {
      viewport.classList.remove("is-carrying");
      if (over) dropOn(carried, over);
    },
    get target() { return over; },
  };
}

function whatIsCarried(item) {
  if (!item.canCarry) return null;
  return item.kind === "employee" ? peopleToCarry(item.person)
    : { kind: "department", branch: item.branch, department: item.department };
}

function carrying(from, item) {
  const before = offsets.get(item.key);
  const start = before ?? { x: 0, y: 0 };
  const carried = whatIsCarried(item);
  const places = landing(carried);
  return {
    from,
    begin() {
      places.show();
      const card = cards.get(item.key);
      card.classList.add("is-carried");
      if (carried?.kind === "people" && carried.people.length > 1) {
        card.append(el("span", "flow-carried num", String(carried.people.length)));
      }
    },
    move(dx, dy, event) {
      offsets.set(item.key, { x: start.x + dx / camera.zoom, y: start.y + dy / camera.zoom });
      positionNodes();
      places.follow(worldPoint(event));
    },
    end(moved) {
      if (!moved) return;
      ignoreClick = true;
      if (places.target || item.kind === "employee") { // it goes back: the move decides where it ends up
        if (before) offsets.set(item.key, before);
        else offsets.delete(item.key);
      }
      saveOffsets();
      drawCanvas();
      places.finish();
    },
  };
}

function wiring(from, start, carried, lifted) {
  const ghost = document.createElementNS(SVG, "path");
  ghost.setAttribute("class", "flow-wire is-lit is-ghost");
  const places = landing(carried);
  return {
    from,
    begin() {
      places.show();
      wiresBox.append(ghost);
      wires.get(lifted?.key)?.[0].classList.add("is-lifted");
    },
    move(dx, dy, event) {
      const point = worldPoint(event);
      ghost.setAttribute("d", wirePath(start, point, rtl));
      places.follow(point);
    },
    end(moved) {
      if (!moved) return;
      ignoreClick = true;
      drawCanvas();
      places.finish();
    },
  };
}

function gestureFor(event, from) {
  if (event.button === 1) return panning(from);
  const item = byKey.get(event.target.closest(".flow-node")?.dataset.key);
  if (!item || item.kind === "hint") return panning(from);
  if (event.target.closest("[data-toggle],[data-check]") || item.kind === "more") return null;
  const port = event.target.closest("[data-port]")?.dataset.port;
  if (port === "out") return wiring(from, outPoint(item, rtl), { kind: "connect", branch: item.branch });
  if (port === "in") return wiring(from, outPoint(item.parent, rtl), whatIsCarried(item), item);
  return item.kind === "employee" && !item.canCarry ? null : carrying(from, item);
}

viewport.addEventListener("pointerdown", (event) => {
  if (event.button > 1 || event.target.closest("[data-cut]")) return;
  ignoreClick = false;
  const from = { x: event.clientX, y: event.clientY };
  pressed.set(event.pointerId, from);
  if (pressed.size === 2) {
    gesture = null; // a second finger turns the press into a pinch
    const [a, b] = [...pressed.values()];
    pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y), zoom: camera.zoom };
    return;
  }
  gesture = gestureFor(event, from);
});

function pinching() {
  const [a, b] = [...pressed.values()];
  const box = viewport.getBoundingClientRect();
  zoomAt((a.x + b.x) / 2 - box.left, (a.y + b.y) / 2 - box.top, pinch.zoom * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.distance));
}

window.addEventListener("pointermove", (event) => {
  if (pressed.has(event.pointerId)) pressed.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pinch && pressed.size === 2) {
    pinching();
    return;
  }
  if (!gesture) return;
  const dx = event.clientX - gesture.from.x;
  const dy = event.clientY - gesture.from.y;
  if (!gesture.moved) {
    if (Math.hypot(dx, dy) < DRAG_FROM) return;
    gesture.moved = true;
    gesture.begin?.();
  }
  gesture.move(dx, dy, event);
});

function release(event) {
  pressed.delete(event.pointerId);
  if (pressed.size < 2) pinch = null;
  if (!gesture) return;
  const finished = gesture;
  gesture = null;
  finished.end?.(finished.moved);
}

window.addEventListener("pointerup", release);
window.addEventListener("pointercancel", release);

viewport.addEventListener("wheel", (event) => {
  event.preventDefault();
  const lines = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : 1;
  if (event.ctrlKey || event.metaKey) {
    const box = viewport.getBoundingClientRect();
    zoomAt(event.clientX - box.left, event.clientY - box.top, camera.zoom * Math.exp(-event.deltaY * lines * 0.002));
    return;
  }
  camera.x -= (event.shiftKey ? event.deltaY : event.deltaX) * lines;
  camera.y -= event.shiftKey ? 0 : event.deltaY * lines;
  applyCamera();
}, { passive: false });

// --- the button on a wire: this department stops being in this branch -----------------------------

wiresBox.addEventListener("pointerover", (event) => {
  const item = byKey.get(event.target.dataset?.wire);
  if (!item) return;
  const from = outPoint(item.parent, rtl);
  const to = inPoint(item, rtl);
  cutting = item;
  cut.style.transform = `translate(${(from.x + to.x) / 2}px, ${(from.y + to.y) / 2}px) translate(-50%, -50%)`;
  cut.hidden = false;
});

wiresBox.addEventListener("pointerout", (event) => {
  if (!cut.contains(event.relatedTarget)) cut.hidden = true;
});

cut.addEventListener("pointerleave", () => { cut.hidden = true; });
cut.addEventListener("click", () => {
  cut.hidden = true;
  openRemoveDepartment(cutting.branch, cutting.department);
});
cut.title = words.remove_department;
cut.setAttribute("aria-label", words.remove_department);
cut.append(icon("unlink"));

// --- the keyboard (WAI-ARIA tree, with the zoom keys) ----------------------------------------------

function goTo(item, from) {
  if (!item) return;
  cards.get(from.key).tabIndex = -1;
  cards.get(item.key).tabIndex = 0;
  cards.get(item.key).focus({ preventScroll: true });
  bringIntoView(item);
}

function neighbour(item, step) {
  const column = nodes.filter((other) => other.depth === item.depth && other.kind !== "hint").sort((a, b) => a.y - b.y);
  return column[column.indexOf(item) + step];
}

nodesBox.addEventListener("keydown", (event) => {
  const item = byKey.get(event.target.closest(".flow-node")?.dataset.key);
  if (!item || !["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Enter", " ", "Home"].includes(event.key)) return;
  event.preventDefault();
  const inward = rtl ? "ArrowLeft" : "ArrowRight";
  const outward = rtl ? "ArrowRight" : "ArrowLeft";
  if (event.key === "ArrowDown") goTo(neighbour(item, 1), item);
  else if (event.key === "ArrowUp") goTo(neighbour(item, -1), item);
  else if (event.key === "Home") goTo(root, item);
  else if (event.key === inward) {
    if (item.open === false) toggleNode(item);
    else goTo(item.children.find((child) => child.kind !== "hint"), item);
  } else if (event.key === outward) {
    if (item.open) toggleNode(item);
    else goTo(item.parent, item);
  } else if (event.key === " " && item.kind === "employee" && item.canCarry) {
    toggleChecked(item.person, !state.checked.has(item.person.id));
  } else activate(item, event);
});

viewport.addEventListener("keydown", (event) => {
  if (event.key === "+" || event.key === "=") zoomBy(ZOOM_STEP);
  else if (event.key === "-") zoomBy(1 / ZOOM_STEP);
  else if (event.key === "0") fit();
});

// --- the controls -----------------------------------------------------------------------------

document.querySelector("[data-zoom-in]").addEventListener("click", () => zoomBy(ZOOM_STEP));
document.querySelector("[data-zoom-out]").addEventListener("click", () => zoomBy(1 / ZOOM_STEP));
document.querySelector("[data-zoom-fit]").addEventListener("click", fit);
document.querySelector("[data-tidy]").addEventListener("click", () => {
  offsets.clear();
  saveOffsets();
  drawCanvas({ fit: true });
});
