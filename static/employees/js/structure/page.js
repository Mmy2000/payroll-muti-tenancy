// The company structure page (apps/employees/templates/employees/structure.html): the toolbar, the
// search and the switch between the two views of the same company. Dragging is a shortcut in both:
// every move is also a button in the details panel, for touch screens and the keyboard.
import { api } from "../../../core/js/api.js";
import { drawCanvas } from "./canvas.js";
import { avatar, el, icon } from "./dom.js";
import { drawInspector } from "./inspector.js";
import { openMovePeople } from "./moves.js";
import { branchById, branches, changed, clearChecked, departmentIn, onChange, refresh, reveal, routes, shown, state, words } from "./store.js";
import { drawTree } from "./tree.js";

const root = document.querySelector("[data-structure]");
const body = root.querySelector("[data-body]");
const searchBox = root.querySelector("[data-search]");
const resultsBox = root.querySelector("[data-results]");
const selectionBar = root.querySelector("[data-selection]");
const statusBox = root.querySelector("[data-status]");

const VIEW_KEY = "structure.view";
const PHONE = "(max-width: 767px)";
const OPEN_AT_START = 8; // more branches than this start closed, so the first view stays readable

function remembered() {
  try {
    return localStorage.getItem(VIEW_KEY);
  } catch {
    return null;
  }
}

let view = remembered() ?? (matchMedia(PHONE).matches ? "list" : "canvas");

function drawStats() {
  const active = branches().filter((branch) => branch.is_active);
  const departments = new Set(active.flatMap((branch) => branch.departments)
    .filter((department) => department.is_active).map((department) => department.id));
  const counts = {
    branches: active.length, departments: departments.size,
    people: active.reduce((total, branch) => total + branch.people, 0),
    unassigned: active.reduce((total, branch) => total + branch.unassigned, 0),
  };
  Object.entries(counts).forEach(([name, value]) => {
    root.querySelector(`[data-stat="${name}"]`).textContent = value;
  });
  root.querySelector('[data-stat="unassigned"]').parentElement.classList.toggle("is-warn", counts.unassigned > 0);
}

function drawSelection() {
  selectionBar.hidden = state.checked.size === 0;
  selectionBar.querySelector("[data-selection-count]").textContent = `${state.checked.size} ${words.selected}`;
}

function draw(hints) {
  drawStats();
  drawSelection();
  drawInspector();
  if (view === "canvas") drawCanvas(hints);
  else drawTree(hints);
}

function setView(next) {
  view = next;
  body.dataset.view = next;
  root.querySelector("[data-canvas-view]").hidden = next !== "canvas";
  root.querySelector("[data-list-view]").hidden = next !== "list";
  root.querySelector(`[data-view-choice][value="${next}"]`).checked = true;
  try {
    localStorage.setItem(VIEW_KEY, next);
  } catch {
    // the page simply opens on its default next time
  }
  changed({ fit: true });
}

// --- the search -------------------------------------------------------------------------------

function closeResults() {
  searchBox.value = "";
  resultsBox.hidden = true;
  resultsBox.replaceChildren();
}

function glyph(name) {
  const box = el("span", "flow-result-glyph");
  box.append(icon(name));
  return box;
}

function result(mark, label, sub, target) {
  const button = el("button", "flow-result");
  button.type = "button";
  const text = el("span", "min-w-0 flex-1");
  text.append(el("span", "org-name", label));
  if (sub) text.append(el("span", "org-sub", sub));
  button.append(mark, text);
  button.addEventListener("click", () => {
    closeResults();
    reveal(target);
  });
  return button;
}

function drawResults(text, people) {
  const found = [];
  branches().filter(shown).forEach((branch) => {
    if (branch.name.toLowerCase().includes(text)) found.push(result(glyph("store"), branch.name, "", { branch }));
    branch.departments.filter(shown).forEach((department) => {
      if (department.name.toLowerCase().includes(text)) found.push(result(glyph("users-round"), department.name, branch.name, { branch, department }));
    });
  });
  people.forEach((person) => {
    const branch = branchById(person.branch_id);
    const department = departmentIn(branch, person.department_id);
    const sub = [person.job_title, department?.name, branch?.name].filter(Boolean).join(" · ");
    found.push(result(avatar(person.name), person.name, sub, { branch, department, person }));
  });
  resultsBox.replaceChildren(...(found.length ? found : [el("p", "org-hint", words.nothing_found)]));
  resultsBox.hidden = false;
}

let searching = null;
searchBox.addEventListener("input", () => {
  clearTimeout(searching);
  const text = searchBox.value.trim();
  if (!text) {
    closeResults();
    return;
  }
  searching = setTimeout(async () => {
    const people = await api(`${routes.search}?${new URLSearchParams({ q: text })}`, { quiet: true }).catch(() => []);
    if (searchBox.value.trim() === text) drawResults(text.toLowerCase(), people);
  }, 220);
});

searchBox.addEventListener("keydown", (event) => {
  const first = resultsBox.querySelector(".flow-result");
  if (event.key === "Escape") closeResults();
  else if (event.key === "Enter") first?.click();
  else if (event.key === "ArrowDown" && first) {
    event.preventDefault();
    first.focus();
  }
});

resultsBox.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeResults();
    searchBox.focus();
    return;
  }
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  event.preventDefault();
  const rows = [...resultsBox.querySelectorAll(".flow-result")];
  const next = rows[rows.indexOf(document.activeElement) + (event.key === "ArrowDown" ? 1 : -1)];
  (next ?? searchBox).focus();
});

// "/" goes to the search from anywhere that isn't being typed in.
document.addEventListener("keydown", (event) => {
  if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest("input, textarea, select, [contenteditable]") || event.target.closest("dialog, [data-panel]")) return;
  event.preventDefault();
  searchBox.focus();
});

document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest("[data-search-box]")) closeResults();
});

// --- the toolbar ------------------------------------------------------------------------------

root.querySelectorAll("[data-view-choice]").forEach((choice) => {
  choice.addEventListener("change", () => setView(choice.value));
});

root.querySelector("[data-show-inactive]").addEventListener("change", (event) => {
  state.inactive = event.target.checked;
  changed();
});

root.querySelector("[data-expand-all]").addEventListener("click", () => {
  branches().forEach((branch) => state.open.add(`b${branch.id}`));
  changed({ fit: true });
});

root.querySelector("[data-collapse-all]").addEventListener("click", () => {
  state.open.clear();
  changed({ fit: true });
});

selectionBar.querySelector("[data-selection-clear]").textContent = words.clear;
selectionBar.querySelector("[data-selection-move-label]").textContent = words.move_selected;
selectionBar.querySelector("[data-selection-clear]").addEventListener("click", clearChecked);
selectionBar.querySelector("[data-selection-move]").addEventListener("click", () => openMovePeople([...state.checked.values()]));

async function start() {
  statusBox.hidden = false;
  statusBox.replaceChildren(el("span", "animate-pulse", words.loading));
  try {
    await refresh();
  } catch {
    const retry = el("button", "btn btn-secondary", words.try_again);
    retry.type = "button";
    retry.addEventListener("click", start);
    statusBox.replaceChildren(el("span", "", words.load_failed), retry);
    return;
  }
  statusBox.hidden = true;
  const opening = branches().filter(shown);
  if (opening.length <= OPEN_AT_START) opening.forEach((branch) => state.open.add(`b${branch.id}`));
  onChange(draw);
  setView(view);
}

start();
