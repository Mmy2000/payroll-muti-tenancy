// The details of what is selected on the company structure page: how it is made up, the places
// connected to it, and what can be done with it.
import { avatar, el, icon } from "./dom.js";
import { openAddDepartment, openMoveDepartment, openMovePeople, openRemoveDepartment } from "./moves.js";
import { branchById, departmentIn, groupKey, reveal, select, state, words } from "./store.js";

const PEOPLE_PREVIEW = 6;

const inspector = document.querySelector("[data-inspector]");

function facts(pairs) {
  const list = el("dl", "flow-facts");
  pairs.forEach(([term, value]) => {
    const box = el("div", "flow-fact");
    box.append(el("dd", "num", String(value)), el("dt", "", term));
    list.append(box);
  });
  return list;
}

function fact(list, term, value) {
  const line = el("div", "flex justify-between gap-4 text-sm");
  line.append(el("dt", "text-slate-500", term), el("dd", "text-end font-medium text-slate-800", value));
  list.append(line);
}

function section(title, ...content) {
  const box = el("section", "space-y-2");
  box.append(el("h3", "flow-section", title), ...content);
  return box;
}

// Places and how many people each has, biggest first: one bar in one colour, measured against the
// biggest. A row leads to its place.
function placesList(rows) {
  const largest = Math.max(...rows.map((row) => row.count), 1);
  const list = el("div", "space-y-0.5");
  [...rows].sort((a, b) => b.count - a.count).forEach((row) => {
    const button = el("button", `flow-place${row.warn ? " is-warn" : ""}`);
    button.type = "button";
    button.disabled = Boolean(row.current);
    button.addEventListener("click", row.onClick);
    const bar = el("span", "flow-bar-track");
    const fill = el("span", "flow-bar-fill");
    fill.style.width = `${(row.count / largest) * 100}%`;
    bar.append(fill);
    const line = el("span", "flex items-baseline justify-between gap-3");
    line.append(el("span", "min-w-0 truncate", row.label), el("span", "num text-xs font-medium text-slate-600", String(row.count)));
    button.append(line, bar);
    list.append(button);
  });
  return list;
}

function peoplePreview(key, total) {
  const people = state.people.get(key);
  if (!people?.length) return null;
  const stack = el("div", "flow-faces");
  people.slice(0, PEOPLE_PREVIEW).forEach((person) => {
    const face = avatar(person.name);
    face.title = person.name;
    stack.append(face);
  });
  if (total > PEOPLE_PREVIEW) stack.append(el("span", "flow-avatar num", `+${total - PEOPLE_PREVIEW}`));
  return stack;
}

function action(label, iconName, onClick, { href = "", primary = false, danger = false } = {}) {
  const node = el(href ? "a" : "button", `btn ${primary ? "btn-primary" : "btn-secondary"} w-full justify-start`);
  if (href) node.href = href;
  else {
    node.type = "button";
    node.addEventListener("click", onClick);
  }
  if (danger) node.classList.add("text-red-600");
  node.append(icon(iconName), el("span", "", label));
  return node;
}

function closeButton() {
  const close = el("button", "btn btn-ghost -me-2 -mt-1 shrink-0 px-2");
  close.type = "button";
  close.setAttribute("aria-label", words.close);
  close.append(icon("x"));
  close.addEventListener("click", () => select(null));
  return close;
}

function head(mark, title, subtitle) {
  const box = el("div", "flex items-start gap-3");
  const text = el("div", "min-w-0 flex-1");
  text.append(el("h2", "text-base font-semibold tracking-tight break-words text-slate-900", title));
  if (subtitle) text.append(el("p", "mt-0.5 text-sm text-slate-500", subtitle));
  box.append(mark, text, closeButton());
  return box;
}

function tile(iconName) {
  const mark = el("span", "stat-icon");
  mark.append(icon(iconName));
  return mark;
}

const newEmployee = (query) => `${state.tree.urls.new_employee}?${new URLSearchParams(query)}`;

