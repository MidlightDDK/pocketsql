// A three-page app needs no router library: pathname state plus pushState.
import { type AnchorHTMLAttributes, useSyncExternalStore } from "react";

const listeners = new Set<() => void>();
const subscribe = (l: () => void) => {
  listeners.add(l);
  addEventListener("popstate", l);
  return () => {
    listeners.delete(l);
    removeEventListener("popstate", l);
  };
};

export const usePath = () =>
  useSyncExternalStore(subscribe, () => location.pathname);

export function navigate(to: string) {
  history.pushState(null, "", to);
  scrollTo(0, 0);
  for (const l of listeners) l();
}

export function Link({
  href,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return (
    <a
      href={href}
      {...rest}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(href);
      }}
    />
  );
}
