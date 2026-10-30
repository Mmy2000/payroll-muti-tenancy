// Date, month and time pickers in the system's own look, for every <input type="date|month|time">.
//
// The real input stays in the form, hidden, and keeps sending what it always sent (2026-10-30,
// 2026-10, 09:30); a text box beside it shows and takes the value the way people write it
// (30/10/2026), so a date can still be typed. One panel serves every field on the page, which
// keeps a table of sixty time boxes light. Each kind of field is a strategy below: how it reads,
// writes and draws its value.

const MINUTE_STEP = 5;
const ICONS = {
  date: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  month: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18M8 14h.01M12 14h.01M16 14h.01"/>',
  time: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  forward: '<path d="m9 18 6-6-6-6"/>',
};

const pad = (number) => String(number).padStart(2, "0");
const svg = (name, size = 16) => `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}"
  viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
const westernDigits = (text) => text.trim()
  .replace(/[٠-٩]/g, (digit) => "٠١٢٣٤٥٦٧٨٩".indexOf(digit))
  .replace(/[۰-۹]/g, (digit) => "۰۱۲۳۴۵۶۷۸۹".indexOf(digit));
const locale = () => `${document.documentElement.lang || "en"}-u-nu-latn-ca-gregory`;
const isRtl = () => document.documentElement.dir === "rtl";
const words = () => document.getElementById("picker-strings")?.dataset ?? {};
const today = () => new Date();
const isoDate = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const isoMonth = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}`;

function realDate(year, month, day) {
  const date = new Date(year, month - 1, day);
  return date.getMonth() === month - 1 && date.getDate() === day ? isoDate(date) : null;
}

function fromIso(value) {
  const [year, month, day = 1] = (value || "").split("-").map(Number);
  return year && month ? new Date(year, month - 1, day) : null;
}

function button(className, label, onPick) {
  const node = document.createElement("button");
  node.type = "button";
  node.tabIndex = -1;
  node.className = className;
  node.innerHTML = label;
  node.addEventListener("click", onPick);
  return node;
}

function heading(panel, title, onTitle, onStep) {
  const row = document.createElement("div");
  row.className = "picker-head";
  const [back, forward] = isRtl() ? ["forward", "back"] : ["back", "forward"];
  row.append(button("picker-step", svg(back), () => onStep(-1)),
    button("picker-title", title, onTitle), button("picker-step", svg(forward), () => onStep(1)));
  return row;
}

function monthNames() {
  const format = new Intl.DateTimeFormat(locale(), { month: "long" });
  return Array.from({ length: 12 }, (_, month) => format.format(new Date(2026, month, 1)));
}

function monthGrid(panel, year, chosen, onPick) {
  const grid = document.createElement("div");
  grid.className = "picker-months";
  monthNames().forEach((name, index) => {
    const value = `${year}-${pad(index + 1)}`;
    const node = button("picker-month", name, () => onPick(value));
    node.disabled = !panel.field.allows(`${value}-31`, `${value}-01`);
    node.toggleAttribute("data-selected", chosen === value);
    node.toggleAttribute("data-today", isoMonth(today()) === value);
    grid.append(node);
  });
  return grid;
}

// --- the strategies ----------------------------------------------------------------------------

