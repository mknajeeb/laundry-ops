import React from "react";
import ReactDOM from "react-dom/client";
import "./api";
import App from "./App.jsx";
import "./index.css";
import { AuthProvider } from "./context/AuthContext.jsx";
import { I18nProvider } from "./i18n/I18nContext.jsx";

const ONESIGNAL_APP_ID = import.meta.env.VITE_ONESIGNAL_APP_ID;

/** OneSignal Web Push: requires VITE_ONESIGNAL_APP_ID and index.html OneSignalSDK.page.js script. */
if (typeof window !== "undefined" && ONESIGNAL_APP_ID && !window.__laundryOpsOneSignalInitQueued) {
  window.__laundryOpsOneSignalInitQueued = true;
  window.OneSignalDeferred = window.OneSignalDeferred || [];
  window.OneSignalDeferred.push(async function initOneSignal(OneSignal) {
    await OneSignal.init({
      appId: ONESIGNAL_APP_ID,
      allowLocalhostAsSecureOrigin: Boolean(import.meta.env.DEV),
      // Default: /OneSignalSDKWorker.js in public/ (from OneSignal SDK zip)
    });
  });
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <I18nProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </I18nProvider>
  </React.StrictMode>
);

// PWA shell updates: register SW when not using OneSignal (OneSignal.init registers /service-worker.js).
if ("serviceWorker" in navigator && import.meta.env.PROD && !ONESIGNAL_APP_ID) {
  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register("/service-worker.js");

      const notifyUpdateReady = () => {
        window.dispatchEvent(new CustomEvent("washpro:update-ready"));
      };

      if (registration.waiting) {
        notifyUpdateReady();
      }

      registration.addEventListener("updatefound", () => {
        const newWorker = registration.installing;
        if (!newWorker) return;

        newWorker.addEventListener("statechange", () => {
          if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
            notifyUpdateReady();
          }
        });
      });
    } catch (error) {
      console.error("Service worker registration failed:", error);
    }
  });
}