function drawBranch(body, actions, branch) {
  body.append(head(tile("store"), branch.name, branch.is_head_office ? words.head_office : words.branch));
  body.append(facts([[words.code, branch.code], [words.departments, branch.departments.length], [words.employees, branch.people]]));
  const rows = branch.departments.filter((department) => department.is_active).map((department) => ({
    label: department.name, count: department.people, onClick: () => reveal({ branch, department }),
  }));
  if (branch.unassigned) {
    rows.push({ label: words.no_department, count: branch.unassigned, warn: true, onClick: () => reveal({ branch, department: null, unassigned: true }) });
  }
  if (rows.length) body.append(section(words.by_department, placesList(rows)));
  if (branch.can_manage_departments) {
    actions.append(action(words.add_department, "plus", () => openAddDepartment(branch), { primary: true }));
  }
  if (state.tree.can_add_employee && branch.can_manage_people) {
    actions.append(action(words.new_employee, "plus", null, { href: newEmployee({ branch: branch.id }) }));
  }
  if (branch.edit_url) actions.append(action(words.edit_branch, "pencil", null, { href: branch.edit_url }));
}

function drawDepartment(body, actions, branch, department) {
  body.append(head(tile("users-round"), department.name, branch.name));
  body.append(facts([[words.code, department.code], [words.employees, department.people], [words.branches, department.branch_ids.length]]));
  const preview = peoplePreview(groupKey(branch.id, department.id), department.people);
  if (preview) body.append(section(words.employees, preview));
  const rows = department.branch_ids.map(branchById).filter(Boolean).map((place) => ({
    label: place.name, count: departmentIn(place, department.id)?.people ?? 0, current: place.id === branch.id,
    onClick: () => reveal({ branch: place, department: departmentIn(place, department.id) }),
  }));
  if (rows.length > 1) body.append(section(words.in_branches, placesList(rows)));
  if (branch.can_manage_departments) {
    actions.append(action(words.move_department, "arrow-left-right", () => openMoveDepartment(branch, department), { primary: true }));
    if (department.branch_ids.length > 1) {
      actions.append(action(words.remove_department, "unlink", () => openRemoveDepartment(branch, department), { danger: true }));
    }
    if (department.edit_url) actions.append(action(words.edit_department, "pencil", null, { href: department.edit_url }));
  }
  if (state.tree.can_add_employee && branch.can_manage_people) {
    actions.append(action(words.new_employee, "plus", null, { href: newEmployee({ branch: branch.id, department: department.id }) }));
  }
}

function drawEmployee(body, actions, branch, person, department) {
  body.append(head(avatar(person.name, "size-11 text-sm"), person.name, person.job_title));
  const list = el("dl", "space-y-2 border-y border-slate-100 py-4");
  fact(list, words.code, String(person.code));
  fact(list, words.branch, branch.name);
  fact(list, words.department, departmentIn(branch, department)?.name ?? words.no_department);
  body.append(list);
  if (branch.can_manage_people) {
    actions.append(action(words.move_employee, "arrow-left-right", () => openMovePeople([person]), { primary: true }));
  }
  actions.append(action(words.open, "eye", null, { href: person.url }));
}

export function drawInspector() {
  const target = state.selected;
  const wasEmpty = inspector.hasAttribute("data-empty");
  const scroll = inspector.scrollTop;
  const body = el("div", "card-body space-y-5");
  inspector.toggleAttribute("data-empty", !target);
  inspector.classList.toggle("is-opening", wasEmpty && Boolean(target));
  if (!target) {
    body.append(el("p", "text-sm leading-6 text-slate-500", words.pick_something));
    inspector.replaceChildren(body);
    return;
  }
  const actions = el("div", "space-y-2");
  if (target.kind === "branch") drawBranch(body, actions, target.branch);
  else if (target.kind === "department") drawDepartment(body, actions, target.branch, target.department);
  else drawEmployee(body, actions, target.branch, target.person, target.department);
  body.append(actions);
  inspector.replaceChildren(body);
  inspector.scrollTop = scroll;
}
