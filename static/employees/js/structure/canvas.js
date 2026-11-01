// The canvas view of the company structure page, a workspace in the manner of n8n: cards joined by
// wires on an endless grid. Drag the background to look around, and a card to arrange it. Dropped on
// a place it can go, a card opens the move for that place. A branch's "+" draws a wire to a
// department to place it there too, and a department's own wire end pulls it to another branch.
import { bringIntoView, camera, centerOn, fit, overview, panBy, panTo, rtl, shift, zoomAt, zoomIn } from "./camera.js";
import { el, icon } from "./dom.js";
import { drawCard } from "./card.js";
import { recordArrangement } from "./history.js";
import { buildGraph, flatten, inPoint, layOut, outPoint, showMore, wirePath } from "./graph.js";
import { drawMap } from "./minimap.js";
import { between, tween } from "./motion.js";
import { dropAllowed, dropOn, openAddDepartment, openRemoveDepartment, peopleToCarry } from "./moves.js";
import { changed, select, state, toggleChecked, toggleOpen, words } from "./store.js";

const DRAG_FROM = 4; // pixels before a press becomes a drag
const SETTLE = 240; // how long cards take to reach their new places
const SETTLE_AT_MOST = 400; // with more cards than this they go straight there
const EDGE_ZONE = 48; // dragging this close to the edge moves the canvas
const EDGE_SPEED = 12;
const SVG = "http://www.w3.org/2000/svg";

const viewport = document.querySelector("[data-canvas]");
const wiresBox = viewport.querySelector("[data-wires]");
const nodesBox = viewport.querySelector("[data-nodes]");
const cut = viewport.querySelector("[data-cut]");

const storageKey = `structure.layout.${rtl ? "rtl" : "ltr"}`;

const offsets = readOffsets();
const cards = new Map(); // key → its card
const wires = new Map(); // key → the wire into that node
const shown = new Map(); // key → where its card is right now
let root = null;
let nodes = [];
let byKey = new Map();
let settling = null; // cards on their way to new places
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

// `before` and the cards as they are now become one step of undo.
function arranged(before) {
  const after = new Map(offsets);
  const putBack = (spots) => () => {
    offsets.clear();
    spots.forEach((spot, key) => offsets.set(key, spot));
    saveOffsets();
    changed();
  };
  recordArrangement({ undo: putBack(before), redo: putBack(after) });
}

// --- drawing ----------------------------------------------------------------------------------

const placed = (item) => ({ ...shown.get(item.key), width: item.width, height: item.height });

// Puts every card where `spot` says, and the wires between them.
function placeCards(spot) {
  nodes.forEach((item) => {
    const at = spot(item);
    shown.set(item.key, at);
    cards.get(item.key).style.transform = `translate(${at.x}px, ${at.y}px)`;
  });
  nodes.filter((item) => item.parent).forEach((item) => {
    const path = wirePath(outPoint(placed(item.parent), rtl), inPoint(placed(item), rtl), rtl);
    wires.get(item.key).forEach((line) => line.setAttribute("d", path));
  });
}

function stopSettling() {
  settling?.stop();
  settling = null;
}

// The cards as they stand, while one is being dragged.
function positionNodes() {
  stopSettling();
  layOut(root, offsets, rtl);
  placeCards((item) => ({ x: item.x, y: item.y }));
}

// From where cards were to where they belong. New ones come out of their parent, and ones that went
// away fold back into what is left of theirs.
function settle(starts, leaving) {
  const moves = nodes.some((item) => starts.get(item.key).x !== item.x || starts.get(item.key).y !== item.y);
  if (nodes.length > SETTLE_AT_MOST || (!moves && !leaving.length)) {
    leaving.forEach(({ card }) => card.remove());
    placeCards((item) => ({ x: item.x, y: item.y }));
    return;
  }
  placeCards((item) => starts.get(item.key));
  nodesBox.append(...leaving.map(({ card }) => card));
  const clear = () => leaving.forEach(({ card }) => card.remove());
  const run = tween(SETTLE, (t) => {
    placeCards((item) => {
      const from = starts.get(item.key);
      return { x: between(from.x, item.x, t), y: between(from.y, item.y, t) };
    });
    leaving.forEach(({ card, from, to }) => {
      card.style.opacity = String(1 - t);
      card.style.transform = `translate(${between(from.x, to.x, t)}px, ${between(from.y, to.y, t)}px)`;
    });
  }, () => {
    clear();
    settling = null;
  });
  settling = { stop() { run.cancel(); clear(); } };
}