const dateKind = {
  placeholder: "dd/mm/yyyy",
  icon: "date",
  now: () => isoDate(today()),
  nowLabel: () => words().today,
  show: (value) => {
    const [year, month, day] = value.split("-");
    return day ? `${day}/${month}/${year}` : "";
  },
  read(text) {
    let found = text.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/);
    if (found) return realDate(+found[1], +found[2], +found[3]);
    found = text.match(/^(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2}|\d{4}))?$/) || text.match(/^(\d{2})(\d{2})(\d{4})$/);
    if (!found) return null;
    const year = found[3] ? +found[3] + (found[3].length === 2 ? 2000 : 0) : today().getFullYear();
    return realDate(year, +found[2], +found[1]);
  },
  start(panel) {
    panel.cursor = fromIso(panel.field.value) || today();
    panel.mode = "days";
  },
  move(panel, step) {
    const next = new Date(panel.cursor);
    next.setDate(next.getDate() + step);
    panel.cursor = next;
    panel.render();
  },
  keys: { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 },
  pickCursor: (panel) => panel.pick(isoDate(panel.cursor)),
  draw(panel) {
    if (panel.mode === "months") return this.drawMonths(panel);
    const { cursor } = panel;
    const shift = (months) => {
      panel.cursor = new Date(cursor.getFullYear(), cursor.getMonth() + months, 1);
      panel.render();
    };
    const title = new Intl.DateTimeFormat(locale(), { month: "long", year: "numeric" }).format(cursor);
    const toMonths = () => { panel.mode = "months"; panel.render(); };

    const grid = document.createElement("div");
    grid.className = "picker-days";
    const firstDay = Number(words().firstDay ?? 6);
    const weekday = new Intl.DateTimeFormat(locale(), { weekday: "short" });
    for (let index = 0; index < 7; index += 1) {
      const name = document.createElement("span");
      name.className = "picker-weekday";
      name.textContent = weekday.format(new Date(2023, 0, 1 + ((firstDay + index) % 7)));
      grid.append(name);
    }
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const lead = (first.getDay() - firstDay + 7) % 7;
    for (let offset = -lead; offset < 42 - lead; offset += 1) {
      const day = new Date(first.getFullYear(), first.getMonth(), 1 + offset);
      const value = isoDate(day);
      const node = button("picker-day", String(day.getDate()), () => panel.pick(value));
      node.disabled = !panel.field.allows(value, value);
      node.toggleAttribute("data-outside", day.getMonth() !== first.getMonth());
      node.toggleAttribute("data-today", value === isoDate(today()));
      node.toggleAttribute("data-selected", value === panel.field.value);
      node.toggleAttribute("data-cursor", value === isoDate(cursor));
      grid.append(node);
    }
    return [heading(panel, title, toMonths, shift), grid];
  },
  drawMonths(panel) {
    const year = panel.cursor.getFullYear();
    const step = (years) => {
      panel.cursor = new Date(year + years, panel.cursor.getMonth(), 1);
      panel.render();
    };
    const open = (value) => {
      panel.cursor = fromIso(value);
      panel.mode = "days";
      panel.render();
    };
    return [heading(panel, String(year), () => {}, step),
      monthGrid(panel, year, isoMonth(panel.cursor), open)];
  },
};

const monthKind = {
  placeholder: "mm/yyyy",
  icon: "month",
  now: () => isoMonth(today()),
  nowLabel: () => words().thisMonth,
  show: (value) => {
    const [year, month] = value.split("-");
    return month ? `${month}/${year}` : "";
  },
  read(text) {
    const iso = text.match(/^(\d{4})[-/.](\d{1,2})$/);
    const written = text.match(/^(\d{1,2})[-/.](\d{4})$/);
    const [year, month] = iso ? [+iso[1], +iso[2]] : written ? [+written[2], +written[1]] : [0, 0];
    return month >= 1 && month <= 12 ? `${year}-${pad(month)}` : null;
  },
  start(panel) {
    panel.cursor = fromIso(panel.field.value) || today();
  },
  move(panel, step) {
    panel.cursor = new Date(panel.cursor.getFullYear(), panel.cursor.getMonth() + step, 1);
    panel.render();
  },
  keys: { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -3, ArrowDown: 3 },
  pickCursor: (panel) => panel.pick(isoMonth(panel.cursor)),
  draw(panel) {
    const year = panel.cursor.getFullYear();
    const step = (years) => {
      panel.cursor = new Date(year + years, panel.cursor.getMonth(), 1);
      panel.render();
    };
    return [heading(panel, String(year), () => {}, step),
      monthGrid(panel, year, panel.field.value, (value) => panel.pick(value))];
  },
};

