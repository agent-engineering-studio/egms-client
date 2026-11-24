// One row per source for the point clicked: what it is, its number in words, and how far
// to trust it. The numbers are the records' and the facts' own; here they are only worded.

import type { Text } from "./i18n";
import { notMeasured, numberText, timeText, type Group } from "./records";
import type { Lang } from "./start";
import type { OpenRecord, Velocity, Worded } from "./types";

export type TrustKind = "reliable" | "weak" | "unmeasured" | "unknown";

export type Row = {
  key: string;
  /** A colour of the map, or "egms" for the ground map. */
  colour: string;
  title: string;
  value: string;
  sub: string;
  trust: TrustKind;
  detail: {
    sentence?: string;
    values?: [string, string][];
    notes: string[];
    source: { name: string; url?: string };
    when: string | null;
    score: number | null;
    method?: string;
    licence: string;
    attribution?: string;
    slug: string;
  };
};

/** The words for the properties people know, when a record gives no label of its own. */
const PROPERTIES: Record<string, Record<Lang, string>> = {
  rainfall: { it: "Pioggia", en: "Rain" },
  velocity: { it: "Velocità", en: "Velocity" },
  displacement: { it: "Spostamento", en: "Displacement" },
  acceleration: { it: "Accelerazione", en: "Acceleration" },
  soil_moisture: { it: "Umidità del suolo", en: "Soil moisture" },
  pore_pressure: { it: "Pressione dell'acqua nel terreno", en: "Pore water pressure" },
  water_level: { it: "Livello dell'acqua", en: "Water level" },
  air_temperature: { it: "Temperatura dell'aria", en: "Air temperature" },
  relative_humidity: { it: "Umidità dell'aria", en: "Air humidity" },
  wind_speed: { it: "Vento", en: "Wind" },
};

/** The anchor of a source on the page of the data. */
export const slug = (name: string) =>
  name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

export function label(r: OpenRecord, lang: Lang): string {
  const l = r.label;
  if (typeof l === "string") return l;
  if (l) return l[lang] ?? Object.values(l)[0];
  if (r.property && PROPERTIES[r.property]) return PROPERTIES[r.property][lang];
  return r.question ?? r.property ?? r.source.name;
}

function trustOf(r: OpenRecord): TrustKind {
  if (notMeasured(r)) return "unmeasured";
  const reliable = r.reliability?.reliable;
  return reliable === true ? "reliable" : reliable === false ? "weak" : "unknown";
}

const signed = (meaning?: string) => /positiv/i.test(meaning ?? "");

function detailOf(r: OpenRecord, lang: Lang): Row["detail"] {
  return {
    notes: r.notes ?? [],
    source: { name: r.source.name, url: r.source.url },
    when: timeText(r, lang),
    score: r.reliability?.score ?? null,
    method: r.reliability?.method,
    licence: r.source.licence,
    attribution: r.source.attribution,
    slug: slug(r.source.name),
  };
}

/** A row for a group of records near the point: a fact, an observation, or a series. */
export function recordRow(group: Group, colour: string, t: Text, lang: Lang): Row {
  const records = group.items.map((i) => i.record);
  const last = records[records.length - 1];
  const where = t.away(Math.round(group.distance));
  const base = { key: group.key, colour, title: label(last, lang), detail: detailOf(last, lang) };
  if (last.kind === "fact") {
    const values = Object.entries(last.values ?? {});
    const head = values.find(([name]) => name === last.headline);
    const text = (v: (typeof values)[number][1]) =>
      v.value === null ? t.noValue : numberText(v.value, v.unit, lang, signed(v.meaning));
    return {
      ...base,
      value: head ? text(head[1]) : "",
      sub: where,
      trust: trustOf(last),
      detail: {
        ...base.detail,
        sentence: last.question,
        values: values.map(([name, v]) => [v.meaning ? `${name} (${v.meaning})` : name, text(v)]),
      },
    };
  }
  // An observation, or a series of one thing: the last value that was measured.
  const measured = [...records].reverse().find((r) => r.value !== null && r.value !== undefined);
  const shown = measured ?? last;
  const value =
    shown.value === null || shown.value === undefined
      ? t.noValue
      : numberText(shown.value, shown.unit ?? "", lang, signed(shown.meaning));
  const when = (r: OpenRecord) => timeText(r, lang, true) ?? "";
  const sub =
    records.length > 1
      ? [
          last === shown ? t.lastReading(when(last)) : `${t.at(when(shown))} · ${t.lastMissing(when(last))}`,
          t.readings(records.length),
          where,
        ].join(" · ")
      : [timeText(shown, lang), where].filter(Boolean).join(" · ");
  return {
    ...base,
    value,
    sub,
    trust: measured ? trustOf(measured) : "unmeasured",
    detail: {
      ...base.detail,
      values:
        records.length > 1
          ? records.slice(-6).map((r) => [when(r), r.value === null || r.value === undefined ? t.noValue : numberText(r.value, r.unit ?? "", lang)])
          : undefined,
      sentence: shown.meaning,
    },
  };
}

/** A row for the EGMS velocity of one component at the point. */
export function groundRow(component: "U" | "E", w: Worded<Velocity>, t: Text, lang: Lang): Row {
  const f = w.facts;
  const v = f.velocity_mm_per_year;
  const n = v === null ? "" : Math.abs(v).toLocaleString(t.locale, { maximumFractionDigits: 1 });
  const value =
    v === null
      ? t.trust.unmeasured
      : v === 0
        ? t.zero
        : component === "U"
          ? v > 0
            ? t.up(n)
            : t.down(n)
          : v > 0
            ? t.east(n)
            : t.west(n);
  const day = (d: string) =>
    new Date(d + "T00:00:00Z").toLocaleDateString(t.locale, { dateStyle: "medium", timeZone: "UTC" });
  const when =
    f.window.exact && f.window.first && f.window.last
      ? t.between(day(f.window.first), day(f.window.last))
      : t.releaseYears(f.window.release);
  const record = w.records?.[0];
  return {
    key: `egms-${component}`,
    colour: "egms",
    title: component === "U" ? t.groundU : t.groundE,
    value,
    sub: when,
    trust: !f.measured ? "unmeasured" : f.reliability.reliable ? "reliable" : "weak",
    detail: {
      sentence: w.text.split(/(?<=\.) (?=Dati:|Data:)/)[0],
      notes: [],
      source: { name: record?.source.name ?? "EGMS", url: "https://egms.land.copernicus.eu/" },
      when,
      score: f.reliability.score,
      method: record?.reliability?.method,
      licence: record?.source.licence ?? f.licence,
      attribution: record?.source.attribution,
      slug: "egms",
    },
  };
}
