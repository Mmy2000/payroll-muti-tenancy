// A place and a zone around it, on a map: <div data-location-picker> (components/location_picker.html).
// Search, paste a map link, use the device's location, or click the map, then drag the pin. The form
// still sends its plain coordinates and radius, which can also be typed in: that is what remains if
// the map can't load. Leaflet is only fetched for a page that has a map.

const START = { center: [26.8, 30.8], zoom: 5 }; // Egypt, until there is a pin
const CLOSE_ENOUGH = 13; // a click from further out zooms in, to place the pin with care
const CLOSE_UP = 16;
const MAX_ZOOM = 19;
const SLIDER_MAX = 1000; // a bigger zone can still be typed in, up to what the server allows
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const SEARCH = "https://nominatim.openstreetmap.org/search";
// The site sends no referrer to others, but OpenStreetMap refuses requests without one.
const REFERRER = "strict-origin-when-cross-origin";
const PIN = `<svg viewBox="0 0 32 40" width="32" height="40" aria-hidden="true">
  <path d="M16 1C8 1 2 7 2 15c0 10 14 24 14 24s14-14 14-24C30 7 24 1 16 1z"/>
  <circle cx="16" cy="15" r="5.5"/></svg>`;
const PLACE_IN_TEXT = [
  /@(-?\d+\.\d+),(-?\d+\.\d+)/, // a Google Maps address bar
  /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/,
  /[?&](?:q|ll|query)=(-?\d+\.\d+)(?:,|%2C)(-?\d+\.\d+)/,
  /^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,،\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/, // "30.04, 31.23"
];

/** The coordinates in a pasted link or pair of numbers, or null. */
export function placeInText(text) {
  for (const pattern of PLACE_IN_TEXT) {
    const found = text.match(pattern);
    if (!found) continue;
    const [lat, lng] = [Number(found[1]), Number(found[2])];
    if (Math.abs(lat) <= 90 && Math.abs(lng) <= 180) return { lat, lng };
  }
  return null;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = Object.assign(document.createElement("script"), { src, onload: resolve, onerror: reject });
    document.head.append(script);
  });
}

function loadStyle(href) {
  document.head.append(Object.assign(document.createElement("link"), { rel: "stylesheet", href }));
}

let leaflet = null;

function loadLeaflet(box) {
  leaflet ??= (async () => {
    loadStyle(box.dataset.leafletCss);
    await loadScript(box.dataset.leafletJs);
    return window.L;
  })();
  return leaflet;
}

class LocationPicker {
  constructor(box, L) {
    this.box = box;
    this.L = L;
    const part = (name) => box.querySelector(`[data-loc-${name}]`);
    Object.assign(this, {
      lat: part("lat"), lng: part("lng"), radius: part("radius"), slider: part("slider"),
      noteBox: part("note"), search: part("search"), results: part("results"), hint: part("hint"),
      clearButton: part("clear"), manual: part("manual"), form: box.closest("form"),
    });
    this.pin = null;
    this.zone = null;
    this.map = L.map(part("map"), { zoomControl: false, scrollWheelZoom: false, maxZoom: MAX_ZOOM });
    L.control.zoom({ position: "bottomleft" }).addTo(this.map); // clear of the hint and of Remove
    this.map.attributionControl.setPrefix(false);
    this.tiles = L.tileLayer(TILES, {
      maxZoom: MAX_ZOOM, referrerPolicy: REFERRER,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(this.map);
    this.map.setView(START.center, START.zoom);
    this.listen(part);
    new ResizeObserver(() => this.map.invalidateSize()).observe(part("map"));
    this.showRadius();
    this.placeFromFields({ fit: true, animate: false });
  }

  listen(part) {
    this.map.on("click", (event) => this.pick(event.latlng, this.map.getZoom() < CLOSE_ENOUGH ? "near" : "stay"));
    this.tiles.once("tileerror", () => this.mapFailed());
    // The wheel keeps scrolling the form past the map, until someone has clicked into the map.
    this.map.on("focus", () => this.map.scrollWheelZoom.enable());
    this.map.on("blur", () => this.map.scrollWheelZoom.disable());
    this.slider.addEventListener("input", () => this.setRadius(this.slider.value));
    this.slider.addEventListener("change", () => this.fitZone());
    this.radius.addEventListener("input", () => this.setRadius(this.radius.value, { typed: true }));
    this.box.querySelectorAll("[data-loc-preset]").forEach((button) => button.addEventListener("click", () => {
      this.setRadius(button.dataset.locPreset);
      this.fitZone();
    }));
    [this.lat, this.lng].forEach((field) => field.addEventListener("change", () => this.placeFromFields({ fit: true })));
    this.clearButton.addEventListener("click", () => this.clear());
    part("find").addEventListener("click", () => this.find());
    this.search.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.results.hidden = true;
      if (event.key !== "Enter") return;
      event.preventDefault(); // it finds the place, it doesn't save the form
      this.find();
    });
    const here = part("here");
    if (navigator.geolocation) here.addEventListener("click", () => this.useDevice());
    else here.hidden = true;
  }

  note(text = "") {
    this.noteBox.textContent = text;
    this.noteBox.hidden = !text;
  }

