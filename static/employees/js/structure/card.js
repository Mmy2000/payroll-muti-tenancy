// One card on the canvas.
import { avatar, badge, el, icon } from "./dom.js";
import { branchById, state, words } from "./store.js";

const GLYPHS = { company: "building-2", branch: "store", department: "users-round", none: "triangle-alert" };

function outputPort(item) {
  if (item.kind === "branch" && item.branch.can_manage_departments) {
    const add = el("button", "flow-port flow-port-out flow-port-add");
    add.type = "button";
    add.tabIndex = -1;
    add.dataset.port = "out";
    add.title = words.add_department;
    add.setAttribute("aria-label", words.add_department);
    add.append(icon("plus"));
    return add;
  }
  return item.children.length ? el("span", "flow-port flow-port-out") : null;
}

function inputPort(item) {
  const port = el("span", "flow-port flow-port-in");
  if (item.kind === "department" && item.canCarry) {
    port.classList.add("is-live");
    port.dataset.port = "in";
    port.title = words.move_department;
  }
  return port;
}

function elsewhere(item) {
  const others = item.department.branch_ids.filter((id) => id !== item.branch.id);
  if (!others.length) return null;
  const tag = el("span", "flow-tag num", `+${others.length}`);
  tag.title = `${words.also_in}: ${others.map((id) => branchById(id)?.name).filter(Boolean).join(" · ")}`;
  return tag;
}

function toggle(item) {
  const button = el("button", `org-toggle${item.open ? " is-open" : ""}`);
  button.type = "button";
  button.tabIndex = -1;
  button.dataset.toggle = "";
  button.setAttribute("aria-hidden", "true");
  button.append(icon("chevron-down"));
  return button;
}

function checkbox(item) {
  const box = el("input", "org-check");
  box.type = "checkbox";
  box.tabIndex = -1;
  box.checked = state.checked.has(item.person.id);
  box.setAttribute("aria-label", item.label);
  box.dataset.check = "";
  return box;
}

function placeholder(item) {
  const card = el(item.kind === "hint" ? "div" : "button", `flow-node flow-node-${item.kind}`, item.label);
  card.dataset.key = item.key;
  if (item.kind !== "hint") {
    card.type = "button";
    card.tabIndex = -1;
  }
  if (item.kind === "more") card.append(el("span", "org-count num", String(item.count)));
  if (item.kind === "add") card.prepend(icon("plus"));
  card.prepend(inputPort(item));
  return card;
}

// How much of the level above is here: a thin line along the foot of the card.
function shareLine(share) {
  const line = el("span", "flow-share");
  const fill = el("span");
  fill.style.width = `${Math.round(share * 100)}%`;
  line.append(fill);
  return line;
}

function mark(item) {
  if (item.kind === "employee") return avatar(item.label);
  const tile = el("span", `flow-tile flow-tile-${item.kind}`);
  tile.append(icon(GLYPHS[item.kind]));
  return tile;
}

export function drawCard(item, { selected = false, twin = false } = {}) {
  if (["hint", "more", "add"].includes(item.kind)) return placeholder(item);
  const card = el("div", `flow-node flow-node-${item.kind}`);
  card.dataset.key = item.key;
  card.tabIndex = -1;
  card.setAttribute("role", "treeitem");
  card.setAttribute("aria-level", String(item.depth + 1));
  card.setAttribute("aria-label", item.label);
  card.setAttribute("aria-selected", String(selected));
  if (item.open !== undefined) card.setAttribute("aria-expanded", String(item.open));
  card.classList.toggle("is-selected", selected);
  card.classList.toggle("is-twin", twin);
  card.classList.toggle("is-inactive", Boolean(item.inactive));
  if (item.kind === "employee" && item.canCarry) card.append(checkbox(item));

  const text = el("span", "min-w-0 flex-1");
  text.append(el("span", "org-name font-medium text-slate-900", item.label));
  if (item.sub) text.append(el("span", "org-sub", item.sub));
  card.append(mark(item), text);

  if (item.inactive) card.append(badge(words.inactive));
  if (item.kind === "department") {
    const tag = elsewhere(item);
    if (tag) card.append(tag);
  }
  if (item.count !== undefined) card.append(el("span", "org-count num", String(item.count)));
  if (item.open !== undefined) card.append(toggle(item));
  if (item.share !== undefined) card.append(shareLine(item.share));
  if (item.kind !== "company") card.append(inputPort(item));
  const output = outputPort(item);
  if (output) card.append(output);
  return card;
}
