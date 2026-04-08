import { useEffect, useRef } from "react";

const SCRIPT_ID = "washpro-gmaps-places";

function parseAddressComponents(components) {
  const out = { street: "", city: "", state: "", zip: "" };
  let num = "";
  let route = "";
  /** NYC and some US addresses omit `locality`; use neighborhood / sublocality as city fallback. */
  const cityFallbacks = [];
  if (!components) return out;
  for (const c of components) {
    const t = c.types || [];
    const long = (c.long_name || "").trim();
    if (t.includes("street_number")) num = long;
    if (t.includes("route")) route = long;
    if (t.includes("locality")) out.city = long;
    if (
      t.includes("sublocality_level_1") ||
      t.includes("sublocality") ||
      t.includes("neighborhood") ||
      t.includes("administrative_area_level_3")
    ) {
      if (long) cityFallbacks.push(long);
    }
    if (t.includes("administrative_area_level_1")) out.state = String(c.short_name || "").slice(0, 2).toUpperCase();
    if (t.includes("postal_code")) out.zip = String(c.long_name || "").replace(/\D/g, "").slice(0, 10);
  }
  if (!out.city && cityFallbacks.length) {
    out.city = cityFallbacks[0];
  }
  out.street = [num, route].filter(Boolean).join(" ").trim();
  return out;
}

function loadPlacesApi(apiKey) {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") return reject();
    if (window.google?.maps?.places) {
      resolve();
      return;
    }
    const existing = document.getElementById(SCRIPT_ID);
    if (existing) {
      const t0 = Date.now();
      const poll = setInterval(() => {
        if (window.google?.maps?.places) {
          clearInterval(poll);
          resolve();
        } else if (Date.now() - t0 > 20000) {
          clearInterval(poll);
          reject(new Error("timeout"));
        }
      }, 80);
      return;
    }
    const s = document.createElement("script");
    s.id = SCRIPT_ID;
    s.async = true;
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=places`;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("script"));
    document.head.appendChild(s);
  });
}

/**
 * When VITE_GOOGLE_MAPS_API_KEY is set, wires Places Autocomplete to the input.
 * onPlace{{ street, city, state, zip }}
 *
 * `enabled` must go true after the input mounts (e.g. when switching to a tab that
 * contains the street field); otherwise the effect runs once with ref=null and never attaches.
 */
export function useStreetAutocomplete(onPlace, enabled = true) {
  const ref = useRef(null);
  const cb = useRef(onPlace);
  cb.current = onPlace;
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";

  useEffect(() => {
    if (!apiKey || !enabled) return undefined;
    let ac = null;
    let listener = null;
    let dead = false;
    let retryTimer = null;
    const tryAttach = () => {
      if (dead) return;
      const el = ref.current;
      if (!el || !window.google?.maps?.places) return;
      ac = new window.google.maps.places.Autocomplete(el, {
        types: ["address"],
        fields: ["address_components", "formatted_address"],
      });
      listener = ac.addListener("place_changed", () => {
        const place = ac.getPlace();
        const p = parseAddressComponents(place?.address_components);
        if (!p.city && place?.formatted_address) {
          const segments = place.formatted_address.split(",").map((s) => s.trim()).filter(Boolean);
          if (segments.length >= 3) {
            p.city = segments[segments.length - 3] || p.city;
          }
        }
        if (cb.current) cb.current(p);
      });
    };

    (async () => {
      try {
        await loadPlacesApi(apiKey);
        if (dead) return;
        if (ref.current) {
          tryAttach();
        } else {
          let n = 0;
          retryTimer = setInterval(() => {
            n += 1;
            if (dead) {
              clearInterval(retryTimer);
              return;
            }
            if (ref.current) {
              clearInterval(retryTimer);
              retryTimer = null;
              tryAttach();
            } else if (n > 40) {
              clearInterval(retryTimer);
              retryTimer = null;
            }
          }, 100);
        }
      } catch {
        /* optional feature */
      }
    })();

    return () => {
      dead = true;
      if (retryTimer) clearInterval(retryTimer);
      if (listener && window.google?.maps?.event) {
        try {
          window.google.maps.event.removeListener(listener);
        } catch {
          /* ignore */
        }
      }
    };
  }, [apiKey, enabled]);

  return { inputRef: ref, hasMapsKey: !!apiKey };
}
