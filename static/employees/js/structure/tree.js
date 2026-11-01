// The list view of the company structure page: the same company as an indented tree, for phones and
// for working from the keyboard (WAI-ARIA tree pattern).
import { badge, el, icon } from "./dom.js";
import { dropAllowed, dropOn, peopleToCarry } from "./moves.js";
import { branchById, branches, departmentIn, groupKey, select, shown, state, toggleChecked, toggleOpen, words } from "./store.js";

const treeBox = document.querySelector("[data-tree]");

function row({ key, kind, label, sub, count, canOpen, opened, data, draggable, badges = [], onClick }) {
  const item = el("div", `org-row org-row-${kind}`);
  item.setAttribute("role", "treeitem");
  item.tabIndex = -1;
  item.dataset.key = key;
  item.dataset.kind = kind;
  Object.assign(item.dataset, data);
  if (canOpen) item.setAttribute("aria-expanded", String(opened));
  if (state.selected?.key === key) item.setAttribute("aria-selected", "true");
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
  badges.forEach(([word, tone]) => item.append(badge(word, tone)));
  if (count !== undefined) item.append(el("span", "org-count num", String(count)));
  item.addEventListener("click", (event) => onClick(event, toggle));
  return item;
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
  wrapper.append(row({
    key, kind: "department", label: department.name, count: department.people,
    canOpen: true, opened, draggable: branch.can_manage_departments,
    badges: department.is_active ? [] : [[words.inactive, "neutral"]],
    data: { branch: branch.id, department: department.id },
    onClick: (event, toggle) => {
      if (toggle.contains(event.target)) toggleOpen(key, branch, department);
      else {
        select({ key, kind: "department", branch, department });
        if (!state.open.has(key)) toggleOpen(key, branch, department);
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
    onClick: () => toggleOpen(key, branch, null),
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
    key, kind: "branch", label: branch.name, count: branch.people, canOpen: true, opened, badges,
    data: { branch: branch.id },
    onClick: (event, toggle) => {
      if (toggle.contains(event.target)) toggleOpen(key, branch);
      else {
        select({ key, kind: "branch", branch });
        if (!state.open.has(key)) toggleOpen(key, branch);
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

export function drawTree({ reveal } = {}) {
  const scroll = treeBox.parentElement.scrollTop;
  treeBox.replaceChildren(...branches().filter(shown).map(drawBranch));
  treeBox.parentElement.scrollTop = scroll;
  const rows = [...treeBox.querySelectorAll(".org-row")];
  const current = rows.find((item) => item.dataset.key === state.selected?.key) ?? rows[0];
  if (current) current.tabIndex = 0;
  if (reveal) treeBox.querySelector(`[data-key="${reveal}"]`)?.scrollIntoView({ block: "nearest" });
}

// --- dragging ---------------------------------------------------------------------------------

let carried = null;

function placeOf(item) {
  const branch = branchById(Number(item.dataset.branch));
  return { kind: item.dataset.kind, branch, department: departmentIn(branch, Number(item.dataset.department)) };
}

treeBox.addEventListener("dragstart", (event) => {
  const item = event.target.closest(".org-row");
  if (!item?.draggable) return;
  const { branch, department } = placeOf(item);
  if (item.dataset.person) {
    const people = state.people.get(groupKey(branch.id, department?.id ?? null));
    carried = peopleToCarry(people.find((person) => person.id === Number(item.dataset.person)));
  } else {
    carried = { kind: "department", branch, department };
  }
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", item.dataset.key);
  item.classList.add("is-dragged");
});

treeBox.addEventListener("dragend", (event) => {
  event.target.closest(".org-row")?.classList.remove("is-dragged");
  treeBox.querySelectorAll(".is-drop").forEach((node) => node.classList.remove("is-drop"));
  carried = null;
});

treeBox.addEventListener("dragover", (event) => {
  const item = event.target.closest(".org-row");
  treeBox.querySelectorAll(".is-drop").forEach((node) => {
    if (node !== item) node.classList.remove("is-drop");
  });
  if (item && dropAllowed(carried, placeOf(item))) {
    event.preventDefault();
    item.classList.add("is-drop");
  }
});

treeBox.addEventListener("drop", (event) => {
  const item = event.target.closest(".org-row");
  if (!item || !dropAllowed(carried, placeOf(item))) return;
  event.preventDefault();
  dropOn(carried, placeOf(item));
});

// --- the keyboard -----------------------------------------------------------------------------

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
