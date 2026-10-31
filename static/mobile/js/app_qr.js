// The QR card on an employee's page (apps/mobile/templates/mobile/_qr_card.html). The server keeps
// only a fingerprint of the code, so the picture exists here alone, until the page is left.
import { api, ApiError } from "../../core/js/api.js";
import { toast } from "../../core/js/ui.js";

const card = document.querySelector("[data-app-qr]");
const part = (name) => card.querySelector(`[data-qr-${name}]`);
const words = () => part("words").dataset;
let ticking = null;

function showError(error) {
  const box = part("error");
  box.textContent = error instanceof ApiError ? error.message : words().expired;
  box.classList.remove("hidden");
}

function setButtons({ shown, active }) {
  part("shown").hidden = !shown;
  part("waiting").hidden = shown || !active;
  card.querySelectorAll("[data-qr-cancel]")[1].hidden = shown || !active;
  part("generate-label").textContent = shown || active ? words().new : words().first;
}

function countDown(expiresAt) {
  clearInterval(ticking);
  const tick = () => {
    const left = Math.round((new Date(expiresAt) - Date.now()) / 1000);
    if (left <= 0) {
      clearInterval(ticking);
      part("image").replaceChildren();
      setButtons({ shown: false, active: false });
      toast(words().expired);
      return;
    }
    const hours = Math.floor(left / 3600);
    const clock = `${String(Math.floor(left / 60) % 60).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
    part("left").textContent = hours ? `${hours}:${clock}` : clock;
  };
  tick();
  ticking = setInterval(tick, 1000);
}

async function act(run) {
  part("error").classList.add("hidden");
  try {
    await run();
  } catch (error) {
    showError(error);
  }
}

if (card) {
  const url = card.dataset.endpoint;
  part("generate").addEventListener("click", () => act(async () => {
    const data = await api(url, { method: "PUT", body: {} });
    part("image").innerHTML = data.svg; // drawn by the server from its own text
    setButtons({ shown: true, active: true });
    countDown(data.expires_at);
  }));
  part("renew").addEventListener("click", () => act(async () => {
    const data = await api(`${url}renew/`, { method: "POST", body: {} });
    countDown(data.expires_at);
  }));
  card.querySelectorAll("[data-qr-cancel]").forEach((button) => button.addEventListener("click", () => act(async () => {
    await api(url, { method: "DELETE" });
    clearInterval(ticking);
    part("image").replaceChildren();
    setButtons({ shown: false, active: false });
  })));
}
