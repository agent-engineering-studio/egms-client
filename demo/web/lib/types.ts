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

export type Worded<F> = { facts: F; text: string };

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

export type Failed = { error: string; not_measured?: boolean };

export type Box = { west: number; south: number; east: number; north: number };