const timeKind = {
  placeholder: "--:--",
  icon: "time",
  now: () => `${pad(today().getHours())}:${pad(today().getMinutes())}`,
  nowLabel: () => words().now,
  show: (value) => value.slice(0, 5),
  read(text) {
    const found = text.match(/^(\d{1,2})(?:[:.](\d{1,2}))?(?::\d{1,2})?$/) || text.match(/^(\d{1,2})(\d{2})$/);
    if (!found) return null;
    const [hours, minutes] = [+found[1], +(found[2] ?? 0)];
    return hours < 24 && minutes < 60 ? `${pad(hours)}:${pad(minutes)}` : null;
  },
  start() {},
  move() {},
  keys: {},
  pickCursor: (panel) => panel.close(),
  draw(panel) {
    const [hour = "", minute = ""] = (panel.field.value || "").split(":");
    const column = (values, chosen, label, onPick) => {
      const list = document.createElement("div");
      list.className = "picker-column";
      list.setAttribute("aria-label", label);
      for (const value of values) {
        const node = button("picker-time", value, () => onPick(value));
        node.toggleAttribute("data-selected", value === chosen);
        list.append(node);
      }
      return list;
    };
    const minutes = Array.from({ length: 60 / MINUTE_STEP }, (_, index) => pad(index * MINUTE_STEP));
    if (minute && !minutes.includes(minute)) minutes.push(minute);
    minutes.sort();
    const hours = column(Array.from({ length: 24 }, (_, index) => pad(index)), hour, words().hours ?? "",
      (value) => panel.field.set(`${value}:${minute || "00"}`));
    const mins = column(minutes, minute, words().minutes ?? "",
      (value) => panel.pick(`${hour || "00"}:${value}`));
    const columns = document.createElement("div");
    columns.className = "picker-columns";
    columns.append(hours, mins);
    requestAnimationFrame(() => columns.querySelectorAll("[data-selected]")
      .forEach((node) => node.parentElement.scrollTo({ top: node.offsetTop - 72 })));
    return [columns];
  },
};

const KINDS = { date: dateKind, month: monthKind, time: timeKind };

// --- one field ---------------------------------------------------------------------------------

const NATIVE_VALUE = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
// Layout classes belong on the wrapper; the look stays on the text box.
const LAYOUT = /^(?:[a-z0-9-]+:)*(?:w-|min-w-|max-w-|flex-|grow|shrink|col-span|self-|m[stbexy]?-)/;

class Field {
  constructor(input) {
    this.input = input;
    this.kind = KINDS[input.type];
    const classes = input.className.split(/\s+/).filter(Boolean);

    this.box = document.createElement("input");
    this.box.type = "text";
    this.box.className = `${classes.filter((name) => !LAYOUT.test(name)).join(" ")} picker-input`;
    this.box.placeholder = this.kind.placeholder;
    this.box.autocomplete = "off";
    this.box.inputMode = "numeric";
    this.box.dir = "ltr";
    this.box.setAttribute("aria-haspopup", "dialog");
    for (const name of ["aria-label", "title", "required", "aria-invalid"]) {
      if (input.hasAttribute(name)) this.box.setAttribute(name, input.getAttribute(name));
    }
    if (input.id) {
      this.box.id = input.id; // labels point at what people use
      input.removeAttribute("id");
    }
    this.box.disabled = input.disabled;

    const wrapper = document.createElement("span");
    wrapper.className = `picker ${classes.filter((name) => LAYOUT.test(name)).join(" ")}`;
    const toggle = button("picker-toggle", svg(this.kind.icon), () => this.box.focus());
    toggle.setAttribute("aria-hidden", "true");
    input.before(wrapper);
    wrapper.append(this.box, toggle, input);
    input.type = "hidden";
    input.dataset.picker = "";

    Object.defineProperty(input, "value", {
      configurable: true,
      get: () => NATIVE_VALUE.get.call(input),
      set: (value) => {
        NATIVE_VALUE.set.call(input, value);
        this.showValue();
      },
    });
    input.focus = () => this.box.focus(); // a failed save brings the cursor to the first error
    new MutationObserver(() => {
      this.box.disabled = input.disabled;
      if (input.hasAttribute("aria-invalid")) this.box.setAttribute("aria-invalid", input.getAttribute("aria-invalid"));
      else this.box.removeAttribute("aria-invalid");
    }).observe(input, { attributes: true, attributeFilter: ["disabled", "aria-invalid"] });

    this.showValue();
    this.box.addEventListener("click", () => panel.open(this));
    toggle.addEventListener("click", () => panel.open(this));
    this.box.addEventListener("keydown", (event) => this.keydown(event));
    this.box.addEventListener("blur", () => {
      this.commit();
      panel.close();
    });
  }

