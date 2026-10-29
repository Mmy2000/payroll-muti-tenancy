// Parts of a form that only apply to one choice: <div data-show-when="target_kind=branch">
// shows while the form's field "target_kind" (a radio group or a select) has the value "branch",
// and its inputs are disabled while hidden, so the form doesn't send them.

function valueOf(form, name) {
  const field = form.elements.namedItem(name);
  if (!field) return "";
  return field.value; // a RadioNodeList (radio group) has the checked value too
}

function refresh(form) {
  form.querySelectorAll("[data-show-when]").forEach((part) => {
    const [name, expected] = part.dataset.showWhen.split("=");
    const shown = valueOf(form, name) === expected;
    part.hidden = !shown;
    part.querySelectorAll("input, select, textarea").forEach((el) => (el.disabled = !shown));
    part.querySelectorAll(".ts-wrapper").forEach((wrapper) => wrapper.classList.toggle("disabled", !shown));
  });
}

export function initReveal() {
  document.querySelectorAll("form").forEach((form) => {
    if (form.querySelector("[data-show-when]")) refresh(form);
  });
  document.addEventListener("change", (event) => {
    const form = event.target.closest("form");
    if (form?.querySelector("[data-show-when]")) refresh(form);
  });
}
