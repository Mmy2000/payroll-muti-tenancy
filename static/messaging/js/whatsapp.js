// Settings → WhatsApp: start linking, then show the QR and watch the link until the phone has
// scanned it (every 3 s, at most 100 times, as PayRole's screen did).

import { ApiError, api } from "../../core/js/api.js";
import { busy } from "../../core/js/loading.js";

const EVERY_MS = 3000;
const TRIES = 100;

function show(box, state) {
  const text = box.dataset;
  const words = { linked: text.textLinked, waiting: text.textWaiting, broken: text.textBroken };
  box.querySelector("[data-link-status]").textContent = words[state.status] || text.textNotLinked;
  box.querySelector("[data-link-phone]").textContent = state.phone || "";
  const qr = box.querySelector("[data-link-qr]");
  qr.classList.toggle("hidden", !state.qr);
  if (state.qr) qr.src = state.qr;
  box.querySelector("[data-link-error]").textContent = state.error || "";
}

async function watch(box) {
  for (let tries = 0; tries < TRIES; tries += 1) {
    const state = await api(box.dataset.endpoint, { quiet: true });
    show(box, state);
    if (state.status === "linked") {
      window.location.reload();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, EVERY_MS));
  }
}

function init() {
  const box = document.querySelector("[data-whatsapp-link]");
  if (!box) return;
  const button = box.querySelector("[data-link-start]");
  button.addEventListener("click", async () => {
    const done = busy(button);
    try {
      show(box, await api(box.dataset.endpoint, { method: "POST", body: {} }));
      await watch(box);
    } catch (error) {
      box.querySelector("[data-link-error]").textContent =
        error instanceof ApiError ? error.message : String(error);
    } finally {
      done();
    }
  });
}

init();
