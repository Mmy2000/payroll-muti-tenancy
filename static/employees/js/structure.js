// The company structure page (apps/employees/templates/employees/structure.html): the tree, what is
// selected, and the moves. The tree and head counts come from the API; a department's people come
// when it is opened, so a large company stays quick. Dragging is a shortcut: every move is also a
// button in the side panel, for touch screens and the keyboard.
import { api, ApiError } from "../../core/js/api.js";
import { filterOptions } from "../../core/js/selects.js";
import { toast } from "../../core/js/ui.js";

const root = document.querySelector("[data-structure]");
const { words, api: routes } = JSON.parse(document.getElementById("structure-config").textContent);

const treeBox = root.querySelector("[data-tree]");
const inspector = root.querySelector("[data-inspector]");
const panel = document.querySelector("[data-panel]");
const backdrop = document.querySelector("[data-panel-backdrop]");
const form = panel.querySelector("[data-panel-form]");
document.body.append(backdrop, panel); // over the whole window, not just the page's wrapper

const state = {
  tree: null,
  open: new Set(), // keys of the opened rows: "b3", "b3:d7", "b3:d0" (no department)
  people: new Map(), // key → the people of a department row
  selected: null, // {kind, branch, department?, person?}
  checked: new Map(), // employee id → person
  inactive: false,
  query: "",
  results: null,
};

// --- building blocks --------------------------------------------------------------------------

function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function icon(name) {
  return document.querySelector(`template[data-icon="${name}"]`).content.cloneNode(true);
}

function badge(text, tone = "neutral") {
  return el("span", `badge badge-${tone}`, text);
}

const groupKey = (branchId, departmentId) => `b${branchId}:d${departmentId ?? 0}`;
const branches = () => state.tree?.branches ?? [];
const shown = (node) => state.inactive || node.is_active;

function branchById(id) {
  return branches().find((branch) => branch.id === id);
}

// --- the tree ---------------------------------------------------------------------------------

function row({ key, kind, label, sub, count, canOpen, opened, data, draggable, onClick }) {
  const item = el("div", `org-row org-row-${kind}`);
  item.setAttribute("role", "treeitem");
  item.tabIndex = -1;
  item.dataset.key = key;
  Object.assign(item.dataset, data);
  if (canOpen) item.setAttribute("aria-expanded", String(opened));
  if (isSelected(key)) item.setAttribute("aria-selected", "true");
  item.draggable = Boolean(draggable);

  if (draggable) item.append(Object.assign(el("span", "org-grip"), { ariaHidden: "true" }));
  if (draggable) item.lastChild.append(icon("grip-vertical"));
  const toggle = el("button", `org-toggle${opened ? " is-open" : ""}`);
  toggle.type = "button";
  toggle.tabIndex = -1;
  toggle.setAttribute("aria-hidden", "true");
  if (canOpen) toggle.append(icon("chevron-down"));
  else toggle.classList.add("invisible");
  item.append(toggle);

  if (kind === "employee") {
    const box = el("input", "org-check");
    box.type = "checkbox";
    box.tabIndex = -1;
    box.checked = state.checked.has(Number(data.person));
    box.setAttribute("aria-label", label);
    box.dataset.check = "";
    item.append(box);
  }

  const glyph = el("span", `org-glyph org-glyph-${kind}`);
  glyph.append(icon({ branch: "store", department: "users-round", employee: "user", none: "triangle-alert" }[kind]));
  const text = el("span", "min-w-0 flex-1 truncate");
  text.append(el("span", "org-name", label));
  if (sub) text.append(el("span", "org-sub", sub));
  item.append(glyph, text);
  (data.badges ? JSON.parse(data.badges) : []).forEach(([word, tone]) => item.append(badge(word, tone)));
  delete item.dataset.badges;
  if (count !== undefined) item.append(el("span", "org-count num", String(count)));
  item.addEventListener("click", (event) => onClick(event, toggle));
  return item;
}

function isSelected(key) {
  return state.selected?.key === key;
}

function group(parent, children) {
  const list = el("div", "org-group");
  list.setAttribute("role", "group");
  list.append(...children);
  parent.append(list);
}

