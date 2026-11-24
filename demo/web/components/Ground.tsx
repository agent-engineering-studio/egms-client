"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { TEXT, type Text } from "@/lib/i18n";
import { near, SOURCE_COLOURS } from "@/lib/records";
import { groundRow, recordRow, type Row, type TrustKind } from "@/lib/rows";
import type { Lang, Start, Tiles } from "@/lib/start";
import type { GroundState } from "./MapView";
import type {
  Area,
  Box,
  Failed,
  Health,
  MovingAnswer,
  OpenRecord,
  PlaceAnswer,
  RecordsAnswer,
  SourcesAnswer,
} from "@/lib/types";

// Leaflet needs a window: the map is drawn in the browser only.
const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

const COLOURS = ["#67000d", "#cb181d", "#fb6a4a", "#fcbba1", "#f0f0f0", "#9ecae1", "#4292c6", "#08519c", "#08306b"];

export async function ask<T>(path: string, params: Record<string, string | number>): Promise<T | Failed> {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  try {
    const answer = await fetch(`/api/${path}?${query}`, { cache: "no-store" });
    return (await answer.json()) as T | Failed;
  } catch (error) {
    return { error: error instanceof Error ? error.message : "—" };
  }
}

export const failed = (x: unknown): x is Failed => typeof x === "object" && x !== null && "error" in x;

/** The records EGMS gives live are its own rows: the files of egms-client are not repeated. */
const fromEgms = (r: OpenRecord) => r.made_by.name === "egms-client";

function Dot({ trust, t }: { trust: TrustKind; t: Text }) {
  return (
    <span className={`egms-dot egms-dot-${trust}`}>
      <span aria-hidden="true" />
      {t.trust[trust]}
    </span>
  );
}

function Swatch({ colour }: { colour: string }) {
  return colour === "egms" ? (
    <span className="egms-swatch egms-swatch-egms" aria-hidden="true" />
  ) : (
    <span className="egms-swatch" style={{ background: colour }} aria-hidden="true" />
  );
}

