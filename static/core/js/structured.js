// Forms that send more than flat fields (shape "nested"): <form data-api-form data-shape="nested">.
//  - Dotted names nest: name="pay.salary" → {pay: {salary: …}}.
//  - Checkbox groups: unnamed checkboxes with data-multi="schedule.days_off" become an array of
//    the checked values (numbers when the group has data-number).
//  - Repeatable rows: a list [data-rows="bands"] of [data-row] elements whose inputs carry
//    data-field="from_minutes" (and no name) becomes an array of objects. A <template
//    data-row-template="bands"> holds the markup of a new row; [data-add-row="bands"] adds one,
//    [data-remove-row] removes its row. Each row's [data-row-error] shows the errors the server
//    gives for that row ("bands.2.to_minutes").
// Empty inputs follow forms.js: data-empty="null" sends null, otherwise "".

import { registerShaper } from "./forms.js";
import { enhanceSelects } from "./selects.js";

function setPath(target, path, value) {
  const parts = path.split(".");
  let node = target;
  for (const part of parts.slice(0, -1)) node = node[part] ??= {};
  node[parts.at(-1)] = value;
}

function inputValue(el) {
  if (el.type === "checkbox") return el.checked;
  const value = el.value.trim();
  if (value !== "") return value;
  return el.dataset.empty === "null" ? null : "";
}

function shapeNested(values, form) {
  const body = {};
  for (const [name, value] of Object.entries(values)) setPath(body, name, value);

  const groups = new Map();
  // form.elements also holds inputs outside the form tag that name it (form="…"), as in a table.
  [...form.elements].filter((el) => el.matches("input[data-multi]")).forEach((box) => {
    const group = groups.get(box.dataset.multi) ?? [];
    if (box.checked) group.push(box.closest("[data-number]") ? Number(box.value) : box.value);
    groups.set(box.dataset.multi, group);
  });
  groups.forEach((items, path) => setPath(body, path, items));

  form.querySelectorAll("[data-rows]").forEach((list) => {
    const rows = [...list.querySelectorAll(":scope > [data-row]")].map((row, index) => {
      row.querySelector("[data-row-error]")?.setAttribute("data-error-for", `${list.dataset.rows}.${index}`);
      const item = {};
      row.querySelectorAll("[data-field]").forEach((el) => (item[el.dataset.field] = inputValue(el)));
      return item;
    });
    setPath(body, list.dataset.rows, rows);
  });
  return body;
}

function addRow(name, root = document) {
  const list = root.querySelector(`[data-rows="${CSS.escape(name)}"]`);
  const template = root.querySelector(`template[data-row-template="${CSS.escape(name)}"]`);
  if (!list || !template) return null;
  const row = template.content.firstElementChild.cloneNode(true);
  list.append(row);
  enhanceSelects(row);
  row.querySelector("input, select")?.focus();
  return row;
}

export function initStructuredForms() {
  registerShaper("nested", shapeNested);
  document.addEventListener("click", (event) => {
    const add = event.target.closest("[data-add-row]");
    if (add) {
      event.preventDefault();
      addRow(add.dataset.addRow, add.closest("form") ?? document);
      return;
    }
    const remove = event.target.closest("[data-remove-row]");
    if (remove) {
      event.preventDefault();
      remove.closest("[data-row]")?.remove();
    }
  });
}
