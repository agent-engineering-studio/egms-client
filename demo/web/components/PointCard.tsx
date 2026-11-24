"use client";

// The card of a point, over the map: what the ground does there, in a sentence, a
// chart and an icon; how far to trust it; and what the other sources say nearby.

import { useState } from "react";
import type { Text } from "@/lib/i18n";
import type { Row } from "@/lib/rows";
import type { Lang } from "@/lib/start";
import type { Failed, PlaceAnswer, Velocity, Worded } from "@/lib/types";
import { CompareBars, Meter, MotionIcon, Period } from "./Charts";
import { Dot, RowView } from "./Rows";

type Props = {
  point: { lat: number; lon: number };
  place: PlaceAnswer | Failed | null;
  loadingText: string;
  ground: Row[];
  others: Row[];
  t: Text;
  lang: Lang;
  onClose: () => void;
};

const failed = (x: unknown): x is Failed =>
  typeof x === "object" && x !== null && "error" in x;
const up = (v: number | null) =>
  v === null ? "#7a8290" : v >= 0 ? "#2171b5" : "#cb181d";

function Motion({
  w,
  row,
  t,
  around,
}: {
  w: Worded<Velocity>;
  row: Row;
  t: Text;
  around: boolean;
}) {
  const f = w.facts;
  const v = f.velocity_mm_per_year;
  const median = f.regional.median_mm_per_year;
  return (
    <div className="egms-card-motion">
      <div className="egms-card-head">
        <MotionIcon value={v} component={f.component} />
        <div>
          <div className="egms-card-title">{row.title}</div>
          <div className="egms-card-value">{row.value}</div>
        </div>
        <Dot trust={row.trust} t={t} />
      </div>
      {around && (v !== null || median !== null) && (
        <CompareBars
          label={t.cardCompare}
          unit={t.cardYear}
          locale={t.locale}
          bars={[
            { label: t.cardHere, value: v, colour: up(v) },
            {
              label: t.cardAround(f.regional.radius_m / 1000),
              value: median,
              colour: "#9aa3b0",
            },
          ]}
        />
      )}
      {f.measured && (
        <div className="egms-card-trust">
          <span>
            {t.cardReliability(
              f.reliability.score.toLocaleString(t.locale, {
                maximumFractionDigits: 2,
              }),
            )}
          </span>
          <Meter
            value={f.reliability.score}
            mark={f.reliability.reliable_from}
            label={t.cardReliability(String(f.reliability.score))}
          />
        </div>
      )}
      {v === null && (
        <p className="egms-small text-secondary mb-0">{row.sub}</p>
      )}
    </div>
  );
}

export default function PointCard({
  point,
  place,
  loadingText,
  ground,
  others,
  t,
  lang,
  onClose,
}: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const ok = place && !failed(place) ? place : null;
  const window_ = ok?.vertical.facts.window;
  return (
    <div className="egms-card">
      <div className="egms-card-top">
        <span className="egms-place">
          {t.here} · {point.lat.toFixed(4)}° N, {point.lon.toFixed(4)}° E
        </span>
        <button
          type="button"
          className="egms-card-close"
          aria-label={t.cardClose}
          onClick={onClose}
        >
          ×
        </button>
      </div>

      {!place && <p className="text-secondary mb-0">{loadingText}</p>}
      {place && failed(place) && (
        <p className="egms-warning mb-0">
          {place.missing_tiles
            ? t.missingTiles(place.missing_tiles)
            : place.not_measured === false
              ? t.outside
              : `${t.failed}: ${place.error}`}
        </p>
      )}

      {ok && (
        <>
          <h3 className="egms-card-section">{t.cardGround}</h3>
          <Motion w={ok.vertical} row={ground[0]} t={t} around />
          {ok.east && ground[1] && (
            <Motion w={ok.east} row={ground[1]} t={t} around={false} />
          )}
          {window_?.first && window_.last && (
            <div className="egms-card-trust">
              <span>
                {t.cardPeriod}: {ground[0].sub.split(" · ").pop()}
              </span>
              <Period
                first={window_.first}
                last={window_.last}
                label={t.cardPeriod}
              />
            </div>
          )}
          {ok.gap && (
            <div
              className={
                ok.gap.gap ? "egms-gap" : "egms-small text-secondary mb-2"
              }
            >
              {ok.gap.gap ? (
                <>
                  <strong>
                    <span className="egms-gap-swatch" /> {t.gapHere}
                  </strong>
                  <p className="mb-1">
                    {t.gapHereText(Math.round(ok.gap.measured_share * 100))}
                  </p>
                  <a href={`/dati?lang=${lang}#aggiungi`}>{t.addData}</a>
                </>
              ) : (
                t.gapCovered(Math.round(ok.gap.measured_share * 100))
              )}
            </div>
          )}
          <details className="egms-card-more">
            <summary>{t.cardDetails}</summary>
            <ul className="egms-rows">
              {ground.map((row) => (
                <RowView
                  key={row.key}
                  row={row}
                  t={t}
                  lang={lang}
                  open={open === row.key}
                  onToggle={() =>
                    setOpen((o) => (o === row.key ? null : row.key))
                  }
                />
              ))}
            </ul>
          </details>
          {ok.source === "demo" && (
            <p className="egms-small text-secondary">{t.demo}</p>
          )}
        </>
      )}

      <h3 className="egms-card-section">{t.cardOthers}</h3>
      {others.length === 0 ? (
        <p className="egms-small text-secondary mb-0">{t.noneNear}</p>
      ) : (
        <ul className="egms-rows">
          {others.map((row) => (
            <RowView
              key={row.key}
              row={row}
              t={t}
              lang={lang}
              open={open === row.key}
              onToggle={() => setOpen((o) => (o === row.key ? null : row.key))}
            />
          ))}
        </ul>
      )}
      <p className="egms-small egms-alert-note mb-0">{t.notAlert}</p>
    </div>
  );
}
