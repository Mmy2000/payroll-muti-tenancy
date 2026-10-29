// Bulk changes with a preview (apps/core/bulk.py): <form data-bulk-form data-endpoint
// [data-shape] [data-redirect] [data-success]>. Submitting the form previews (save: false) and
// lists each row in [data-bulk-rows], one clone of <template data-bulk-row> per row, filling
// its [data-slot="name|detail|status|notes"]. Then:
//   [data-bulk-save]          saves every row (shown only when none fails);
//   [data-bulk-save-passing]  saves the rows that pass and leaves out the rest.
// Changing any field hides both buttons until the next preview, so what is saved is what was
// seen. Words come from the form: data-text-summary ("{passed} … {failed} …"),
// data-text-ok, data-text-failed, data-text-save ("{count}"), data-text-save-passing.

import { ApiError, api } from "./api.js";
import { clearErrors, formBody, showErrors } from "./forms.js";
import { busy, startNavigation } from "./loading.js";
import { flash, strings, toast } from "./ui.js";

function fill(text, values) {
  return (text || "").replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");
}

function badge(text, kind) {
  const node = document.createElement("span");
  node.className = `badge badge-${kind}`;
  node.textContent = text;
  return node;
}

function notes(row) {
  const list = document.createElement("ul");
  list.className = "space-y-0.5 text-xs";
  for (const [messages, tone] of [[row.errors, "text-red-700"], [row.warnings, "text-amber-700"]]) {
    for (const message of messages) {
      const item = document.createElement("li");
      item.className = tone;
      item.textContent = message;
      list.append(item);
    }
  }
  return list;
}

function render(form, outcome) {
  const text = form.dataset;
  const result = form.querySelector("[data-bulk-result]");
  const body = form.querySelector("[data-bulk-rows]");
  const template = form.querySelector("template[data-bulk-row]");
  body.replaceChildren(...outcome.rows.map((row) => {
    const line = template.content.firstElementChild.cloneNode(true);
    const slot = (name) => line.querySelector(`[data-slot="${name}"]`);
    slot("name").textContent = row.code ? `${row.code} · ${row.name}` : row.name;
    slot("detail").textContent = row.detail;
    slot("status").replaceChildren(row.ok ? badge(text.textOk, row.warnings.length ? "warning" : "success")
                                          : badge(text.textFailed, "danger"));
    slot("notes").replaceChildren(notes(row));
    return line;
  }));
  form.querySelector("[data-bulk-summary]").textContent = fill(text.textSummary, outcome);
  const all = form.querySelector("[data-bulk-save]");
  const passing = form.querySelector("[data-bulk-save-passing]");
  all.hidden = outcome.failed > 0 || outcome.passed === 0;
  all.textContent = fill(text.textSave, { count: outcome.passed });
  passing.hidden = !(outcome.failed > 0 && outcome.passed > 0);
  passing.textContent = fill(text.textSavePassing, { count: outcome.passed });
  result.hidden = false;
  result.classList.remove("opacity-50");
}

function stale(form) {
  const result = form.querySelector("[data-bulk-result]");
  if (result.hidden) return;
  result.classList.add("opacity-50");
  form.querySelectorAll("[data-bulk-save], [data-bulk-save-passing]").forEach((b) => (b.hidden = true));
}

async function send(form, button, options) {
  clearErrors(form);
  const done = busy(button);
  try {
    const outcome = await api(form.dataset.endpoint, { method: "POST", body: { ...formBody(form), ...options } });
    if (!options.save) {
      render(form, outcome);
      done();
      return;
    }
    flash(fill(form.dataset.success, { count: outcome.saved }));
    const next = form.dataset.redirect || window.location.href;
    startNavigation(next);
    window.location.assign(next);
  } catch (error) {
    done();
    if (!(error instanceof ApiError)) {
      toast(strings().network, { kind: "error" });
      return;
    }
    if (error.details) render(form, error.details); // saving refused: the rows say why
    showErrors(form, error);
  }
}

export function initBulkForms() {
  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-bulk-form]");
    if (!form) return;
    event.preventDefault();
    send(form, event.submitter || form.querySelector('[type="submit"]'), { save: false });
  });
  document.addEventListener("click", (event) => {
    const rows = event.target.closest("[data-add-row], [data-remove-row]");
    if (rows?.closest("form[data-bulk-form]")) stale(rows.closest("form[data-bulk-form]"));
    const button = event.target.closest("[data-bulk-save], [data-bulk-save-passing]");
    const form = button?.closest("form[data-bulk-form]");
    if (!form) return;
    event.preventDefault();
    send(form, button, { save: true, skip_failed: button.hasAttribute("data-bulk-save-passing") });
  });
  for (const type of ["input", "change"]) {
    document.addEventListener(type, (event) => {
      const form = event.target.closest?.("form[data-bulk-form]");
      if (form) stale(form);
    });
  }
}
