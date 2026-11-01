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

// A person's initials. Arabic joins its letters, so one reads better than two run together.
function initials(name) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = Array.from(parts[0] ?? "?")[0];
  if (/[\u0600-\u06FF]/.test(first)) return first;
  return (first + (parts.length > 1 ? Array.from(parts[1])[0] : "")).toUpperCase();
}

export function avatar(name, className = "") {
  const face = el("span", `flow-avatar ${className}`.trim(), initials(name));
  face.setAttribute("aria-hidden", "true");
  return face;
}

export function badge(text, tone = "neutral") {
  return el("span", `badge badge-${tone}`, text);
}