function drawPeople(wrapper, key, branch, department) {
  const people = state.people.get(key);
  if (!people) {
    group(wrapper, [el("p", "org-hint", words.loading)]);
    return;
  }
  if (!people.length) {
    group(wrapper, [el("p", "org-hint", words.nobody)]);
    return;
  }
  group(wrapper, people.map((person) => row({
    key: `p${person.id}`, kind: "employee", label: person.name,
    sub: [person.code, person.job_title].filter(Boolean).join(" · "),
    draggable: branch.can_manage_people,
    data: { person: person.id, branch: branch.id, department: department ?? "" },
    onClick: (event) => {
      if (event.target.matches("[data-check]")) {
        toggleChecked(person, event.target.checked);
        return;
      }
      select({ key: `p${person.id}`, kind: "employee", branch, person, department });
    },
  })));
}

function drawDepartment(wrapper, branch, department) {
  const key = groupKey(branch.id, department.id);
  const opened = state.open.has(key);
  const badges = department.is_active ? [] : [[words.inactive, "neutral"]];
  wrapper.append(row({
    key, kind: "department", label: department.name, count: department.people,
    canOpen: true, opened, draggable: branch.can_manage_departments,
    data: { branch: branch.id, department: department.id, badges: JSON.stringify(badges) },
    onClick: (event, toggle) => {
      if (toggle.contains(event.target)) toggleRow(key, branch, department);
      else {
        select({ key, kind: "department", branch, department });
        if (!state.open.has(key)) toggleRow(key, branch, department);
      }
    },
  }));
  if (opened) drawPeople(wrapper, key, branch, department.id);
}

function drawUnassigned(wrapper, branch) {
  const key = groupKey(branch.id, null);
  const opened = state.open.has(key);
  wrapper.append(row({
    key, kind: "none", label: words.no_department, count: branch.unassigned, canOpen: true, opened,
    data: { branch: branch.id, department: "" },
    onClick: () => toggleRow(key, branch, null),
  }));
  if (opened) drawPeople(wrapper, key, branch, null);
}

function drawBranch(branch) {
  const wrapper = el("div");
  const key = `b${branch.id}`;
  const opened = state.open.has(key);
  const badges = [];
  if (branch.is_head_office) badges.push([words.head_office, "brand"]);
  if (!branch.is_active) badges.push([words.inactive, "neutral"]);
  wrapper.append(row({
    key, kind: "branch", label: branch.name, count: branch.people, canOpen: true, opened,
    data: { branch: branch.id, badges: JSON.stringify(badges) },
    onClick: (event, toggle) => {
      if (toggle.contains(event.target)) toggleRow(key, branch);
      else {
        select({ key, kind: "branch", branch });
        if (!state.open.has(key)) toggleRow(key, branch);
      }
    },
  }));
  if (opened) {
    const inner = el("div", "org-group");
    inner.setAttribute("role", "group");
    branch.departments.filter(shown).forEach((department) => drawDepartment(inner, branch, department));
    if (branch.unassigned) drawUnassigned(inner, branch);
    if (!inner.children.length) inner.append(el("p", "org-hint", words.nobody));
    wrapper.append(inner);
  }
  return wrapper;
}

function drawResults() {
  const text = state.query.toLowerCase();
  const places = [];
  branches().filter(shown).forEach((branch) => {
    if (branch.name.toLowerCase().includes(text)) {
      places.push(row({
        key: `b${branch.id}`, kind: "branch", label: branch.name, count: branch.people,
        data: { branch: branch.id }, onClick: () => reveal({ branch }),
      }));
    }
    branch.departments.filter(shown).forEach((department) => {
      if (department.name.toLowerCase().includes(text)) {
        places.push(row({
          key: groupKey(branch.id, department.id), kind: "department", label: department.name,
          sub: branch.name, count: department.people, data: { branch: branch.id, department: department.id },
          onClick: () => reveal({ branch, department }),
        }));
      }
    });
  });
  const people = (state.results ?? []).map((person) => {
    const branch = branchById(person.branch_id);
    const department = branch?.departments.find((row_) => row_.id === person.department_id);
    return row({
      key: `p${person.id}`, kind: "employee", label: person.name,
      sub: [person.job_title, department?.name, branch?.name].filter(Boolean).join(" · "),
      data: { person: person.id, branch: person.branch_id, department: person.department_id ?? "" },
      onClick: () => reveal({ branch, department, person }),
    });
  });
  const found = [...places, ...people];
  treeBox.replaceChildren(...(found.length ? found : [el("p", "org-hint", words.nothing_found)]));
  focusFirstRow();
}

