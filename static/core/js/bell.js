// The bell in the top bar: the unread count and the panel, kept up to date by live.js.
// `state` is what is known; render() draws it, so a live event only has to change the state.
import { api } from "./api.js";
import { connectLive } from "./live.js";
import { spinner } from "./loading.js";
import { toast } from "./ui.js";

const REFRESH_TIMES_EVERY = 60 * 1000;
const KEPT = 30;

function text(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

/** "5 minutes ago", in the page's language. */
function timeAgo(iso) {
  const seconds = Math.round((new Date(iso) - Date.now()) / 1000);
  const words = new Intl.RelativeTimeFormat(document.documentElement.lang || undefined, { numeric: "auto" });
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(seconds) >= size) return words.format(Math.round(seconds / size), unit);
  }
  return words.format(0, "minute");
}

function dayOf(iso, labels) {
  const midnight = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((midnight(new Date()) - midnight(new Date(iso))) / 86400000);
  if (days <= 0) return labels.today;
  return days === 1 ? labels.yesterday : labels.earlier;
}

class Bell {
  constructor(root) {
    this.root = root;
    this.badge = root.querySelector("[data-bell-count]");
    this.panel = root.querySelector("[data-bell-panel]");
    this.body = root.querySelector("[data-bell-body]");
    this.words = root.querySelector("[data-bell-strings]").dataset;
    this.pageTitle = document.title;
    this.state = { unread: Number(this.badge.textContent.replace("+", "")) || 0, items: [], attention: [],
                   tab: "all", loaded: false, failed: false };
  }

  get isOpen() {
    return !this.panel.hidden;
  }

  // --- what happened ------------------------------------------------------------------------

  setUnread(unread) {
    this.state.unread = unread;
    this.badge.hidden = !unread;
    this.badge.textContent = unread > 99 ? "99+" : String(unread);
    this.root.querySelector("[data-bell-read-all]").hidden = !unread;
    document.title = unread ? `(${unread > 99 ? "99+" : unread}) ${this.pageTitle}` : this.pageTitle;
  }

  arrived(notice) {
    if (this.state.items.some((item) => item.id === notice.id)) return;
    this.state.items = [notice, ...this.state.items].slice(0, KEPT);
    this.badge.classList.remove("bell-badge-new");
    void this.badge.offsetWidth; // restart the animation
    this.badge.classList.add("bell-badge-new");
    if (this.isOpen) {
      this.load(); // what needs attention may have changed with it
    } else {
      toast(notice.title, { href: notice.url });
    }
    document.querySelector("[data-new-notices]")?.removeAttribute("hidden");
  }

  async load() {
    if (!this.state.loaded) this.renderWaiting();
    try {
      const data = await api(this.root.dataset.endpoint, { quiet: true });
      Object.assign(this.state, { items: data.results, attention: data.attention, loaded: true, failed: false });
      this.setUnread(data.unread);
    } catch {
      this.state.failed = true;
    }
    this.render();
  }

  async refreshCount() {
    try {
      this.setUnread((await api(`${this.root.dataset.endpoint}?count=1`, { quiet: true })).unread);
    } catch {
      // Offline for a moment: the next round will try again.
    }
  }

  async readAll() {
    await api(this.root.dataset.readAll, { method: "POST", quiet: true });
    this.state.items = this.state.items.map((item) => ({ ...item, read: true }));
    this.setUnread(0);
    this.render();
  }

  /** Opening a notification marks it read first (the next page shows the new count). */
  open(link, event) {
    if (!link.hasAttribute("data-unread")) return;
    event.preventDefault();
    link.removeAttribute("data-unread");
    const go = () => {
      if (link.getAttribute("href") !== "#") window.location.assign(link.href);
    };
    api(link.dataset.notice, { method: "POST", quiet: true }).then(go, go);
  }

  toggle(open) {
    this.panel.hidden = !open;
    this.root.querySelector("[data-bell-toggle]").setAttribute("aria-expanded", String(open));
    if (open) this.load();
  }

  // --- drawing it ---------------------------------------------------------------------------

  icon(name) {
    const icons = this.root.querySelector("[data-bell-icons]").content;
    const source = icons.querySelector(`[data-icon="${name}"]`) || icons.querySelector('[data-icon="bell"]');
    return source ? source.firstElementChild.cloneNode(true) : document.createElement("span");
  }

  renderWaiting() {
    const wait = document.createElement("div");
    wait.className = "flex justify-center py-10 text-slate-400";
    wait.append(spinner("size-5"));
    this.body.replaceChildren(wait);
  }