  mapFailed() {
    this.note(this.box.dataset.mapFailed);
    this.manual.open = true;
  }

  // --- the pin --------------------------------------------------------------------------------

  placeFromFields({ fit = false, animate = true } = {}) {
    const lat = Number.parseFloat(this.lat.value);
    const lng = Number.parseFloat(this.lng.value);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return;
    this.drawPin([lat, lng]);
    if (fit) this.fitZone({ animate });
  }

  writeFields({ lat, lng }) {
    this.lat.value = lat.toFixed(6);
    this.lng.value = lng.toFixed(6);
  }

  // A place was chosen. `view`: "fit" shows the zone, "near" zooms in on it, "stay" keeps the view.
  pick(latlng, view = "fit") {
    this.note();
    this.results.hidden = true;
    this.writeFields(latlng);
    this.drawPin(latlng);
    if (view === "fit") this.fitZone();
    else if (view === "near") this.map.flyTo(latlng, CLOSE_UP, { duration: 0.5 });
  }

  drawPin(latlng) {
    if (this.pin) {
      this.pin.setLatLng(latlng);
      this.zone.setLatLng(latlng);
    } else {
      const icon = this.L.divIcon({ className: "loc-pin", html: PIN, iconSize: [32, 40], iconAnchor: [16, 40] });
      this.zone = this.L.circle(latlng, { radius: this.radiusValue(), className: "loc-zone", interactive: false }).addTo(this.map);
      this.pin = this.L.marker(latlng, { icon, draggable: true, autoPan: true, title: this.box.dataset.dragPin }).addTo(this.map);
      this.pin.on("drag", (event) => this.zone.setLatLng(event.latlng));
      this.pin.on("dragend", () => this.writeFields(this.pin.getLatLng()));
    }
    this.hint.hidden = true;
    this.clearButton.hidden = false;
  }

  clear() {
    this.pin?.remove();
    this.zone?.remove();
    this.pin = this.zone = null;
    this.lat.value = "";
    this.lng.value = "";
    this.hint.hidden = false;
    this.clearButton.hidden = true;
    this.note();
    this.map.flyTo(START.center, START.zoom, { duration: 0.5 });
  }

  fitZone({ animate = true } = {}) {
    if (this.zone) this.map.fitBounds(this.zone.getBounds().pad(0.35), { maxZoom: 18, animate });
  }

  // --- the zone -------------------------------------------------------------------------------

  radiusValue() {
    return Number.parseInt(this.radius.value, 10) || 0;
  }

  setRadius(value, { typed = false } = {}) {
    if (!typed) this.radius.value = value;
    this.showRadius();
  }

  showRadius() {
    const metres = this.radiusValue();
    this.slider.value = Math.min(metres, SLIDER_MAX);
    this.slider.style.setProperty("--fill", `${((this.slider.value - this.slider.min) / (this.slider.max - this.slider.min)) * 100}%`);
    this.box.querySelectorAll("[data-loc-preset]").forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.locPreset) === metres));
    });
    if (metres) this.zone?.setRadius(metres);
  }

  // --- finding a place ------------------------------------------------------------------------

  async find() {
    const text = this.search.value.trim();
    if (!text) return;
    const place = placeInText(text);
    if (place) {
      this.pick(place);
      return;
    }
    if (/^https?:\/\//.test(text)) { // a short link hides its coordinates behind a redirect
      this.note(this.box.dataset.shortLink);
      return;
    }
    this.note(this.box.dataset.searching);
    try {
      const query = new URLSearchParams({ format: "jsonv2", limit: 5, q: text, "accept-language": document.documentElement.lang });
      const response = await fetch(`${SEARCH}?${query}`, { referrerPolicy: REFERRER });
      this.showResults(response.ok ? await response.json() : []);
    } catch {
      this.note(this.box.dataset.searchFailed);
    }
  }

  showResults(places) {
    this.note(places.length ? "" : this.box.dataset.nothingFound);
    this.results.replaceChildren(...places.map((place) => {
      const button = Object.assign(document.createElement("button"), {
        type: "button", className: "loc-result", textContent: place.display_name });
      button.addEventListener("click", () => this.pick({ lat: Number(place.lat), lng: Number(place.lon) }));
      return button;
    }));
    this.results.hidden = !places.length;
  }

  useDevice() {
    this.note(this.box.dataset.locating);
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => this.pick({ lat: coords.latitude, lng: coords.longitude }),
      () => this.note(this.box.dataset.locationRefused),
      { enableHighAccuracy: true, timeout: 10000 });
  }
}

async function start(box) {
  try {
    new LocationPicker(box, await loadLeaflet(box));
  } catch {
    box.querySelector("[data-loc-note]").textContent = box.dataset.mapFailed;
    box.querySelector("[data-loc-note]").hidden = false;
    box.querySelector("[data-loc-manual]").open = true;
    box.querySelector("[data-loc-map]").hidden = true;
  }
}

function startIn(root) {
  root.querySelectorAll("[data-location-picker]:not([data-started])").forEach((box) => {
    box.dataset.started = "";
    start(box);
  });
}

export function initLocationPickers() {
  startIn(document);
  document.addEventListener("form:opened", (event) => startIn(event.target));
}
