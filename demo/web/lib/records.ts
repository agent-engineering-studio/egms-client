// How a record reads on the page: its number, its time, how far to trust it, and which
// records are near a point. Every number is the record's own; nothing is computed here
// but distances.

import type { Lang } from "./start";
import type { Filed, Geometry, OpenRecord } from "./types";

/** Records shown for a point: the ones within this distance, in metres. */
export const NEAR_M = 2_000;

/** Colours for the sources, in the order they are listed: one colour per source. */
export const SOURCE_COLOURS = ["#0066cc", "#008055", "#995c00", "#7a1fa2", "#cc334d", "#00687a"];

const UNITS: Record<Lang, Record<string, string>> = {
  it: { "mm/a": "mm/anno", "mm/h": "mm/ora", "1": "", h: "ore", Cel: "°C" },
  en: { "mm/a": "mm/year", "mm/h": "mm/hour", "1": "", h: "hours", Cel: "°C" },
};

/** A UCUM unit as people read it. */
export const unitText = (unit: string, lang: Lang) => UNITS[lang][unit] ?? unit;

/** A number in the language of the page, with its sign when the record has a meaning for it. */
export function numberText(value: number, unit: string, lang: Lang, signed = false): string {
  const locale = lang === "it" ? "it-IT" : "en-GB";
  const share = unit === "1" && Math.abs(value) <= 1 && !Number.isInteger(value);
  const text = share
    ? `${(value * 100).toLocaleString(locale, { maximumFractionDigits: 1 })} %`
    : value.toLocaleString(locale, { maximumFractionDigits: 2 });
  const sign = signed && value > 0 ? "+" : "";
  const u = share ? "" : unitText(unit, lang);
  return `${sign}${text}${u ? " " + u : ""}`;
}

/** The time of a record in words, or null when the source gives no dates. */
export function timeText(r: OpenRecord, lang: Lang, short = false): string | null {
  const t = r.time;
  if (!t) return null;
  const locale = lang === "it" ? "it-IT" : "en-GB";
  if ("instant" in t) {
    const style = short ? "short" : "medium";
    return new Date(t.instant).toLocaleString(locale, { dateStyle: style, timeStyle: "short", timeZone: "UTC" }) + " UTC";
  }
  const day = (d: string) => new Date(d + "T00:00:00Z").toLocaleDateString(locale, { dateStyle: "medium", timeZone: "UTC" });
  return `${day(t.first)} – ${day(t.last)}`;
}

export const notMeasured = (r: OpenRecord) => r.reliability?.reasons?.includes("not_measured") ?? false;

/** One point for a geometry: the point itself, or the middle of its bounds. */
export function centre(g: Geometry): [number, number] {
  if (g.type === "Point") return [g.coordinates[0], g.coordinates[1]];
  const flat = (g.type === "Polygon" ? g.coordinates : g.coordinates.flat()).flat();
  const lons = flat.map((p) => p[0]);
  const lats = flat.map((p) => p[1]);
  return [(Math.min(...lons) + Math.max(...lons)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2];
}

/** Metres between two points (haversine). */
export function metres(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const rad = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(a));
}

function inside(g: Geometry, lon: number, lat: number): boolean {
  if (g.type === "Point") return false;
  const flat = (g.type === "Polygon" ? g.coordinates : g.coordinates.flat()).flat();
  const lons = flat.map((p) => p[0]);
  const lats = flat.map((p) => p[1]);
  return lon >= Math.min(...lons) && lon <= Math.max(...lons) && lat >= Math.min(...lats) && lat <= Math.max(...lats);
}

/** A series: the observations of one thing (or place) and one property, oldest first. */
export type Group = { key: string; items: Filed[]; distance: number };

/**
 * The records to show for a point, near first: points within NEAR_M, and the areas that hold it.
 * Map layers are not cards: they are the map. Observations of one thing and property are one
 * group, a series.
 */
export function near(items: Filed[], lon: number, lat: number, skip: (r: OpenRecord) => boolean): Group[] {
  const groups = new Map<string, Group>();
  for (const item of items) {
    const r = item.record;
    if (r.kind === "layer" || skip(r)) continue;
    const [x, y] = centre(r.where);
    const distance = r.where.type === "Point" ? metres(lon, lat, x, y) : inside(r.where, lon, lat) ? 0 : Infinity;
    if (distance > NEAR_M) continue;
    const key =
      r.kind === "observation"
        ? `${r.source.name}|${r.thing ?? r.where.type + x + "," + y}|${r.property}`
        : `${item.file}|${r.id ?? r.question}`;
    const group = groups.get(key) ?? { key, items: [], distance };
    group.items.push(item);
    groups.set(key, group);
  }
  for (const g of groups.values()) g.items.sort((a, b) => stamp(a.record) - stamp(b.record));
  return [...groups.values()].sort((a, b) => a.distance - b.distance);
}

const stamp = (r: OpenRecord) => (r.time && "instant" in r.time ? Date.parse(r.time.instant) : 0);
