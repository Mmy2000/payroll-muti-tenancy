# ADR-109: Placing a branch on a map

**Status:** Accepted · 2026-11-01

## Context

A branch's latitude, longitude and radius decide where the mobile app accepts a punch. People were
asked to type them as numbers, which nobody knows by heart, and a wrong digit quietly locks a branch
out of clocking in.

## Decision

- The branch form picks the place on a map: search, a pasted map link, the device's location, or a
  click, then drag the pin, with the zone drawn as a circle. It is one reusable component
  (`components/location_picker.html`, `static/core/js/location_picker.js`).
- The form still sends the same three fields, so the API, the mobile app and the geofence are
  unchanged. The numbers stay editable: they are the keyboard route, and what is left if the map
  can't load.
- [Leaflet](https://leafletjs.com) is the map (a new dependency, BSD-2-Clause). It is small, needs no
  key, and is vendored like Tom Select, so no third party serves code to the app. It only loads on a
  page with a map.
- Map images come from OpenStreetMap, and search from Nominatim. Those browsers' requests go straight
  to them, and carry a referrer, which OpenStreetMap requires and the site otherwise withholds.
- Search runs on Enter or the button, never while typing: Nominatim's policy forbids autocomplete.
  Links and coordinates are read in the browser and send nothing.

## Consequences

- People's browsers tell OpenStreetMap which area they are viewing, and Nominatim what they searched.
  That is an address being looked up, not employee data, and only on the branch form.
- OpenStreetMap's servers are a public service with a fair-use policy. Staff placing a few branches
  is well inside it. A client with its own needs would mean a commercial tile provider: one constant
  changes (`TILES`), plus the attribution.
- A short link (`maps.app.goo.gl`) can't be read in the browser, so the person is asked for the full
  one.
