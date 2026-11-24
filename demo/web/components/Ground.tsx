"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import AddSource from "@/components/AddSource";
import { HowMade, RecordCard } from "@/components/RecordCard";
import Sources from "@/components/Sources";
import { reasons, TEXT, type Text } from "@/lib/i18n";
import { near, NEAR_M, SOURCE_COLOURS } from "@/lib/records";
import type { Lang, Start, Tab, Tiles } from "@/lib/start";
import type {
  Box,
  Failed,
  MovingAnswer,
  OpenRecord,
  PlaceAnswer,
  RecordsAnswer,
  SourcesAnswer,
  Velocity,
  Worded,
} from "@/lib/types";

// Leaflet needs a window: the map is drawn in the browser only.
const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

const STEPS = ["≤ −20", "−10", "−5", "−2", "±2", "+5", "+10", "+20", "≥ +20"];
const COLOURS = ["#67000d", "#cb181d", "#fb6a4a", "#fcbba1", "#f0f0f0", "#9ecae1", "#4292c6", "#08519c", "#08306b"];

async function ask<T>(path: string, params: Record<string, string | number>): Promise<T | Failed> {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  try {
    const answer = await fetch(`/api/${path}?${query}`, { cache: "no-store" });
    return (await answer.json()) as T | Failed;
  } catch (error) {
    return { error: error instanceof Error ? error.message : "—" };
  }
}

/** The EGMS numbers of the card, as code anyone can run. */
const egmsCode = (lon: number, lat: number) => `import asyncio

from egms_client import EgmsArchive
from egms_client.facts import to_records, velocity


async def main() -> None:
    async with EgmsArchive() as archive:  # the CLMS key, from the environment
        point = await archive.velocity_at(${lon.toFixed(5)}, ${lat.toFixed(5)})
        facts = velocity([point.file], point.lon, point.lat, release=point.release)
        print(to_records(facts))


asyncio.run(main())`;

/** The records EGMS gives live are on the EGMS card: the files of egms-client are not repeated. */
const fromEgms = (r: OpenRecord) => r.made_by.name === "egms-client";

const failed = (x: unknown): x is Failed => typeof x === "object" && x !== null && "error" in x;

