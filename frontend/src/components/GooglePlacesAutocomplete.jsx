import { useEffect, useRef } from "react";

const SCRIPT_ID = "washpro-gmaps-places";

function parseAddressComponents(components) {
  const out = { street: "", city: "", state: "", zip: "" };
  let num = "";
  let route = "";
  if (!components) return out;
  for (const c of components) {
    const t = c.types || [];
    if (t.includes("street_number")) num = c.long_name || "";
    if (t.includes("route")) route = c.long_name || "";
    if (t.includes("locality")) out.city = c.long_name || "";
    if (t.includes("administrative_area_level_1")) out.state = String(c.short_name || "").slice(0, 2).toUpperCase();
    if (t.includes("postal_code")) out.zip = String(c.long_name || "").replace(/\D/g, "").slice(0, 10);
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
 * onPlace({ street, city, state, zip })
 */
export function useStreetAutocomplete(onPlace) {
  const ref = useRef(null);
  const cb = useRef(onPlace);
  cb.current = onPlace;
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";

  useEffect(() => {
    if (!apiKey || !ref.current) return undefined;
    let ac = null;
    let listener = null;
    let dead = false;

    (async () => {
      try {
        await loadPlacesApi(apiKey);
        if (dead || !ref.current || !window.google?.maps?.places) return;
        ac = new window.google.maps.places.Autocomplete(ref.current, {
          types: ["address"],
          fields: ["address_components"],
        });
        listener = ac.addListener("place_changed", () => {
          const place = ac.getPlace();
          const p = parseAddressComponents(place?.address_components);
          if (cb.current) cb.current(p);
        });
      } catch {
        /* optional feature */
      }
    })();

    return () => {
      dead = true;
      if (listener && window.google?.maps?.event) {
        try {
          window.google.maps.event.removeListener(listener);
        } catch {
          /* ignore */
        }
      }
    };
  }, [apiKey]);

  return { inputRef: ref, hasMapsKey: !!apiKey };
}
