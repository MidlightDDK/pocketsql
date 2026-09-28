import type { Page } from "@playwright/test";

/** Collects Content-Security-Policy violations from every page and worker frame. */
export async function watchCsp(page: Page): Promise<() => Promise<string[]>> {
  const console: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy/i.test(m.text())) console.push(m.text());
  });
  await page.addInitScript(() => {
    const w = window as { __csp?: string[] };
    w.__csp = [];
    addEventListener("securitypolicyviolation", (e) => {
      w.__csp?.push(`${e.violatedDirective} ${e.blockedURI}`);
    });
  });
  return async () => [
    ...console,
    ...(await page.evaluate(
      () => (window as { __csp?: string[] }).__csp ?? [],
    )),
  ];
}