function draw() {
  if (state.query) {
    drawResults();
    return;
  }
  const scroll = treeBox.parentElement.scrollTop;
  treeBox.replaceChildren(...branches().filter(shown).map(drawBranch));
  treeBox.parentElement.scrollTop = scroll;
  focusFirstRow();
}

function focusFirstRow() {
  const rows = [...treeBox.querySelectorAll(".org-row")];
  const current = rows.find((item) => item.dataset.key === state.selected?.key) ?? rows[0];
  if (current) current.tabIndex = 0;
}

async function loadPeople(key, branch, department) {
  const query = new URLSearchParams({ branch: branch.id });
  if (department) query.set("department", department);
  state.people.set(key, await api(`${routes.people}?${query}`, { quiet: true }));
}

async function toggleRow(key, branch, department) {
  if (state.open.has(key)) {
    state.open.delete(key);
    draw();
    return;
  }
  state.open.add(key);
  draw();
  if (department !== undefined && !state.people.has(key)) {
    await loadPeople(key, branch, department?.id ?? department);
    draw();
  }
}

async function reveal({ branch, department, person }) {
  state.query = "";
  root.querySelector("[data-search]").value = "";
  state.open.add(`b${branch.id}`);
  let target = { key: `b${branch.id}`, kind: "branch", branch };
  if (department || person) {
    const key = groupKey(branch.id, department?.id ?? null);
    state.open.add(key);
    if (!state.people.has(key)) await loadPeople(key, branch, department?.id ?? null);
    target = department ? { key, kind: "department", branch, department } : target;
  }
  if (person) {
    target = { key: `p${person.id}`, kind: "employee", branch, person, department: department?.id ?? null };
  }
  select(target);
  treeBox.querySelector(`[data-key="${target.key}"]`)?.scrollIntoView({ block: "center" });
}

function select(target) {
  state.selected = target;
  draw();
  drawInspector();
}

// --- what is selected -------------------------------------------------------------------------

