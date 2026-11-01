// The canvas's nodes: what to show from the store as a tree of nodes, and where each one goes. The
// positions are worked out, not stored. What a person drags is kept as an offset from the tidy place,
// which carries the node's children along and survives opening and closing things.
import { branches, company, groupKey, shown, state, words } from "./store.js";

const PEOPLE_PAGE = 12; // more than this and a department's people open a page at a time

const WIDTHS = [248, 296, 272, 232]; // by depth: company, branch, department, employee
const HEIGHTS = { company: 76, branch: 80, department: 68, none: 64, employee: 56, more: 40, hint: 40, add: 40 };
const COLUMN_GAP = 104;
const ROW_GAPS = [40, 20, 10, 0]; // between the children of a node at each depth

function node(kind, key, fields = {}) {
  return { kind, key, children: [], ...fields };
}

export function showMore(key) {
  state.pageOf.set(key, (state.pageOf.get(key) ?? PEOPLE_PAGE) + PEOPLE_PAGE);
}

function hint(key, label) {
  return node("hint", `${key}:hint`, { label });
}

function peopleNodes(key, branch, departmentId) {
  const people = state.people.get(key);
  if (!people) return [hint(key, words.loading)];
  if (!people.length) return [hint(key, words.nobody)];
  const limit = state.pageOf.get(key) ?? PEOPLE_PAGE;
  const nodes = people.slice(0, limit).map((person) => node("employee", `p${person.id}`, {
    label: person.name, sub: [person.code, person.job_title].filter(Boolean).join(" · "),
    branch, person, departmentId, canCarry: branch.can_manage_people,
  }));
  if (people.length > limit) {
    nodes.push(node("more", `${key}:more`, { label: words.show_more, count: people.length - limit, group: key }));
  }
  return nodes;
}

function departmentNode(branch, department) {
  const key = groupKey(branch.id, department.id);
  const open = state.open.has(key);
  return node("department", key, {
    label: department.name, count: department.people, open, branch, department,
    share: department.people / (branch.people || 1),
    canCarry: branch.can_manage_departments, inactive: !department.is_active,
    children: open ? peopleNodes(key, branch, department.id) : [],
  });
}

function unassignedNode(branch) {
  const key = groupKey(branch.id, null);
  const open = state.open.has(key);
  return node("none", key, {
    label: words.no_department, count: branch.unassigned, open, branch,
    children: open ? peopleNodes(key, branch, null) : [],
  });
}

function branchNode(branch, total) {
  const key = `b${branch.id}`;
  const open = state.open.has(key);
  const children = open ? branch.departments.filter(shown).map((department) => departmentNode(branch, department)) : [];
  if (open && branch.unassigned) children.push(unassignedNode(branch));
  if (open && !children.length && branch.can_manage_departments) {
    children.push(node("add", `${key}:add`, { label: words.add_department, branch }));
  }
  const places = `${branch.departments.length} ${words.departments}`;
  return node("branch", key, {
    label: branch.name, sub: branch.is_head_office ? `${words.head_office} · ${places}` : places,
    count: branch.people, share: branch.people / (total || 1), open, branch,
    inactive: !branch.is_active, children,
  });
}

export function buildGraph() {
  const total = branches().filter(shown).reduce((sum, branch) => sum + branch.people, 0);
  const children = branches().filter(shown).map((branch) => branchNode(branch, total));
  return node("company", "company", { label: company, sub: `${children.length} ${words.branches}`, count: total, children });
}

// --- where everything goes ----------------------------------------------------------------------

function columns() {
  let left = 0;
  return WIDTHS.map((width) => {
    const here = left;
    left += width + COLUMN_GAP;
    return here;
  });
}

function measure(item, depth, parent) {
  Object.assign(item, { depth, parent, width: WIDTHS[depth], height: HEIGHTS[item.kind] });
  item.children.forEach((child) => measure(child, depth + 1, item));
  const stacked = item.children.reduce((total, child) => total + child.span, 0)
    + ROW_GAPS[depth] * Math.max(item.children.length - 1, 0);
  item.span = Math.max(item.height, stacked);
}

function place(item, top, carried, { offsets, rtl, lefts }) {
  const own = offsets.get(item.key);
  const shift = { x: carried.x + (own?.x ?? 0), y: carried.y + (own?.y ?? 0) };
  item.x = (rtl ? -lefts[item.depth] - item.width : lefts[item.depth]) + shift.x;
  item.y = top + (item.span - item.height) / 2 + shift.y;
  let next = top;
  item.children.forEach((child) => {
    place(child, next, shift, { offsets, rtl, lefts });
    next += child.span + ROW_GAPS[item.depth];
  });
}

export function layOut(root, offsets, rtl) {
  measure(root, 0, null);
  place(root, 0, { x: 0, y: 0 }, { offsets, rtl, lefts: columns() });
}

export function flatten(item) {
  return [item, ...item.children.flatMap(flatten)];
}

export function bounds(nodes) {
  return {
    left: Math.min(...nodes.map((item) => item.x)), top: Math.min(...nodes.map((item) => item.y)),
    right: Math.max(...nodes.map((item) => item.x + item.width)),
    bottom: Math.max(...nodes.map((item) => item.y + item.height)),
  };
}

// The side of a card its wires leave from, and the side they arrive at.
export function outPoint(item, rtl) {
  return { x: rtl ? item.x : item.x + item.width, y: item.y + item.height / 2 };
}

export function inPoint(item, rtl) {
  return { x: rtl ? item.x + item.width : item.x, y: item.y + item.height / 2 };
}

export function wirePath(from, to, rtl) {
  const bend = Math.max(48, Math.abs(to.x - from.x) / 2) * (rtl ? -1 : 1);
  return `M${from.x} ${from.y} C${from.x + bend} ${from.y} ${to.x - bend} ${to.y} ${to.x} ${to.y}`;
}
