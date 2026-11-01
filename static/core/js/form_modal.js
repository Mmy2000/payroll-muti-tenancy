// Create and edit without leaving the page: <a href="/people/new/" data-form-modal> shows that page's
// form in a modal. The page itself stays the source of the form, its rules and its permissions, and
// still opens by itself (a new tab, or no script). A page without a JSON form just opens as usual.
//
// After saving, data-form-modal says what happens:
//   ""       the page reloads (the default)
//   "follow" go on to where the form leads, for a new record whose next step is on its own page
//   "stay"   nothing reloads: the page hears "form-modal:saved" on window and updates itself

import { formBody } from "./forms.js";
import { startNavigation } from "./loading.js";
import { revealForm } from "./reveal.js";
import { enhanceSelects, initDependentSelects } from "./selects.js";
import { flash, toast } from "./ui.js";

const box = document.querySelector("[data-modal]");
const backdrop = document.querySelector("[data-modal-backdrop]");
const shell = document.querySelector("[data-shell]");

let current = null; // {form, url, mode, untouched, returnTo}
let opening = 0; // the latest request: a form that arrives after closing is dropped

const part = (name) => box.querySelector(`[data-modal-${name}]`);

function show() {
  box.hidden = false;
  backdrop.hidden = false;
  shell.inert = true;
  document.documentElement.classList.add("overflow-hidden");
}

function close() {
  opening += 1;
  box.hidden = true;
  backdrop.hidden = true;
  shell.inert = false;
  document.documentElement.classList.remove("overflow-hidden");
  part("guard").hidden = true;
  part("form").replaceChildren();
  current?.returnTo?.focus({ preventScroll: true });
  current = null;
}

const touched = () => current && JSON.stringify(formBody(current.form)) !== current.untouched;

function askToClose() {
  if (touched()) part("guard").hidden = false;
  else close();
}

async function fetchPage(url) {
  const response = await fetch(url, { headers: { Accept: "text/html" } });
  if (!response.ok || response.redirected) return null;
  return new DOMParser().parseFromString(await response.text(), "text/html");
}

// A page's own script may shape its form. A module runs once, so what is loaded is left alone.
function loadScripts(page) {
  const sources = [...page.querySelectorAll('head script[type="module"][src]')];
  return Promise.all(sources.map((script) => import(new URL(script.getAttribute("src"), location.href).href)));
}

// The buttons stay in reach under a long form, and Cancel closes instead of leaving.
function placeActions(form) {
  const actions = form.querySelector('[type="submit"]').parentElement;
  actions.classList.add("modal-actions");
  form.append(actions);
  actions.querySelector("a")?.addEventListener("click", (event) => {
    event.preventDefault();
    askToClose();
  });
}

function prepare(form) {
  enhanceSelects(form);
  initDependentSelects(form);
  revealForm(form);
  form.dispatchEvent(new CustomEvent("form:opened", { bubbles: true }));
}

function focusFirst(form) {
  const first = form.querySelector("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea");
  if (first?.tomselect) first.tomselect.focus();
  else first?.focus({ preventScroll: true });
}

export async function openFormModal(url, { mode = "", returnTo = null } = {}) {
  const request = (opening += 1);
  part("title").textContent = "";
  part("form").replaceChildren();
  part("full").href = url;
  part("loading").hidden = false;
  show();
  let page = null;
  try {
    page = await fetchPage(url);
    if (page) await loadScripts(page);
  } catch {
    page = null;
  }
  if (request !== opening) return;
  const form = page?.querySelector("main form[data-api-form]");
  if (!form?.querySelector('[type="submit"]')) {
    location.assign(url); // nothing to show here: the page itself knows what to do
    return;
  }
  part("loading").hidden = true;
  part("title").textContent = page.querySelector("h1")?.textContent.trim() ?? "";
  part("form").replaceChildren(document.adoptNode(form));
  placeActions(form);
  prepare(form);
  focusFirst(form);
  current = { form, url, mode, returnTo, untouched: JSON.stringify(formBody(form)) };
}

function saved(event) {
  const { form, mode } = current;
  if (event.target !== form) return;
  event.preventDefault();
  const message = form.dataset.success ?? "";
  const { data } = event.detail;
  close();
  if (mode === "stay") {
    toast(message);
    window.dispatchEvent(new CustomEvent("form-modal:saved", { detail: { data } }));
    return;
  }
  const next = mode === "follow" && form.dataset.redirect
    ? form.dataset.redirect.replace("{id}", data?.id) : location.href;
  flash(message);
  startNavigation(next);
  if (mode === "follow") location.assign(next);
  else location.reload();
}

export function initFormModals() {
  if (!box) return;
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-form-modal]");
    const newTab = event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0;
    if (!link || newTab || !box.hidden) return;
    event.preventDefault();
    openFormModal(link.href, { mode: link.dataset.formModal, returnTo: link });
  });
  box.addEventListener("form:saved", saved);
  backdrop.addEventListener("click", askToClose);
  part("close").addEventListener("click", askToClose);
  part("keep").addEventListener("click", () => { part("guard").hidden = true; });
  part("discard").addEventListener("click", close);
  // Before anything else hears it: an open list or calendar takes Escape for itself.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || box.hidden) return;
    if (!document.querySelector(".ts-wrapper.dropdown-active, .picker-panel:not([hidden])")) askToClose();
  }, true);
}