function fact(list, term, value) {
  const line = el("div", "flex justify-between gap-4 text-sm");
  line.append(el("dt", "text-slate-500", term), el("dd", "num text-end font-medium text-slate-800", value));
  list.append(line);
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

function inspectorHead(iconName, title, subtitle) {
  const head = el("div", "flex items-start gap-3");
  const mark = el("span", "stat-icon");
  mark.append(icon(iconName));
  const text = el("div", "min-w-0");
  text.append(el("h2", "text-base font-semibold tracking-tight break-words text-slate-900", title));
  if (subtitle) text.append(el("p", "mt-0.5 text-sm text-slate-500", subtitle));
  head.append(mark, text);
  return head;
}

function departmentActions(actions, branch, department) {
  if (!branch.can_manage_departments) return;
  actions.append(action(words.move_department, "arrow-left-right", () => openMoveDepartment(branch, department), { primary: true }));
  if (department.branch_ids.length > 1) {
    actions.append(action(words.remove_department, "unlink", () => openRemoveDepartment(branch, department), { danger: true }));
  }
  if (department.edit_url) actions.append(action(words.edit_department, "pencil", null, { href: department.edit_url }));
}

function drawInspector() {
  const target = state.selected;
  const body = el("div", "card-body space-y-5");
  if (!target) {
    body.append(el("p", "text-sm leading-6 text-slate-500", words.pick_something));
    inspector.replaceChildren(body);
    return;
  }
  const { branch, department, person } = target;
  const facts = el("dl", "space-y-2 border-y border-slate-100 py-4");
  const actions = el("div", "space-y-2");
  const newEmployee = (query) => `${state.tree.urls.new_employee}?${new URLSearchParams(query)}`;

  if (target.kind === "branch") {
    body.append(inspectorHead("store", branch.name, branch.is_head_office ? words.head_office : words.branch));
    fact(facts, words.code, String(branch.code));
    fact(facts, words.departments, String(branch.departments.length));
    fact(facts, words.employees, String(branch.people));
    if (branch.can_manage_departments) {
      actions.append(action(words.add_department, "plus", () => openAddDepartment(branch), { primary: true }));
    }
    if (state.tree.can_add_employee && branch.can_manage_people) {
      actions.append(action(words.new_employee, "plus", null, { href: newEmployee({ branch: branch.id }) }));
    }
    if (branch.edit_url) actions.append(action(words.edit_branch, "pencil", null, { href: branch.edit_url }));
  } else if (target.kind === "department") {
    body.append(inspectorHead("users-round", department.name, branch.name));
    fact(facts, words.code, String(department.code));
    fact(facts, words.employees, String(department.people));
    const others = department.branch_ids.filter((id) => id !== branch.id).map((id) => branchById(id)?.name).filter(Boolean);
    fact(facts, words.also_in, others.join(" · ") || words.only_here);
    departmentActions(actions, branch, department);
    if (state.tree.can_add_employee && branch.can_manage_people) {
      actions.append(action(words.new_employee, "plus", null, { href: newEmployee({ branch: branch.id, department: department.id }) }));
    }
  } else {
    body.append(inspectorHead("user", person.name, person.job_title));
    const place = branch.departments.find((row_) => row_.id === department);
    fact(facts, words.code, String(person.code));
    fact(facts, words.branch, branch.name);
    fact(facts, words.department, place?.name ?? words.no_department);
    if (branch.can_manage_people) {
      actions.append(action(words.move_employee, "arrow-left-right", () => openMovePeople([person]), { primary: true }));
    }
    actions.append(action(words.open, "eye", null, { href: person.url }));
  }
  body.append(facts, actions);
  inspector.replaceChildren(body);
}

function toggleChecked(person, on) {
  if (on) state.checked.set(person.id, person);
  else state.checked.delete(person.id);
  drawSelection();
}

function drawSelection() {
  const bar = root.querySelector("[data-selection]");
  bar.hidden = state.checked.size === 0;
  bar.querySelector("[data-selection-count]").textContent = `${state.checked.size} ${words.selected}`;
}

// --- the panel --------------------------------------------------------------------------------

let submitting = null;
let returnFocus = null;

function setChoice(name, value) {
  const select = form.elements[name];
  if (select.tomselect) select.tomselect.setValue(String(value ?? ""), false);
  else select.value = String(value ?? "");
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function openPanel({ title, summary = "", note = "", fields, departmentLabel = words.department, onSubmit }) {
  panel.querySelector("[data-panel-title]").textContent = title;
  panel.querySelector("[data-panel-summary]").textContent = summary;
  const noteBox = panel.querySelector("[data-panel-note]");
  noteBox.textContent = note;
  noteBox.hidden = !note;
  panel.querySelector("[data-department-label]").textContent = departmentLabel;
  panel.querySelectorAll("[data-field]").forEach((field) => {
    field.hidden = !fields.includes(field.dataset.field);
  });
  clearErrors();
  form.elements.note.value = "";
  submitting = onSubmit;
  returnFocus = document.activeElement;
  panel.hidden = false;
  backdrop.hidden = false;
  requestAnimationFrame(() => panel.classList.add("is-open"));
  panel.querySelector("[data-panel-close]").focus();
}

function closePanel() {
  panel.classList.remove("is-open");
  panel.hidden = true;
  backdrop.hidden = true;
  submitting = null;
  returnFocus?.focus?.();
}

function clearErrors() {
  panel.querySelector("[data-panel-error]").classList.add("hidden");
  panel.querySelectorAll("[data-error-for]").forEach((node) => { node.textContent = ""; });
}

function showError(error) {
  const box = panel.querySelector("[data-panel-error]");
  const fields = error instanceof ApiError ? error.fields : {};
  let shownInPlace = false;
  Object.entries(fields).forEach(([name, messages]) => {
    panel.querySelectorAll(`[data-error-for="${name}"]`).forEach((node) => {
      if (node.closest("[data-field]")?.hidden) return;
      node.textContent = [].concat(messages).join(" ");
      shownInPlace = true;
    });
  });
  if (shownInPlace) return;
  box.textContent = Object.values(fields).flat().join(" ") || error.message;
  box.classList.remove("hidden");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearErrors();
  try {
    await submitting();
    closePanel();
    toast(words.saved);
    await refresh();
  } catch (error) {
    showError(error);
  }
});

panel.querySelectorAll("[data-panel-close]").forEach((button) => button.addEventListener("click", closePanel));
backdrop.addEventListener("click", closePanel);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !panel.hidden) closePanel();
});

const dateValue = () => form.elements.effective_from.value;

