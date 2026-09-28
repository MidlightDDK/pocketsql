import type { ChatMessage } from "@pocketsql/sqlgen";

export type Device = "webgpu" | "wasm";
export type Dtype = "q4f16" | "q4";

export type ToWorker =
  | { type: "load"; device: Device; dtype: Dtype }
  | { type: "generate"; id: number; messages: ChatMessage[]; sample: boolean };

export type FromWorker =
  | { type: "progress"; file: string; loaded: number; total: number }
  /** `cached`: every model file is in the browser cache, so it loads offline. */
  | { type: "ready"; loadMs: number; cached: boolean }
  | { type: "text"; id: number; text: string }
  | { type: "done"; id: number; text: string; ms: number; tokens: number }
  | { type: "error"; id?: number; message: string };
