// The details of what is selected on the company structure page, and what can be done with it.
import { el, icon } from "./dom.js";
import { openAddDepartment, openMoveDepartment, openMovePeople, openRemoveDepartment } from "./moves.js";
import { branchById, departmentIn, select, state, words } from "./store.js";

const inspector = document.querySelector("[data-inspector]");

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

function head(iconName, title, subtitle) {
  const box = el("div", "flex items-start gap-3");
  const mark = el("span", "stat-icon");
  mark.append(icon(iconName));
  const text = el("div", "min-w-0 flex-1");
  text.append(el("h2", "text-base font-semibold tracking-tight break-words text-slate-900", title));
  if (subtitle) text.append(el("p", "mt-0.5 text-sm text-slate-500", subtitle));
  const close = el("button", "btn btn-ghost -me-2 -mt-1 shrink-0 px-2");
  close.type = "button";
  close.setAttribute("aria-label", words.close);
  close.append(icon("x"));
  close.addEventListener("click", () => select(null));
  box.append(mark, text, close);
  return box;
}

function departmentActions(actions, branch, department) {
  if (!branch.can_manage_departments) return;
  actions.append(action(words.move_department, "arrow-left-right", () => openMoveDepartment(branch, department), { primary: true }));
  if (department.branch_ids.length > 1) {
    actions.append(action(words.remove_department, "unlink", () => openRemoveDepartment(branch, department), { danger: true }));
  }
  if (department.edit_url) actions.append(action(words.edit_department, "pencil", null, { href: department.edit_url }));
}

export function drawInspector() {
  const target = state.selected;
  const body = el("div", "card-body space-y-5");
  inspector.toggleAttribute("data-empty", !target);
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
    body.append(head("store", branch.name, branch.is_head_office ? words.head_office : words.branch));
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
    body.append(head("users-round", department.name, branch.name));
    fact(facts, words.code, String(department.code));
    fact(facts, words.employees, String(department.people));
    const others = department.branch_ids.filter((id) => id !== branch.id).map((id) => branchById(id)?.name).filter(Boolean);
    fact(facts, words.also_in, others.join(" · ") || words.only_here);
    departmentActions(actions, branch, department);
    if (state.tree.can_add_employee && branch.can_manage_people) {
      actions.append(action(words.new_employee, "plus", null, { href: newEmployee({ branch: branch.id, department: department.id }) }));
    }
  } else {
    body.append(head("user", person.name, person.job_title));
    fact(facts, words.code, String(person.code));
    fact(facts, words.branch, branch.name);
    fact(facts, words.department, departmentIn(branch, department)?.name ?? words.no_department);
    if (branch.can_manage_people) {
      actions.append(action(words.move_employee, "arrow-left-right", () => openMovePeople([person]), { primary: true }));
    }
    actions.append(action(words.open, "eye", null, { href: person.url }));
  }
  body.append(facts, actions);
  inspector.replaceChildren(body);
}
