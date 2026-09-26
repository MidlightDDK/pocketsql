import { readFileSync } from "node:fs";
import { join } from "node:path";
import { AutoTokenizer } from "@huggingface/transformers";
import { expect, it } from "vitest";
import { FIXTURES, goldenCases } from "./fixtures.ts";
import { buildMessages, serializeSchema } from "./schema.ts";

// Python writes these ids (python -m pocketsql.data.tokens --write); matching them
// here proves Transformers.js tokenizes the prompt exactly like training does.
const spec: { model: string; revision: string; ids: Record<string, number[]> } =
  JSON.parse(readFileSync(join(FIXTURES, "tokens.json"), "utf8"));

// Extra keys reach the Jinja template; enable_thinking is not in the option types.
const TEMPLATE_OPTIONS = {
  add_generation_prompt: true,
  enable_thinking: false,
  tokenize: true,
  return_tensor: false,
  return_dict: false,
} as const;

it("tokenizes every golden prompt like the Python tokenizer", async () => {
  const tokenizer = await AutoTokenizer.from_pretrained(spec.model, {
    revision: spec.revision,
  });
  const cases = goldenCases();
  expect(Object.keys(spec.ids).sort()).toEqual(cases.map((c) => c.name));
  for (const c of cases) {
    const ids = tokenizer.apply_chat_template(
      buildMessages(serializeSchema(c.schema), c.question),
      TEMPLATE_OPTIONS,
    );
    expect(ids, c.name).toEqual(spec.ids[c.name]);
  }
}, 120_000);
