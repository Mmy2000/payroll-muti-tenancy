// Hover for the server-drawn columns and bars (components/column_chart.html, bar_chart.html):
// the mark's name and value in a tooltip by the pointer. Each mark's hit area is its whole band,
// so a thin or short mark is as easy to reach as a tall one. Keyboard and screen readers have
// the table under each chart.

function place(figure, tip, event) {
  const box = figure.getBoundingClientRect();
  const x = event.clientX - box.left;
  const y = event.clientY - box.top;
  tip.style.left = `${Math.min(Math.max(x + 12, 0), box.width - tip.offsetWidth)}px`;
  tip.style.top = `${Math.max(y - tip.offsetHeight - 10, 0)}px`;
}

export function initBars() {
  document.addEventListener("pointermove", (event) => {
    const mark = event.target.closest?.("[data-viz] [data-mark]");
    document.querySelectorAll("[data-viz-tip]:not(.hidden)").forEach((tip) => {
      if (!mark || !tip.closest("[data-viz]").contains(mark)) tip.classList.add("hidden");
    });
    if (!mark) return;
    const figure = mark.closest("[data-viz]");
    const tip = figure.querySelector("[data-viz-tip]");
    tip.replaceChildren();
    const title = document.createElement("span");
    title.className = "block text-slate-500";
    title.textContent = mark.dataset.title;
    const value = document.createElement("span");
    value.className = "block font-semibold text-slate-900 num";
    value.textContent = mark.dataset.value;
    tip.append(title, value);
    tip.classList.remove("hidden");
    place(figure, tip, event);
  });
}