function RowView({ row, t, lang, open, onToggle }: { row: Row; t: Text; lang: Lang; open: boolean; onToggle: () => void }) {
  const d = row.detail;
  return (
    <li className={`egms-row ${open ? "open" : ""}`}>
      <button type="button" className="egms-row-head" aria-expanded={open} onClick={onToggle}>
        <Swatch colour={row.colour} />
        <span className="egms-row-text">
          <span className="egms-row-title">{row.title}</span>
          <span className="egms-row-value">{row.value}</span>
          <span className="egms-row-sub">{row.sub}</span>
        </span>
        <Dot trust={row.trust} t={t} />
      </button>
      {open && (
        <div className="egms-row-detail">
          {d.sentence && <p>{d.sentence}</p>}
          {d.values && (
            <table className="egms-values">
              <tbody>
                {d.values.map(([name, value]) => (
                  <tr key={name}>
                    <th scope="row">{name}</th>
                    <td>{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {d.notes.length > 0 && (
            <ul className="egms-notes">
              {d.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          <dl className="egms-facts">
            <dt>{t.sourceLabel}</dt>
            <dd>
              {d.source.url ? (
                <a href={d.source.url} target="_blank" rel="noreferrer">
                  {d.source.name}
                </a>
              ) : (
                d.source.name
              )}
            </dd>
            <dt>{t.whenLabel}</dt>
            <dd>{d.when ?? t.noDates}</dd>
            <dt>{t.trustLabel}</dt>
            <dd>
              {t.trust[row.trust]}
              {d.score !== null ? ` (${t.score(d.score.toLocaleString(t.locale))})` : ""}
            </dd>
            <dt>{t.licenceLabel}</dt>
            <dd>
              {d.licence}
              {d.attribution && <span className="text-secondary"> · {d.attribution}</span>}
            </dd>
          </dl>
          <a href={`/dati?lang=${lang}#${d.slug}`}>{t.howMade}</a>
        </div>
      )}
    </li>
  );
}

export default function Ground({ start, tiles }: { start: Start; tiles: Tiles }) {
  const [lang, setLang] = useState<Lang>(start.lang);
  const t = TEXT[lang];
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(
    start.given ? { lat: start.lat, lon: start.lon } : null,
  );
  const [place, setPlace] = useState<PlaceAnswer | Failed | null>(null);
  const [area, setArea] = useState<Area | null>(null);
  const [outside, setOutside] = useState(false);
  const [bounds, setBounds] = useState<Box | null>(null);
  const [records, setRecords] = useState<RecordsAnswer | null>(null);
  const [sources, setSources] = useState<SourcesAnswer | null>(null);
  const [moving, setMoving] = useState<MovingAnswer | Failed | null>(null);
  const [layersOpen, setLayersOpen] = useState(false);
  const [showGround, setShowGround] = useState(true);
  const [showMoving, setShowMoving] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [slow, setSlow] = useState(false);
  const [groundState, setGroundState] = useState<GroundState>("none");
  const [groundMissing, setGroundMissing] = useState<string[]>([]);
  const [groundSince, setGroundSince] = useState(0);
  // On a phone the panel is a sheet: low, to see the map, or high, to read.
  const [sheet, setSheet] = useState<"low" | "high">(start.given ? "high" : "low");

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  // The area of the page: the map stays in it, and a point given outside it is dropped.
  useEffect(() => {
    let live = true;
    ask<Health>("health", {}).then((h) => {
      if (!live || failed(h)) return;
      setArea(h.area);
      setPoint((p) =>
        p && p.lon >= h.area.west && p.lon <= h.area.east && p.lat >= h.area.south && p.lat <= h.area.north ? p : null,
      );
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    ask<SourcesAnswer>("sources", {}).then((a) => {
      if (live && !failed(a)) setSources(a);
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!point) return;
    let live = true;
    setPlace(null);
    setSlow(false);
    // The first answer in an area may wait for a download from the archive: say so.
    const wait = window.setTimeout(() => live && setSlow(true), 2000);
    ask<PlaceAnswer>("place", { lat: point.lat.toFixed(5), lon: point.lon.toFixed(5), lang }).then((a) => {
      if (live) setPlace(a);
      window.clearTimeout(wait);
    });
    return () => {
      live = false;
      window.clearTimeout(wait);
    };
  }, [point, lang]);

  const onGround = useCallback((state: GroundState, missing?: string[]) => {
    setGroundState(state);
    setGroundMissing(missing ?? []);
    if (state === "loading") setGroundSince(Date.now());
  }, []);
  // A map that takes more than 3 seconds is being downloaded: tick to update the badge.
  const [, tick] = useState(0);
  useEffect(() => {
    if (groundState !== "loading") return;
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [groundState]);
  const archive = sources?.egms === "archive";

  useEffect(() => {
    if (!bounds) return;
    let live = true;
    const pad = 0.05;
    ask<RecordsAnswer>("records", {
      west: (bounds.west - pad).toFixed(4),
      south: (bounds.south - pad).toFixed(4),
      east: (bounds.east + pad).toFixed(4),
      north: (bounds.north + pad).toFixed(4),
    }).then((a) => {
      if (live && !failed(a)) setRecords(a);
    });
    return () => {
      live = false;
    };
  }, [bounds]);

  useEffect(() => {
    if (!showMoving || !area) {
      setMoving(null);
      return;
    }
    let live = true;
    const { west, south, east, north } = area;
    ask<MovingAnswer>("moving", { west, south, east, north, lang }).then((a) => {
      if (live) setMoving(a);
    });
    return () => {
      live = false;
    };
  }, [showMoving, area, lang]);

  const onOutside = useCallback(() => setOutside(true), []);
  const onPoint = useCallback((lat: number, lon: number) => {
    setOutside(false);
    setPoint({ lat, lon });
    setOpen(null);
    setSheet("high");
  }, []);

  const names = (sources?.sources ?? []).filter((s) => !s.made_by.every((m) => m === "egms-client")).map((s) => s.name);
  const colourOf = useCallback(
    (name: string) => {
      const i = names.indexOf(name);
      return i < 0 ? "#5c6f82" : SOURCE_COLOURS[i % SOURCE_COLOURS.length];
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [names.join("|")],
  );
  const colour = useCallback((r: OpenRecord) => colourOf(r.source.name), [colourOf]);
  const shown = (records?.records ?? []).filter((i) => !fromEgms(i.record) && !hidden.has(i.record.source.name));

  const ground: Row[] =
    place && !failed(place)
      ? [groundRow("U", place.vertical, t, lang), ...(place.east ? [groundRow("E", place.east, t, lang)] : [])]
      : [];
  const others: Row[] = point
    ? near(shown, point.lon, point.lat, fromEgms).map((g) => recordRow(g, colourOf(g.items[0].record.source.name), t, lang))
    : [];
  const toggle = (key: string) => setOpen((o) => (o === key ? null : key));

  return (
    <div className={start.embed ? "egms embed" : "egms"}>
      {!start.embed && (
        <header className="egms-header">
          <div className="egms-brand">
            <div className="egms-brand-title">{start.place ?? t.title}</div>
            <div className="egms-brand-tagline">{start.place ? t.title : t.tagline}</div>
          </div>
          <nav className="egms-nav">
            <a href={`/dati?lang=${lang}`} className="egms-nav-link">
              {t.dataLink}
            </a>
            <button
              type="button"
              className="egms-lang"
              aria-label={`${t.language}: ${lang === "it" ? "English" : "Italiano"}`}
              onClick={() => setLang(lang === "it" ? "en" : "it")}
            >
              {lang === "it" ? "EN" : "IT"}
            </button>
          </nav>
        </header>
      )}

      <main className="egms-main">
        <div className="egms-map-wrap">
          <MapView
            start={start}
            tiles={tiles}
            text={t}
            point={point}
            showGround={showGround}
            moving={showMoving && moving && !failed(moving) ? moving.facts.cells : []}
            records={shown}
            colour={colour}
            onPoint={onPoint}
            area={area}
            onOutside={onOutside}
            onBounds={setBounds}
            onGround={onGround}
          />

          {groundState !== "ready" && groundState !== "none" && (
            <div className={`egms-map-state ${groundState}`} role="status">
              {groundState === "failed"
                ? t.mapFailed
                : groundState === "partial"
                  ? t.mapPartial(groundMissing)
                  : archive && Date.now() - groundSince > 3000
                    ? t.mapDownloading
                    : t.mapLoading}
            </div>
          )}

          <div className={`egms-layers ${layersOpen ? "open" : ""}`}>
            <button type="button" className="egms-layers-toggle" aria-expanded={layersOpen} onClick={() => {
                setLayersOpen((o) => !o);
                setSheet("low");
              }}>
              {t.layers}
            </button>
            {layersOpen && (
              <div className="egms-layers-body">
                <label className="egms-check">
                  <input type="checkbox" checked={showGround} onChange={(e) => setShowGround(e.target.checked)} />
                  <Swatch colour="egms" /> {t.layerGround}
                </label>
                {showGround && (
                  <div className="egms-legend">
                    <div className="egms-ramp">
                      {COLOURS.map((c) => (
                        <span key={c} style={{ background: c }} />
                      ))}
                    </div>
                    <div className="egms-ramp-words">
                      <span>{t.legendDown}</span>
                      <span>
                        <span className="egms-veil" /> {t.legendNone}
                      </span>
                      <span>{t.legendUp}</span>
                    </div>
                    {groundState === "partial" && (
                      <div className="egms-ramp-words">
                        <span>
                          <span className="egms-stripes" /> {t.legendMissing}
                        </span>
                      </div>
                    )}
                  </div>
                )}
                <label className="egms-check">
                  <input type="checkbox" checked={showMoving} onChange={(e) => setShowMoving(e.target.checked)} />
                  <span className="egms-swatch egms-swatch-moving" aria-hidden="true" /> {t.layerMoving}
                </label>
                {names.map((name) => (
                  <label className="egms-check" key={name}>
                    <input
                      type="checkbox"
                      checked={!hidden.has(name)}
                      onChange={(e) =>
                        setHidden((h) => {
                          const next = new Set(h);
                          if (e.target.checked) next.delete(name);
                          else next.add(name);
                          return next;
                        })
                      }
                    />
                    <Swatch colour={colourOf(name)} /> {name}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        <aside className={`egms-panel sheet-${sheet}`} aria-live="polite">
          <button
            type="button"
            className="egms-handle"
            aria-label={sheet === "low" ? t.openPanel : t.closePanel}
            onClick={() => setSheet((s) => (s === "low" ? "high" : "low"))}
          >
            <span />
          </button>
          <div className="egms-panel-body">
            {outside && area && <p className="egms-warning">{t.outsideArea(area.radius_km)}</p>}
            {!point && <p className="egms-hint">{t.hint}</p>}
            {point && (
              <>
                <h2 className="egms-place">
                  {t.here} · {point.lat.toFixed(4)}° N, {point.lon.toFixed(4)}° E
                </h2>
                {!place && <p className="text-secondary">{slow && archive ? t.downloading : t.loading}</p>}
                {place && failed(place) && (
                  <p className="egms-warning">
                    {place.missing_tiles
                      ? t.missingTiles(place.missing_tiles)
                      : place.not_measured === false
                        ? t.outside
                        : `${t.failed}: ${place.error}`}
                  </p>
                )}
                <ul className="egms-rows">
                  {ground.map((row) => (
                    <RowView key={row.key} row={row} t={t} lang={lang} open={open === row.key} onToggle={() => toggle(row.key)} />
                  ))}
                </ul>
                {place && !failed(place) && place.source === "demo" && <p className="egms-small text-secondary">{t.demo}</p>}

                <h2 className="egms-place mt-3">{t.near}</h2>
                {others.length === 0 && <p className="egms-small text-secondary">{t.noneNear}</p>}
                <ul className="egms-rows">
                  {others.map((row) => (
                    <RowView key={row.key} row={row} t={t} lang={lang} open={open === row.key} onToggle={() => toggle(row.key)} />
                  ))}
                </ul>
                {others.length > 0 && <p className="egms-small text-secondary">{t.trustHelp}</p>}
              </>
            )}
            {area && <p className="egms-small text-secondary mt-3 mb-0">{t.areaNote(area.radius_km)}</p>}
            <p className="egms-small egms-alert-note">{t.notAlert}</p>
          </div>
        </aside>
      </main>

      {!start.embed && (
        <footer className="egms-footer">
          {t.credit}{" "}
          <a href="https://github.com/agent-engineering-studio/egms-client" target="_blank" rel="noreferrer">
            {t.source}
          </a>
        </footer>
      )}
    </div>
  );
}