function openMovePeople(people, target = {}) {
  const ids = people.map((person) => person.id);
  openPanel({
    title: words.title_move_people,
    summary: people.length === 1 ? people[0].name : `${people.length} ${words.selected}`,
    fields: ["branch", "department", "date", "note"],
    onSubmit: () => api(routes.move_people, { method: "POST", body: {
      employee_ids: ids, branch_id: Number(form.elements.branch_id.value),
      department_id: form.elements.department_id.value ? Number(form.elements.department_id.value) : null,
      effective_from: dateValue(), note: form.elements.note.value,
    } }),
  });
  const first = people[0];
  setChoice("branch_id", target.branch ?? first.branch_id);
  setChoice("department_id", "department" in target ? target.department : first.department_id);
}

function openMoveDepartment(branch, department, toBranch = "") {
  openPanel({
    title: words.title_move_department,
    summary: `${department.name} · ${branch.name}`,
    note: department.people ? `${words.people_go_along} ${department.people}` : "",
    fields: ["branch", "date"],
    onSubmit: () => api(routes.move_department, { method: "POST", body: {
      department_id: department.id, from_branch_id: branch.id,
      branch_id: Number(form.elements.branch_id.value), effective_from: dateValue(),
    } }),
  });
  setChoice("branch_id", toBranch);
}

function openRemoveDepartment(branch, department) {
  openPanel({
    title: words.title_remove_department,
    summary: `${department.name} · ${branch.name}`,
    note: department.people ? `${words.people_stay} ${department.people}` : "",
    fields: department.people ? ["department", "date"] : [],
    onSubmit: () => api(routes.remove_department, { method: "POST", body: {
      department_id: department.id, from_branch_id: branch.id,
      move_to: form.elements.department_id.value ? Number(form.elements.department_id.value) : null,
      effective_from: dateValue(),
    } }),
  });
  setChoice("branch_id", branch.id);
  setChoice("department_id", "");
}

function openAddDepartment(branch) {
  const select = form.elements.add_department_id;
  filterOptions(select, (option) => !option.dataset.parent.split(" ").includes(String(branch.id)));
  openPanel({
    title: words.title_add_department,
    summary: branch.name,
    fields: ["add_department"],
    onSubmit: () => api(routes.add_department, { method: "POST", body: {
      department_id: Number(select.value), branch_id: branch.id,
    } }),
  });
  setChoice("add_department_id", "");
}

// --- dragging ---------------------------------------------------------------------------------

let dragged = null;

function dropAllowed(target) {
  if (!dragged || !target) return false;
  const branch = branchById(Number(target.dataset.branch));
  if (dragged.kind === "people") {
    return branch?.can_manage_people && (target.classList.contains("org-row-branch")
      || target.classList.contains("org-row-department") || target.classList.contains("org-row-none"));
  }
  return branch?.can_manage_departments && target.classList.contains("org-row-branch")
    && branch.id !== dragged.branch.id;
}

treeBox.addEventListener("dragstart", (event) => {
  const item = event.target.closest(".org-row");
  if (!item?.draggable) return;
  const branch = branchById(Number(item.dataset.branch));
  if (item.dataset.person) {
    const people = state.people.get(groupKey(branch.id, Number(item.dataset.department) || null));
    const person = people?.find((row_) => row_.id === Number(item.dataset.person));
    dragged = { kind: "people", people: state.checked.has(person.id) ? [...state.checked.values()] : [person] };
  } else {
    dragged = { kind: "department", branch, department: branch.departments.find((row_) => row_.id === Number(item.dataset.department)) };
  }
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", item.dataset.key);
  item.classList.add("is-dragged");
});

treeBox.addEventListener("dragend", (event) => {
  event.target.closest(".org-row")?.classList.remove("is-dragged");
  treeBox.querySelectorAll(".is-drop").forEach((node) => node.classList.remove("is-drop"));
  dragged = null;
});

treeBox.addEventListener("dragover", (event) => {
  const target = event.target.closest(".org-row");
  treeBox.querySelectorAll(".is-drop").forEach((node) => {
    if (node !== target) node.classList.remove("is-drop");
  });
  if (dropAllowed(target)) {
    event.preventDefault();
    target.classList.add("is-drop");
  }
});

