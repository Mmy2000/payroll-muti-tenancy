// The small pieces the company structure page is built from.

export function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

export function icon(name) {
  return document.querySelector(`template[data-icon="${name}"]`).content.cloneNode(true);
}

export function badge(text, tone = "neutral") {
  return el("span", `badge badge-${tone}`, text);
}
