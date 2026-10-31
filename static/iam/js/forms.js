// Member and role forms: request shapers plus small interactions (role scope, group toggles).
import { registerShaper } from "../../core/js/forms.js";
import { toast } from "../../core/js/ui.js";

registerShaper("member", (values, form) => {
  const roles = [];
  form.querySelectorAll("[data-role-row]").forEach((row) => {
    if (!row.querySelector("[data-role-toggle]").checked) return;
    const allBranches = row.querySelector("[data-scope]").value === "all";
    const branches = Array.from(row.querySelector("[data-branches]").selectedOptions, (o) => Number(o.value));
    roles.push({ role: Number(row.dataset.roleRow), all_branches: allBranches, branches });
  });
  const body = {
    display_name: values.display_name ?? "",
    username: values.username ?? "",
    email: values.email ?? "",
    phone: values.phone ?? "",
    default_branch: values.default_branch ? Number(values.default_branch) : null,
    roles,
  };
  if (values.password) body.password = values.password;
  // The employee this user is: only on forms that offer it (the mobile app is on).
  if ("employee" in values) body.employee = values.employee ? Number(values.employee) : null;
  return body;
});

registerShaper("role", (values, form) => ({
  name: values.name ?? "",
  description: values.description ?? "",
  permissions: Array.from(form.querySelectorAll("[data-permission]:checked"), (box) => box.dataset.permission),
}));

document.addEventListener("change", (event) => {
  const target = event.target;
  const row = target.closest("[data-role-row]");
  if (row && target.matches("[data-role-toggle]")) {
    row.querySelector("[data-role-scope]").classList.toggle("hidden", !target.checked);
  }
  if (row && target.matches("[data-scope]")) {
    row.querySelector("[data-branch-picker]").classList.toggle("hidden", target.value === "all");
    row.querySelector("[data-scope-warning]")?.classList.toggle("hidden", target.value === "all");
  }
  const group = target.closest("[data-permission-group]");
  if (group && target.matches("[data-group-toggle]")) {
    group.querySelectorAll("[data-permission]").forEach((box) => (box.checked = target.checked));
    keepRoleWhole(target.form, target.checked);
  }
  if (target.matches("[data-permission]")) {
    keepRoleWhole(target.form, target.checked);
    if (target.checked && target.matches("[data-company-wide]")) toast(target.form.dataset.onlyAll);
  }
  if (target.matches("[data-permission], [data-group-toggle]")) refreshBranchWarning(target.form);
});

// Members holding this role for selected branches don't get its company-wide permissions.
function refreshBranchWarning(form) {
  const warning = document.querySelector("[data-branch-warning]");
  if (!warning) return;
  const held = Array.from(form.querySelectorAll("[data-company-wide]:checked"), labelOf);
  warning.hidden = held.length === 0;
  warning.querySelector("[data-branch-warning-steps]").textContent = held.join(" · ");
}

const boxOf = (form, code) => form.querySelector(`[data-permission="${code}"]`);
const needsOf = (box) => box.dataset.needs.split(" ").filter(Boolean);
const labelOf = (box) => box.closest("label").querySelector("[data-step-label]").textContent;

// A step with no way to reach it gives the person nothing: what it needs goes on with it, and
// what can't work any more goes off with it. The toast says what else changed.
function keepRoleWhole(form, turningOn) {
  const boxes = Array.from(form.querySelectorAll("[data-permission]"));
  const changed = [];
  const flip = (box, on) => {
    if (box && box.checked !== on) {
      box.checked = on;
      changed.push(labelOf(box));
    }
  };
  if (turningOn) {
    boxes.filter((box) => box.checked).forEach((box) => needsOf(box).forEach((code) => flip(boxOf(form, code), true)));
  } else {
    boxes.filter((box) => box.checked && needsOf(box).some((code) => !boxOf(form, code).checked))
      .forEach((box) => flip(box, false));
  }
  if (changed.length) {
    toast(`${turningOn ? form.dataset.alsoOn : form.dataset.alsoOff} ${changed.join(" · ")}`);
  }
  refreshGroupToggles();
}

function refreshGroupToggles() {
  document.querySelectorAll("[data-permission-group]").forEach((group) => {
    const boxes = Array.from(group.querySelectorAll("[data-permission]"));
    group.querySelector("[data-group-toggle]").checked = boxes.length > 0 && boxes.every((box) => box.checked);
  });
}

document.querySelector("[data-add-missing]")?.addEventListener("click", (event) => {
  keepRoleWhole(event.target.form ?? event.target.closest("form"), true);
  document.querySelector("[data-role-gaps]")?.remove();
});

// Group toggles start checked when every permission in the group is.
document.querySelectorAll("[data-permission-group]").forEach((group) => {
  const boxes = group.querySelectorAll("[data-permission]");
  group.querySelector("[data-group-toggle]").checked = boxes.length > 0 && Array.from(boxes).every((b) => b.checked);
});