  notice(item) {
    const link = document.createElement("a");
    link.href = item.url || "#";
    link.className = "notice";
    link.dataset.notice = `${this.root.dataset.endpoint}${item.id}/read/`;
    if (!item.read) link.dataset.unread = "";
    const tile = document.createElement("span");
    tile.className = "notice-icon";
    tile.dataset.tone = item.tone;
    tile.append(this.icon(item.icon));
    const words = document.createElement("span");
    words.className = "min-w-0 flex-1";
    words.append(text("span", "block text-sm font-medium text-slate-900", item.title));
    if (item.body) words.append(text("span", "mt-0.5 block text-xs text-slate-600", item.body));
    const time = text("time", "mt-1 block text-[11px] text-slate-400", timeAgo(item.at));
    time.dateTime = item.at;
    time.dataset.at = item.at;
    words.append(time);
    link.append(tile, words);
    return link;
  }

  attentionRow(item) {
    const link = document.createElement("a");
    link.href = item.url;
    link.className = "bell-queue";
    const tile = document.createElement("span");
    tile.className = "notice-icon";
    tile.dataset.tone = "action";
    tile.append(this.icon(item.icon));
    link.append(tile, text("span", "min-w-0 flex-1 truncate", item.label),
      text("span", "badge badge-warning num", String(item.count)));
    return link;
  }

  emptyState(title, detail) {
    const empty = document.createElement("div");
    empty.className = "flex flex-col items-center gap-1 px-4 py-10 text-center";
    const tile = document.createElement("span");
    tile.className = "mb-2 grid size-10 place-items-center rounded-full bg-slate-100 text-slate-400";
    tile.append(this.icon("bell"));
    empty.append(tile, text("p", "text-sm font-medium text-slate-700", title));
    if (detail) empty.append(text("p", "text-xs text-slate-500", detail));
    return empty;
  }

  render() {
    const { items, attention, tab, failed } = this.state;
    if (failed) {
      this.body.replaceChildren(text("p", "px-4 py-8 text-center text-sm text-red-600", this.words.failed));
      return;
    }
    this.root.querySelectorAll("[data-bell-tab]").forEach((button) => {
      button.setAttribute("aria-selected", String(button.dataset.bellTab === tab));
    });
    const shown = tab === "unread" ? items.filter((item) => !item.read) : items;
    const parts = [];
    if (tab === "all" && attention.length) {
      parts.push(text("p", "bell-heading", this.words.attention), ...attention.map((item) => this.attentionRow(item)));
    }
    let day = null;
    for (const item of shown) {
      const label = dayOf(item.at, this.words);
      if (label !== day) parts.push(text("p", "bell-heading", label));
      day = label;
      parts.push(this.notice(item));
    }
    if (!parts.length) {
      parts.push(tab === "unread" ? this.emptyState(this.words.noUnread)
                                  : this.emptyState(this.words.empty, this.words.emptyText));
    }
    this.body.replaceChildren(...parts);
  }

  refreshTimes() {
    this.body.querySelectorAll("[data-at]").forEach((time) => {
      time.textContent = timeAgo(time.dataset.at);
    });
  }

  // --- wiring -------------------------------------------------------------------------------

  start() {
    this.setUnread(this.state.unread);
    document.addEventListener("click", (event) => this.clicked(event));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.isOpen) {
        this.toggle(false);
        this.root.querySelector("[data-bell-toggle]").focus();
      }
    });
    window.setInterval(() => this.isOpen && this.refreshTimes(), REFRESH_TIMES_EVERY);
    connectLive(this.root.dataset.stream, {
      onNotification: (notice) => this.arrived(notice),
      onUnread: (unread) => this.setUnread(unread),
      onPoll: () => this.refreshCount(),
    });
  }

  clicked(event) {
    const { target } = event;
    const toggle = target.closest("[data-bell-toggle]");
    if (toggle && this.root.contains(toggle)) this.toggle(!this.isOpen);
    else if (!this.root.contains(target) && this.isOpen) this.toggle(false);

    const tab = target.closest("[data-bell-tab]");
    if (tab) {
      this.state.tab = tab.dataset.bellTab;
      this.render();
    }
    if (target.closest("[data-bell-read-all]")) this.readAll();
    const notice = target.closest("[data-notice]");
    if (notice) this.open(notice, event);
  }
}

export function initBell() {
  const root = document.querySelector("[data-bell]");
  if (root) new Bell(root).start();
}
