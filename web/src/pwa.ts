// Service-worker state for the "Offline ready" badge: the app shell and the
// DuckDB-WASM files are cached once a service worker is active.

import { registerSW } from "virtual:pwa-register";
import { useSyncExternalStore } from "react";

let active = false;
const listeners = new Set<() => void>();
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const markActive = () => {
  active = true;
  for (const l of listeners) l();
};

export function startServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  registerSW({ immediate: true, onOfflineReady: markActive });
  // `ready` resolves once a worker is active, i.e. after its precache finished.
  void navigator.serviceWorker.ready.then(markActive);
}

export const useServiceWorkerActive = () =>
  useSyncExternalStore(subscribe, () => active);