function Component({ name, worded, t }: { name: string; worded: Worded<Velocity>; t: Text }) {
  const f = worded.facts;
  const r = f.reliability;
  const badge = !f.measured ? (
    <span className="badge bg-secondary">{t.notMeasured}</span>
  ) : r.reliable ? (
    <span className="badge bg-success">{t.reliable}</span>
  ) : (
    <span className="badge bg-warning text-dark">{t.notReliable}</span>
  );
  return (
    <section className="mb-3">
      <h3 className="h6 d-flex align-items-center gap-2 mb-1">
        {name} {badge}
      </h3>
      <p className="mb-1">{worded.text.split(/(?<=\.) (?=Dati:|Data:)/)[0]}</p>
      <ul className="small text-secondary mb-0 ps-3">
        {reasons(r, f.measured, t).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </section>
  );
}

export default function Ground({ start, tiles }: { start: Start; tiles: Tiles }) {
  const [lang, setLang] = useState<Lang>(start.lang);
  const t = TEXT[lang];
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(
    start.given ? { lat: start.lat, lon: start.lon } : null,
  );
  const [place, setPlace] = useState<PlaceAnswer | Failed | null>(null);
  const [view, setView] = useState<Box | null>(null);
  const [moving, setMoving] = useState<MovingAnswer | Failed | null>(null);
  const [showMoving, setShowMoving] = useState(false);
  const [tab, setTab] = useState<Tab>(start.tab);
  const [bounds, setBounds] = useState<Box | null>(null);
  const [records, setRecords] = useState<RecordsAnswer | null>(null);
  const [sources, setSources] = useState<SourcesAnswer | null>(null);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    if (!point) return;
    let live = true;
    setPlace(null);
    ask<PlaceAnswer>("place", { lat: point.lat.toFixed(5), lon: point.lon.toFixed(5), lang }).then((a) => {
      if (live) setPlace(a);
    });
    return () => {
      live = false;
    };
  }, [point, lang]);

  useEffect(() => {
    if (!showMoving || !view) {
      setMoving(null);
      return;
    }
    let live = true;
    ask<MovingAnswer>("moving", { ...view, lang }).then((a) => {
      if (live) setMoving(a);
    });
    return () => {
      live = false;
    };
  }, [showMoving, view, lang]);

  // The sources once, and again each time their tab is opened: a file may have been added.
  useEffect(() => {
    if (sources && tab !== "sources") return;
    let live = true;
    ask<SourcesAnswer>("sources", {}).then((a) => {
      if (live && !failed(a)) setSources(a);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

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

  const onPoint = useCallback((lat: number, lon: number) => {
    setPoint({ lat, lon });
    setTab("point");
  }, []);
  const colour = (r: OpenRecord) => {
    const i = sources?.sources.findIndex((s) => s.name === r.source.name) ?? -1;
    return i < 0 ? "#5c6f82" : SOURCE_COLOURS[i % SOURCE_COLOURS.length];
  };
  const shown = (records?.records ?? []).filter((item) => !fromEgms(item.record));
  const groups = point ? near(shown, point.lon, point.lat, fromEgms) : [];
  const egmsRecords = place && !failed(place) ? [...(place.vertical.records ?? []), ...(place.east?.records ?? [])] : [];
  const window = place && !failed(place) ? place.vertical.facts.window : null;

  return (
    <div className={start.embed ? "egms embed" : "egms"}>
      {!start.embed && (
        <header className="it-header-center-wrapper">
          <div className="container">
            <div className="it-header-center-content-wrapper d-flex justify-content-between align-items-center">
              <div className="it-brand-wrapper">
                <div className="it-brand-text">
                  <div className="it-brand-title">{start.place ?? t.title}</div>
                  <div className="it-brand-tagline d-none d-md-block">{start.place ? t.title + " · " + t.tagline : t.tagline}</div>
                </div>
              </div>
              <div className="btn-group" role="group" aria-label={t.language}>
                {(["it", "en"] as Lang[]).map((l) => (
                  <button
                    key={l}
                    type="button"
                    className={`btn btn-sm ${l === lang ? "btn-light" : "btn-outline-light"}`}
                    aria-pressed={l === lang}
                    onClick={() => setLang(l)}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </header>
      )}

      <main className="egms-main">
        <MapView
          start={start}
          tiles={tiles}
          text={t}
          point={point}
          moving={moving && !failed(moving) ? moving.facts.cells : []}
          onPoint={onPoint}
          onView={setView}
          onBounds={setBounds}
          records={shown}
          colour={colour}
        />

        <aside className="egms-card card shadow-sm" aria-live="polite">
          <div className="card-body">
            <ul className="nav nav-tabs egms-tabs mb-3" role="tablist">
              {(
                [
                  ["point", t.tabPoint],
                  ["sources", t.tabSources],
                  ["add", t.tabAdd],
                ] as [Tab, string][]
              ).map(([key, label]) => (
                <li className="nav-item" key={key} role="presentation">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={tab === key}
                    className={`nav-link ${tab === key ? "active" : ""}`}
                    onClick={() => setTab(key)}
                  >
                    {label}
                  </button>
                </li>
              ))}
            </ul>

            {tab === "sources" && <Sources answer={sources} t={t} />}
            {tab === "add" && <AddSource t={t} />}

            {tab === "point" && (
            <>
            {!point && <p className="mb-2">{t.hint}</p>}
            {point && (
              <h2 className="h6 text-uppercase text-secondary mb-2">
                {point.lat.toFixed(4)}° N, {point.lon.toFixed(4)}° E
              </h2>
            )}
            {point && <h3 className="h5 mb-2">{t.egmsTitle}</h3>}
            {point && !place && <p className="mb-2">{t.loading}</p>}
            {place && failed(place) && (
              <div className="alert alert-warning small mb-2">
                {place.not_measured === false ? t.outside : t.failed}: {place.error}
              </div>
            )}
            {place && !failed(place) && (
              <>
                <Component name={t.vertical} worded={place.vertical} t={t} />
                {place.east ? (
                  <Component name={t.east} worded={place.east} t={t} />
                ) : (
                  <p className="small text-secondary">{t.noEast}</p>
                )}
                {window && (
                  <p className="small mb-2">
                    {window.exact && window.first && window.last
                      ? t.window(window.first, window.last)
                      : t.windowYears(window.release)}
                  </p>
                )}
                {place.source === "demo" && <p className="small text-secondary mb-2">{t.demo}</p>}
                {egmsRecords.length > 0 && <HowMade items={egmsRecords} t={t} code={egmsCode(point!.lon, point!.lat)} />}
              </>
            )}

            {point && (
              <section className="mt-3 pt-2 border-top">
                <h3 className="h5 mb-2">{t.nearTitle(NEAR_M / 1000)}</h3>
                {groups.length === 0 && <p className="small text-secondary">{t.noneNear}</p>}
                {groups.map((g) => (
                  <RecordCard key={g.key} group={g} t={t} lang={lang} />
                ))}
                {groups.length > 0 && <p className="small text-secondary">{t.notesLang}</p>}
              </section>
            )}

            {!view && <p className="small text-secondary mb-2">{t.zoomIn}</p>}
            {view && (
              <div className="mb-2">
                <button type="button" className="btn btn-sm btn-outline-primary" onClick={() => setShowMoving((s) => !s)}>
                  {showMoving ? t.hideMoving : t.showMoving}
                </button>
                {moving && !failed(moving) && <p className="small mt-2 mb-0">{moving.text.split(/(?<=\.) (?=Dati:|Data:)/)[0]}</p>}
                {moving && failed(moving) && <p className="small text-secondary mt-2 mb-0">{t.outside}</p>}
              </div>
            )}

            <div className="egms-legend small" aria-label={t.legend}>
              <div className="fw-semibold">{t.legend}</div>
              <div className="d-flex">
                {COLOURS.map((c, i) => (
                  <span key={c} className="egms-step" style={{ background: c }} title={STEPS[i]} />
                ))}
              </div>
              <div className="d-flex justify-content-between text-secondary">
                <span>{t.legendDown}</span>
                <span>{t.legendUp}</span>
              </div>
              <div className="d-flex align-items-center gap-1 text-secondary">
                <span className="egms-step egms-veil" /> {t.legendNone}
              </div>
            </div>

            </>
            )}

            <p className="small mt-3 mb-0 fw-semibold">{t.notAlert}</p>
          </div>
        </aside>
      </main>

      <footer className="egms-footer small">
        {t.credit}{" "}
        <a href="https://agentengineering.it/egms-client/" target="_blank" rel="noreferrer">
          {t.source}
        </a>
      </footer>
    </div>
  );
}
