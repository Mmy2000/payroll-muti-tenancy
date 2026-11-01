// The moves of the company structure page: the side panel that asks for what a move needs, and which
// drops are allowed. A drag only opens this panel with the target chosen, so every move is dated,
// explained and saved the same way, from a drag or from a button.
import { api, ApiError } from "../../../core/js/api.js";
import { filterOptions } from "../../../core/js/selects.js";
import { toast } from "../../../core/js/ui.js";
import { forgetRedo } from "./history.js";
import { branchById, refresh, routes, state, words } from "./store.js";

const panel = document.querySelector("[data-panel]");
const backdrop = document.querySelector("[data-panel-backdrop]");
const form = panel.querySelector("[data-panel-form]");

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
  returnFocus?.focus?.({ preventScroll: true });
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
    forgetRedo();
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

export function openMovePeople(people, target = {}) {
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

export function openMoveDepartment(branch, department, toBranch = "") {
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

export function openRemoveDepartment(branch, department) {
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

export function openAddDepartment(branch, departmentId = "") {
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
  setChoice("add_department_id", departmentId);
}

// --- what can be dropped where ------------------------------------------------------------------
// What is carried: {kind: "people", people} | {kind: "department", branch, department} |
// {kind: "connect", branch}. Where it lands: {kind, branch, department}, as the canvas and the list
// both describe a node.

export function peopleToCarry(person) {
  return { kind: "people", people: state.checked.has(person.id) ? [...state.checked.values()] : [person] };
}

export function dropAllowed(carried, target) {
  const branch = target.branch;
  if (!carried || !branch) return false;
  if (carried.kind === "people") {
    const place = target.kind === "branch" || target.kind === "department" || target.kind === "none";
    const home = carried.people.every((person) => target.kind !== "branch" && person.branch_id === branch.id
      && person.department_id === (target.department?.id ?? null));
    return place && branch.can_manage_people && !home;
  }
  if (carried.kind === "department") {
    return target.kind === "branch" && branch.can_manage_departments && branch.id !== carried.branch.id;
  }
  return target.kind === "department" && carried.branch.can_manage_departments
    && !target.department.branch_ids.includes(carried.branch.id);
}

export function dropOn(carried, target) {
  if (carried.kind === "people") {
    openMovePeople(carried.people, { branch: target.branch.id, department: target.department?.id ?? null });
  } else if (carried.kind === "department") {
    openMoveDepartment(carried.branch, carried.department, target.branch.id);
  } else {
    openAddDepartment(branchById(carried.branch.id), target.department.id);
  }
}
