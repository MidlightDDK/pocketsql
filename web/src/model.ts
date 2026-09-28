// The released model the app loads: its Hub repo and the exact revision that passed the
// release gate (evals/baseline.json). Change both only through a new gated release.
export const MODEL_REPO = "MidlightDDK/pocketsql-0.5b";
export const MODEL_REVISION = "de60f0f6515208c9b24fe9d9d36f56f1dc336506";
// Download size of the model files per dtype (evals/reports/latest.json, download_mib).
export const DOWNLOAD_MIB = { q4f16: 276, q4: 310 } as const;