  get value() {
    return NATIVE_VALUE.get.call(this.input);
  }

  showValue() {
    this.box.value = this.value ? this.kind.show(this.value) : "";
  }

  allows(last, first) {
    const { min, max } = this.input;
    return !((min && last < min) || (max && first > max));
  }

  /** A new value: the form hears about it as if the real input had changed. */
  set(value) {
    const changed = value !== this.value;
    NATIVE_VALUE.set.call(this.input, value);
    this.showValue();
    if (panel.field === this) panel.render();
    if (changed) {
      this.input.dispatchEvent(new Event("input", { bubbles: true }));
      this.input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  /** What was typed: taken if it reads as a value, otherwise the box goes back. */
  commit() {
    const text = westernDigits(this.box.value);
    const value = text ? this.kind.read(text) : "";
    if (value === null) this.showValue();
    else if (value !== this.value) this.set(value);
    else this.showValue();
  }

  keydown(event) {
    const open = panel.field === this;
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      panel.close();
    } else if (event.key === "Enter") {
      if (open && !this.typed()) {
        event.preventDefault();
        this.kind.pickCursor(panel);
      } else {
        this.commit();
        panel.close();
      }
    } else if (event.key === "ArrowDown" && !open) {
      event.preventDefault();
      panel.open(this);
    } else if (open && event.key in this.kind.keys) {
      event.preventDefault();
      const step = this.kind.keys[event.key];
      this.kind.move(panel, isRtl() && event.key.match(/Left|Right/) ? -step : step);
    }
  }

  typed() {
    return westernDigits(this.box.value) !== (this.value ? this.kind.show(this.value) : "");
  }
}

// --- the one panel -----------------------------------------------------------------------------

class Panel {
  constructor() {
    this.field = null;
    this.node = document.createElement("div");
    this.node.className = "picker-panel";
    this.node.setAttribute("role", "dialog");
    this.node.hidden = true;
    this.node.addEventListener("mousedown", (event) => event.preventDefault()); // keep the focus
    window.addEventListener("resize", () => this.close());
    window.addEventListener("scroll", (event) => {
      if (this.field && !this.node.contains(event.target)) this.place();
    }, true);
  }

  open(field) {
    if (field.box.disabled || field.box.readOnly) return;
    this.field = field;
    (field.box.closest("dialog") || document.body).append(this.node);
    field.kind.start(this);
    this.node.hidden = false;
    this.render();
  }

  close() {
    this.field = null;
    this.node.hidden = true;
  }

  pick(value) {
    const { field } = this;
    this.close();
    field.set(value);
  }

  render() {
    const { field } = this;
    const footer = document.createElement("div");
    footer.className = "picker-foot";
    footer.append(button("picker-link", field.kind.nowLabel() ?? "", () => this.pick(field.kind.now())));
    if (!field.input.required && !field.box.required) {
      footer.append(button("picker-link picker-link-quiet", words().clear ?? "", () => this.pick("")));
    }
    this.node.replaceChildren(...field.kind.draw(this), footer);
    this.place();
  }

  place() {
    const box = this.field.box.getBoundingClientRect();
    const { offsetWidth: width, offsetHeight: height } = this.node;
    const gap = 6;
    const below = box.bottom + gap + height <= window.innerHeight || box.top < height + gap;
    const wanted = isRtl() ? box.right - width : box.left;
    this.node.style.top = `${below ? box.bottom + gap : box.top - height - gap}px`;
    this.node.style.left = `${Math.max(8, Math.min(wanted, window.innerWidth - width - 8))}px`;
  }
}

const panel = new Panel();

export function enhancePickers(root = document) {
  root.querySelectorAll?.('input[type="date"], input[type="month"], input[type="time"]')
    .forEach((input) => new Field(input));
}

/** Now, and whatever is added later: repeatable rows, results brought in by live_filter.js. */
export function initPickers() {
  enhancePickers();
  new MutationObserver((changes) => {
    for (const change of changes) {
      for (const node of change.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (node.matches('input[type="date"], input[type="month"], input[type="time"]')) new Field(node);
        else enhancePickers(node);
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
}