// What left since the last drawing, and where each one folds back to.
function departures(previous, oldNodes) {
  return oldNodes.filter((item) => !byKey.has(item.key) && cards.has(item.key)).map((item) => {
    let home = item.parent;
    while (home && !byKey.has(home.key)) home = home.parent;
    const card = cards.get(item.key);
    card.classList.add("is-leaving");
    return { card, from: previous.get(item.key) ?? item, to: byKey.get(home?.key) ?? item };
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
  stopSettling();
  const previous = new Map(shown);
  const oldNodes = nodes;
  const first = !previous.size;
  const focused = viewport.contains(document.activeElement) ? document.activeElement.closest(".flow-node")?.dataset.key : null;

  root = buildGraph();
  layOut(root, offsets, rtl);
  nodes = flatten(root);
  byKey = new Map(nodes.map((item) => [item.key, item]));
  const leaving = departures(previous, oldNodes);
  cards.clear();
  shown.clear();
  nodes.forEach((item) => {
    const card = drawCard(item, { selected: state.selected?.key === item.key, twin: isTwin(item) });
    card.style.width = `${item.width}px`;
    card.style.height = `${item.height}px`;
    card.classList.toggle("is-new", !first && !previous.has(item.key));
    cards.set(item.key, card);
  });
  nodesBox.replaceChildren(...cards.values());
  drawWires(pathToSelected());
  cut.hidden = true;
  setTabStop();

  // A card that was opened or closed holds still on screen: everything is measured from it.
  const held = previous.get(keep);
  const anchor = byKey.get(keep);
  const drift = held && anchor ? { x: anchor.x - held.x, y: anchor.y - held.y } : { x: 0, y: 0 };
  shift(-drift.x * camera.zoom, -drift.y * camera.zoom);
  const starts = new Map();
  nodes.forEach((item) => {
    const old = previous.get(item.key);
    starts.set(item.key, old ? { x: old.x + drift.x, y: old.y + drift.y }
      : starts.get(item.parent?.key) ?? { x: item.x, y: item.y });
  });
  settle(starts, leaving);
  drawMap(nodes, state.selected?.key);

  if (fitAll) overview(nodes, root, { animate: !first });
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
  } else if (item.kind === "add") openAddDepartment(item.branch);
  else if (item.kind === "none") toggleNode(item);
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
    move: (dx, dy) => panTo(start.x + dx, start.y + dy),
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
  const everything = new Map(offsets);
  const before = offsets.get(item.key);
  const start = before ?? { x: 0, y: 0 };
  const carried = whatIsCarried(item);
  const places = landing(carried);
  return {
    from,
    nearEdgePans: true,
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
      drawMap(nodes, state.selected?.key);
      places.follow(worldPoint(event));
    },
    end(moved) {
      if (!moved) return;
      ignoreClick = true;
      if (places.target || item.kind === "employee") { // it goes back: the move decides where it ends up
        if (before) offsets.set(item.key, before);
        else offsets.delete(item.key);
      } else {
        arranged(everything);
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
    nearEdgePans: true,
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
  if (event.target.closest("[data-toggle],[data-check]") || item.kind === "more" || item.kind === "add") return null;
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

// Carrying something to the edge of the canvas moves the canvas, so it can reach anywhere.
function panNearEdge() {
  if (!gesture?.last) return;
  const { last, from } = gesture;
  const box = viewport.getBoundingClientRect();
  const toward = (at, low, high) => (at < low + EDGE_ZONE ? EDGE_SPEED : at > high - EDGE_ZONE ? -EDGE_SPEED : 0);
  const x = toward(last.clientX, box.left, box.right);
  const y = toward(last.clientY, box.top, box.bottom);
  if (x || y) {
    panBy(x, y);
    gesture.panned.x += x;
    gesture.panned.y += y;
    gesture.move(last.clientX - from.x - gesture.panned.x, last.clientY - from.y - gesture.panned.y, last);
  }
  requestAnimationFrame(panNearEdge);
}

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
    gesture.panned = { x: 0, y: 0 };
    gesture.begin?.();
    if (gesture.nearEdgePans) requestAnimationFrame(panNearEdge);
  }
  if (gesture.nearEdgePans) gesture.last = event;
  gesture.move(dx - gesture.panned.x, dy - gesture.panned.y, event);
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
  panBy(-(event.shiftKey ? event.deltaY : event.deltaX) * lines, event.shiftKey ? 0 : -event.deltaY * lines);
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
  if (event.key === "+" || event.key === "=") zoomIn();
  else if (event.key === "-") zoomIn(-1);
  else if (event.key === "0") fit(nodes);
});

// --- the controls -----------------------------------------------------------------------------

document.querySelector("[data-zoom-in]").addEventListener("click", () => zoomIn());
document.querySelector("[data-zoom-out]").addEventListener("click", () => zoomIn(-1));
document.querySelector("[data-zoom-fit]").addEventListener("click", () => fit(nodes));
document.querySelector("[data-tidy]").addEventListener("click", () => {
  const everything = new Map(offsets);
  offsets.clear();
  saveOffsets();
  if (everything.size) arranged(everything);
  drawCanvas({ fit: true });
});
