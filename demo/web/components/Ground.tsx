"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { reasons, TEXT, type Text } from "@/lib/i18n";
import type { Lang, Start, Tiles } from "@/lib/start";
import type { Box, Failed, MovingAnswer, PlaceAnswer, Velocity, Worded } from "@/lib/types";

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

  const onPoint = useCallback((lat: number, lon: number) => setPoint({ lat, lon }), []);
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
        />

        <aside className="egms-card card shadow-sm" aria-live="polite">
          <div className="card-body">
            {!point && <p className="mb-2">{t.hint}</p>}
            {point && !place && <p className="mb-2">{t.loading}</p>}
            {place && failed(place) && (
              <div className="alert alert-warning small mb-2">
                {place.not_measured === false ? t.outside : t.failed}: {place.error}
              </div>
            )}
            {place && !failed(place) && (
              <>
                <h2 className="h6 text-uppercase text-secondary mb-2">
                  {point!.lat.toFixed(4)}° N, {point!.lon.toFixed(4)}° E
                </h2>
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
              </>
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
