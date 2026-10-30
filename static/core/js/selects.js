// Every <select> becomes searchable (Tom Select, loaded as window.TomSelect before this module).
//
//   <select>                         searchable list of its own options
//   <select data-native>             left as a browser select (avoid: it ignores the theme)
//   <select data-remote="/api/web/parties/customers/" data-label-field="name">
//                                    options come from the API (?q=… search, first page)
//
// Selects with an empty option get a clear button. The original <select> keeps its value, so
// forms (including data-api-form) read it as before.
//
// filterOptions(select, keep) narrows a local select to the options `keep(option)` accepts
// (e.g. cash boxes of the chosen branch and currency); the empty option always stays.

import { api } from "./api.js";
import { strings } from "./ui.js";

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function remoteOptions(select) {
  const labelField = select.dataset.labelField || "name";
  return {
    valueField: "id",
    labelField,
    searchField: [labelField],
    preload: "focus",
    shouldLoad: () => true,
    load(query, callback) {
      const url = select.dataset.remote; // read each time: a form may point it elsewhere
      const separator = url.includes("?") ? "&" : "?";
      api(`${url}${separator}q=${encodeURIComponent(query)}&page_size=20`)
        .then((data) => callback(data.results || data))
        .catch(() => callback());
    },
  };
}

export function enhanceSelects(root = document) {
  const TomSelect = window.TomSelect;
  if (!TomSelect) return;
  const ui = strings();

  root.querySelectorAll("select:not([data-native]):not(.tomselected)").forEach((select) => {
    const nullable = Boolean(select.querySelector('option[value=""]')) || select.dataset.remote;
    const plugins = select.multiple ? { remove_button: { title: ui.clear || "×" } } : { dropdown_input: {} };
    if (nullable && !select.multiple) plugins.clear_button = { title: ui.clear || "×", html: (data) => `<div class="${data.className}" title="${escapeHtml(data.title)}">×</div>` };

    const options = {
      plugins,
      allowEmptyOption: true,
      maxOptions: null,
      create: false,
      refreshThrottle: select.dataset.remote ? 300 : 0, // local lists filter as you type
      dropdownParent: "body",
      placeholder: select.dataset.placeholder || "",
      render: {
        no_results: () => `<div class="no-results">${escapeHtml(ui.no_results || "No results")}</div>`,
        loading: () => `<div class="loading flex items-center gap-2"><span class="busy-spinner size-3.5" aria-hidden="true"></span>${escapeHtml(ui.loading || "…")}</div>`,
      },
      onInitialize() {
        const input = this.dropdown.querySelector(".dropdown-input");
        if (input) input.placeholder = ui.search || "";
      },
      ...(select.dataset.remote ? remoteOptions(select) : {}),
    };
    const control = new TomSelect(select, options);
    keepInSync(select, control);
    // Mirror server-side validation state (forms.js sets aria-invalid on the <select>).
    new MutationObserver(() => {
      if (select.getAttribute("aria-invalid") === "true") control.wrapper.setAttribute("aria-invalid", "true");
      else control.wrapper.removeAttribute("aria-invalid");
    }).observe(select, { attributes: true, attributeFilter: ["aria-invalid"] });
  });
}

// Scripts set `select.value = …` (a group's next code, a branch's default…): the enhanced
// control follows, so every select can be enhanced and keep working with plain DOM code.
const NATIVE_VALUE = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");

function keepInSync(select, control) {
  let syncing = false;
  Object.defineProperty(select, "value", {
    configurable: true,
    get() {
      return NATIVE_VALUE.get.call(this);
    },
    set(value) {
      NATIVE_VALUE.set.call(this, value);
      if (syncing) return;
      syncing = true;
      try {
        control.setValue(value, true);
      } finally {
        syncing = false;
      }
    },
  });
}

export function filterOptions(select, keep) {
  if (!select._allOptions) {
    select._allOptions = [...select.querySelectorAll("option")].map((node) => ({ node, parent: node.parentElement }));
  }
  const value = select.value;
  select._allOptions.forEach(({ node }) => node.remove());
  select._allOptions.forEach(({ node, parent }) => {
    if (node.value === "" || keep(node)) parent.appendChild(node);
  });
  const stillThere = [...select.options].some((option) => option.value === value);
  select.value = stillThere ? value : (select.querySelector('option[value=""]') ? "" : select.options[0]?.value ?? "");
  const control = select.tomselect;
  if (control) {
    control.clearOptions();
    control.sync();
    control.setValue(select.value, true);
  }
  return select.options.length;
}

// <select data-depends-on="branch_id"> with <option data-parent="…">: locked, with an empty option
// saying what to choose first, until the form's field "branch_id" has a value; then only the
// options of that value. A choice that no longer fits is cleared. With no such field (a client
// with one branch has no branch to choose) every option stays open.
function lock(select, locked) {
  const empty = select.querySelector('option[value=""]');
  if (empty) {
    empty.dataset.openText ??= empty.textContent;
    empty.textContent = locked ? strings().choose_branch_first : empty.dataset.openText;
    select.tomselect?.updateOption("", { ...select.tomselect.options[""], text: empty.textContent });
  }
  select.dataset.locked = locked ? "true" : ""; // reveal.js leaves a locked select disabled
  if (select.tomselect) select.tomselect[locked ? "disable" : "enable"]();
  else select.disabled = locked;
}

export function initDependentSelects(root = document) {
  root.querySelectorAll("select[data-depends-on]").forEach((select) => {
    const parent = select.form?.elements.namedItem(select.dataset.dependsOn);
    if (!parent) return;
    // A choice from the address or the saved record brings its parent with it.
    const chosen = select.selectedOptions[0]?.dataset.parent;
    if (chosen && !parent.value) parent.value = chosen;
    const narrow = () => {
      filterOptions(select, (option) => option.dataset.parent === parent.value);
      lock(select, !parent.value);
    };
    parent.addEventListener("change", narrow);
    narrow();
  });
}
