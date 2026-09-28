// The three demo databases (web/public/data/*.duckdb) and their prompt schemas,
// serialized by training's serializer (evals/sets/schemas.json).
import { chinook, penguins, world_bank } from "../../evals/sets/schemas.json";

export interface Dataset {
  id: string;
  label: string;
  blurb: string;
  /** The schema exactly as the model sees it in its prompt. */
  schema: string;
  source?: { name: string; url: string; license: string };
  /** A table the user uploaded: not on the server, so no big-model comparison. */
  upload?: boolean;
}

export const DEMO_DATASETS: Dataset[] = [
  {
    id: "chinook",
    label: "Music store",
    blurb:
      "Chinook: 11 tables of artists, albums, tracks, customers, and invoices.",
    schema: chinook,
    source: {
      name: "Chinook",
      url: "https://github.com/lerocha/chinook-database",
      license: "MIT",
    },
  },
  {
    id: "penguins",
    label: "Penguins",
    blurb: "Palmer penguins: 344 penguins measured on 3 Antarctic islands.",
    schema: penguins,
    source: {
      name: "Palmer penguins",
      url: "https://allisonhorst.github.io/palmerpenguins/",
      license: "CC0 1.0",
    },
  },
  {
    id: "world_bank",
    label: "World Bank",
    blurb:
      "World Development Indicators: population, GDP, and more by country and year.",
    schema: world_bank,
    source: {
      name: "World Development Indicators",
      url: "https://datacatalog.worldbank.org/search/dataset/0037712",
      license: "CC BY 4.0",
    },
  },
];
