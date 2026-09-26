import { parseArgs } from "node:util";

// `pnpm eval:onnx --model <hf-repo>@<revision> --set own_test`
const { values } = parseArgs({
  options: { model: { type: "string" }, set: { type: "string" } },
});
console.error(
  `eval:onnx (model ${values.model ?? "?"}, set ${values.set ?? "?"}) is not implemented yet (planned for M5).`,
);
process.exit(1);
