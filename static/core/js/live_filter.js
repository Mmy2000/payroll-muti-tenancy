// Search and filters that answer as you type: <form method="get" data-live-filter>.
//
// The page is fetched again with the form's values and everything around the form is replaced
// with the new page's, so the results, totals, tabs and pager all stay right, through the same
// view and the same permission checks as a normal visit. The form itself stays in place: the
// cursor and what is being typed are not disturbed. The address follows, so a reload or a shared
// link shows the same list. Without this script the form still works by its Show button.
import { later, refreshing } from "./loading.js";
import { initPrintTables } from "./print_table.js";
import { enhanceSelects, initDependentSelects } from "./selects.js";

const TYPING_PAUSE = 300; // ms after the last key, so one word is one request
const SHOW_BUSY_AFTER = 120;
const TYPED = new Set(["text", "search"]);

let inFlight = null;
const shown = new WeakMap(); // form → the query its results are for

function urlOf(form) {
  // As the browser would send it: an empty choice stays in, it means "all" over a default.
  const query = new URLSearchParams(new FormData(form)).toString();
  return `${window.location.pathname}?${query}`;
}

/** Replace everything around `keep`, up to `stop`, with what surrounds its `twin`. */
function swapAround(keep, twin, stop) {
  while (keep !== stop) {
    const parent = keep.parentElement;
    const nodes = [...twin.parentElement.childNodes];
    const at = nodes.indexOf(twin);
    [...parent.childNodes].forEach((node) => node !== keep && node.remove());
    keep.before(...nodes.slice(0, at));
    keep.after(...nodes.slice(at + 1));
    keep = parent;
    twin = twin.parentElement;
  }
}

function replaceFreshParts(form, next) {
  const fresh = next.querySelectorAll("[data-live-fresh]");
  form.querySelectorAll("[data-live-fresh]").forEach((node, index) => {
    if (fresh[index]) node.replaceWith(fresh[index]);
  });
}

function show(form, html) {
  const main = form.closest("main");
  const nextDocument = new DOMParser().parseFromString(html, "text/html");
  const next = nextDocument.querySelector("form[data-live-filter]");
  const nextMain = nextDocument.querySelector("main");
  if (!main || !next || !nextMain) return false;
  main.querySelectorAll("select.tomselected").forEach((select) => {
    if (!form.contains(select)) select.tomselect?.destroy(); // their menus live on <body>
  });
  replaceFreshParts(form, next);
  swapAround(form, next, main);
  enhanceSelects(main);
  initDependentSelects(main);
  initPrintTables();
  return true;
}

async function refresh(form) {
  const url = urlOf(form);
  shown.set(form, url);
  inFlight?.abort();
  const request = new AbortController();
  inFlight = request;
  const idle = later(() => refreshing([...form.closest("main").querySelectorAll("table, article")]),
    SHOW_BUSY_AFTER);
  try {
    const response = await fetch(url, { signal: request.signal, credentials: "same-origin" });
    // Signed out, or anything unexpected: a normal visit shows it properly.
    if (!response.ok || response.redirected) throw new Error(String(response.status));
    if (!show(form, await response.text())) throw new Error("no results on the page");
    window.history.replaceState(window.history.state, "", url);
  } catch (error) {
    if (error.name !== "AbortError") window.location.assign(url);
  } finally {
    idle();
    if (inFlight === request) inFlight = null;
  }
}

export function initLiveFilters() {
  let pause = null;
  const liveForm = (node) => node.closest?.("form[data-live-filter]");

  document.querySelectorAll("form[data-live-filter]").forEach((form) => {
    form.classList.add("is-live");
    shown.set(form, urlOf(form));
  });
  document.addEventListener("input", (event) => {
    const form = liveForm(event.target);
    if (!form || !TYPED.has(event.target.type) || !event.target.name || event.isComposing) return;
    clearTimeout(pause);
    pause = setTimeout(() => refresh(form), TYPING_PAUSE);
  });
  document.addEventListener("change", (event) => {
    const form = liveForm(event.target);
    if (!form || !event.target.name) return;
    clearTimeout(pause);
    if (urlOf(form) !== shown.get(form)) refresh(form);
  });
  document.addEventListener("submit", (event) => {
    const form = liveForm(event.target);
    if (!form) return;
    event.preventDefault();
    clearTimeout(pause);
    refresh(form);
  });
}
