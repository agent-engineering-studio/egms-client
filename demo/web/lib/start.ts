// Where the page opens, and in which language. A Comune that puts this page on its site
// gives its own place in the environment (EGMS_UI_*) or in the address of the page
// (?lat=&lon=&place=&zoom=&lang=&embed=1). The address wins, one source at a time, so a
// name never goes with the coordinates of another.

export type Lang = "it" | "en";

export type Start = {
  lat: number;
  lon: number;
  zoom: number;
  /** The name to show, such as "Comune di Pozzuoli". */
  place: string | null;
  /** True when the coordinates were given: the place gets a marker, and its card is open. */
  given: boolean;
  lang: Lang;
  /** In an iframe: no header and no footer, only the map and the card. */
  embed: boolean;
};

export type Asked = {
  lat?: string;
  lon?: string;
  zoom?: string;
  place?: string;
  lang?: string;
  embed?: string;
};

// Pozzuoli, Rione Terra: the ground rises there, and EGMS measures much of the town.
const DEFAULT = { lat: 40.8225, lon: 14.1205 };
const DEFAULT_ZOOM = 13;
export const MIN_ZOOM = 6;
export const MAX_ZOOM = 17;
// What EGMS covers, with a margin: coordinates outside it are a mistake.
const AREA = { south: 27, north: 72, west: -32, east: 45 };

const number = (text: string | undefined) => {
  const value = text?.trim() ? Number(text.replace(",", ".")) : NaN;
  return Number.isFinite(value) ? value : null;
};

const inside = (lat: number | null, lon: number | null): lat is number =>
  lat !== null && lon !== null && lat >= AREA.south && lat <= AREA.north && lon >= AREA.west && lon <= AREA.east;

const langOf = (sources: Asked[]): Lang =>
  sources.map((s) => s.lang?.trim().toLowerCase()).find((l) => l === "it" || l === "en") === "en" ? "en" : "it";

/** The start from what was asked: the first source with valid coordinates. */
export function startFrom(...sources: Asked[]): Start {
  const lang = langOf(sources);
  const embed = sources.some((s) => ["1", "true", "yes"].includes(s.embed?.trim().toLowerCase() ?? ""));
  for (const asked of sources) {
    const lat = number(asked.lat);
    const lon = number(asked.lon);
    if (!inside(lat, lon)) continue;
    const zoom = number(asked.zoom) ?? DEFAULT_ZOOM;
    return {
      lat,
      lon: lon as number,
      zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)),
      place: asked.place?.trim().slice(0, 80) || null,
      given: true,
      lang,
      embed,
    };
  }
  return { ...DEFAULT, zoom: DEFAULT_ZOOM, place: null, given: false, lang, embed };
}

export type Tiles = { url: string; attribution: string };

/** The background map: OpenStreetMap, or the tiles of whoever hosts the page. */
export const tilesFrom = (url: string | undefined, attribution: string | undefined): Tiles => ({
  url: url?.trim() || "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution:
    attribution?.trim() ||
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
});