treeBox.addEventListener("drop", (event) => {
  const target = event.target.closest(".org-row");
  if (!dropAllowed(target)) return;
  event.preventDefault();
  const branchId = Number(target.dataset.branch);
  if (dragged.kind === "people") {
    openMovePeople(dragged.people, { branch: branchId, department: target.dataset.department ? Number(target.dataset.department) : null });
  } else {
    openMoveDepartment(dragged.branch, dragged.department, branchId);
  }
});

// --- the keyboard (WAI-ARIA tree) ---------------------------------------------------------------

treeBox.addEventListener("keydown", (event) => {
  const item = event.target.closest(".org-row");
  if (!item || !["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Enter", " ", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const rows = [...treeBox.querySelectorAll(".org-row")];
  const index = rows.indexOf(item);
  const rtl = document.documentElement.dir === "rtl";
  const inward = rtl ? "ArrowLeft" : "ArrowRight";
  const outward = rtl ? "ArrowRight" : "ArrowLeft";
  const go = (next) => {
    if (!next) return;
    item.tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
  };
  if (event.key === "ArrowDown") go(rows[index + 1]);
  else if (event.key === "ArrowUp") go(rows[index - 1]);
  else if (event.key === "Home") go(rows[0]);
  else if (event.key === "End") go(rows[rows.length - 1]);
  else if (event.key === inward && item.getAttribute("aria-expanded") === "false") item.querySelector(".org-toggle").click();
  else if (event.key === outward && item.getAttribute("aria-expanded") === "true") item.querySelector(".org-toggle").click();
  else if (event.key === " " && item.querySelector("[data-check]")) item.querySelector("[data-check]").click();
  else if (event.key === "Enter" || event.key === " ") item.click();
});

// --- the toolbar ------------------------------------------------------------------------------

async function refresh() {
  state.tree = await api(routes.tree, { quiet: true });
  state.people.clear();
  state.checked.clear();
  drawSelection();
  await Promise.all([...state.open].filter((key) => key.includes(":")).map((key) => {
    const [branch, department] = key.slice(1).split(":d").map(Number);
    return loadPeople(key, { id: branch }, department || null);
  }));
  const counts = { branches: 0, departments: new Set(), people: 0, unassigned: 0 };
  branches().filter((branch) => branch.is_active).forEach((branch) => {
    counts.branches += 1;
    counts.people += branch.people;
    counts.unassigned += branch.unassigned;
    branch.departments.filter((department) => department.is_active).forEach((department) => counts.departments.add(department.id));
  });
  counts.departments = counts.departments.size;
  Object.entries(counts).forEach(([name, value]) => {
    root.querySelector(`[data-stat="${name}"]`).textContent = value;
  });
  if (state.selected) {
    const branch = branchById(state.selected.branch.id);
    const department = branch?.departments.find((row_) => row_.id === state.selected.department?.id);
    if (state.selected.kind === "branch" && branch) state.selected.branch = branch;
    else if (state.selected.kind === "department" && department) Object.assign(state.selected, { branch, department });
    else state.selected = null;
  }
  draw();
  drawInspector();
}

let searching = null;
root.querySelector("[data-search]").addEventListener("input", (event) => {
  clearTimeout(searching);
  state.query = event.target.value.trim();
  if (!state.query) {
    state.results = null;
    draw();
    return;
  }
  searching = setTimeout(async () => {
    state.results = await api(`${routes.search}?${new URLSearchParams({ q: state.query })}`, { quiet: true });
    draw();
  }, 220);
});

root.querySelector("[data-show-inactive]").addEventListener("change", (event) => {
  state.inactive = event.target.checked;
  draw();
});

root.querySelector("[data-expand-all]").addEventListener("click", () => {
  branches().forEach((branch) => state.open.add(`b${branch.id}`));
  draw();
});

root.querySelector("[data-collapse-all]").addEventListener("click", () => {
  state.open.clear();
  draw();
});

root.querySelector("[data-selection-clear]").textContent = words.clear;
root.querySelector("[data-selection-move-label]").textContent = words.move_selected;
root.querySelector("[data-selection-clear]").addEventListener("click", () => {
  state.checked.clear();
  drawSelection();
  draw();
});
root.querySelector("[data-selection-move]").addEventListener("click", () => openMovePeople([...state.checked.values()]));

await refresh(); // the tree starts with every branch open
branches().filter(shown).forEach((branch) => state.open.add(`b${branch.id}`));
draw();
drawInspector();
