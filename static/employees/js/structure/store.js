// The company structure page's data, shared by the canvas and the list: the tree from the API, what
// is open and what is selected. The tree and head counts load at once; a department's people load
// when it is opened, so a large company stays quick.
import { api } from "../../../core/js/api.js";

export const { words, company, api: routes } = JSON.parse(document.getElementById("structure-config").textContent);

export const state = {
  tree: null,
  open: new Set(), // keys of the opened nodes: "b3", "b3:d7", "b3:d0" (no department)
  people: new Map(), // key → the people of a department
  pageOf: new Map(), // key → how many of them the canvas shows
  selected: null, // {key, kind, branch, department?, person?}
  checked: new Map(), // employee id → person
  inactive: false,
};

let redraw = () => {};

// The page says how to draw. `hints` tell the view what the change is about: {keep: key} holds that
// node still on screen, {reveal: key} brings it into view, {fit: true} shows everything.
export function onChange(callback) {
  redraw = callback;
}

export function changed(hints = {}) {
  redraw(hints);
}

export const groupKey = (branchId, departmentId) => `b${branchId}:d${departmentId ?? 0}`;
export const branches = () => state.tree?.branches ?? [];
export const shown = (node) => state.inactive || node.is_active;

export function branchById(id) {
  return branches().find((branch) => branch.id === id);
}

export function departmentIn(branch, id) {
  return branch?.departments.find((department) => department.id === id);
}

async function loadPeople(key, branchId, departmentId) {
  const query = new URLSearchParams({ branch: branchId });
  if (departmentId) query.set("department", departmentId);
  state.people.set(key, await api(`${routes.people}?${query}`, { quiet: true }));
}

export function select(target, hints) {
  state.selected = target;
  changed({ reveal: target?.key, ...hints });
}

// `department` is undefined on a branch, and null on a branch's people without a department.
export async function toggleOpen(key, branch, department) {
  if (state.open.has(key)) {
    state.open.delete(key);
    changed({ keep: key });
    return;
  }
  state.open.add(key);
  changed({ keep: key });
  if (department !== undefined && !state.people.has(key)) {
    await loadPeople(key, branch.id, department?.id ?? null);
    changed({ keep: key });
  }
}

export function toggleChecked(person, on) {
  if (on) state.checked.set(person.id, person);
  else state.checked.delete(person.id);
  changed();
}

export function clearChecked() {
  state.checked.clear();
  changed();
}

export async function reveal({ branch, department, person }) {
  state.open.add(`b${branch.id}`);
  let target = { key: `b${branch.id}`, kind: "branch", branch };
  if (department || person) {
    const key = groupKey(branch.id, department?.id ?? null);
    state.open.add(key);
    if (!state.people.has(key)) await loadPeople(key, branch.id, department?.id ?? null);
    if (department) target = { key, kind: "department", branch, department };
  }
  if (person) {
    target = { key: `p${person.id}`, kind: "employee", branch, person, department: department?.id ?? null };
  }
  select(target, { center: true });
}

function keepSelection() {
  if (!state.selected) return;
  const branch = branchById(state.selected.branch.id);
  const department = departmentIn(branch, state.selected.department?.id);
  if (state.selected.kind === "branch" && branch) state.selected.branch = branch;
  else if (state.selected.kind === "department" && department) Object.assign(state.selected, { branch, department });
  else state.selected = null;
}

export async function refresh(hints) {
  state.tree = await api(routes.tree, { quiet: true });
  state.people.clear();
  state.checked.clear();
  await Promise.all([...state.open].filter((key) => key.includes(":")).map((key) => {
    const [branch, department] = key.slice(1).split(":d").map(Number);
    return loadPeople(key, branch, department || null);
  }));
  keepSelection();
  changed(hints);
}
