// What the API (demo/api.py) answers. The facts are egms_client.facts, as JSON.

export type Window = {
  release: string;
  first: string | null;
  last: string | null;
  exact: boolean;
  text: string;
};

export type Reliability = {
  score: number;
  reliable: boolean;
  reliable_from: number;
  coverage: number;
  radius_m: number;
  fit: number | null;
  rmse_mm: number | null;
  reasons: string[];
};

export type Velocity = {
  answer: "velocity";
  lon: number;
  lat: number;
  component: "U" | "E";
  measured: boolean;
  velocity_mm_per_year: number | null;
  reliability: Reliability;
  regional: { radius_m: number; median_mm_per_year: number | null; relative_mm_per_year: number | null };
  release: string;
  window: Window;
  files: string[];
  licence: string;
  notes: string[];
};

export type Worded<F> = { facts: F; text: string; records?: OpenRecord[] };

export type PlaceAnswer = {
  source: "archive" | "demo";
  vertical: Worded<Velocity>;
  east: Worded<Velocity> | null;
};

export type MovingCell = {
  lon: number;
  lat: number;
  velocity_mm_per_year: number;
  relative_mm_per_year: number;
  coverage: number;
  reliable: boolean;
};

export type MovingAnswer = {
  source: "archive" | "demo";
  facts: {
    measured: boolean;
    moving: number;
    moving_reliable: number;
    threshold_mm_per_year: number;
    reference_median_mm_per_year: number | null;
    cells: MovingCell[];
    window: Window;
  };
  text: string;
};

/** missing_tiles: tiles not on the disk yet (503): the page waits, it does not answer with part of the data. */
export type Failed = { error: string; not_measured?: boolean; missing_tiles?: string[] };

export type Box = { west: number; south: number; east: number; north: number };

// Records of open data (egms_client.records, opendata-record/v1): any source, one shape.

export type Geometry =
  | { type: "Point"; coordinates: [number, number] | [number, number, number] }
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] };

export type RecordTime = { instant: string } | { first: string; last: string; exact: boolean } | null;

export type RecordReliability = {
  score?: number | null;
  reliable?: boolean | null;
  method: string;
  reasons?: string[];
} | null;

export type Quantity = { value: number | null; unit: string; meaning?: string };

export type OpenRecord = {
  schema: "opendata-record/v1";
  kind: "observation" | "fact" | "layer";
  id?: string;
  source: { name: string; url?: string; licence: string; attribution?: string };
  made_by: { name: string; version?: string };
  time: RecordTime;
  where: Geometry;
  reliability: RecordReliability;
  notes?: string[];
  label?: string | Record<string, string>;
  headline?: string;
  thing?: string;
  property?: string;
  value?: number | null;
  unit?: string;
  meaning?: string;
  quality?: { flags: string[] };
  question?: string;
  values?: Record<string, Quantity>;
  href?: string;
  no_data?: string;
};

/** A record and the file it was read from. */
export type Filed = { file: string; record: OpenRecord };

export type RecordsAnswer = { records: Filed[]; limit: number };

export type Source = {
  name: string;
  url?: string;
  licence: string;
  attribution?: string;
  made_by: string[];
  records: number;
  kinds: string[];
  properties: string[];
  methods: string[];
  files: string[];
};

export type SourcesAnswer = {
  egms: "archive" | "demo";
  folders: string[];
  sources: Source[];
  refused: { file: string; problems: string[] }[];
};

/** The area of the page (demo/api.py, /api/health): its Comune and a radius around it. */
export type Area = {
  lon: number;
  lat: number;
  radius_km: number;
  west: number;
  south: number;
  east: number;
  north: number;
};

export type Health = { ok: boolean; source: "archive" | "demo"; area: Area };
