"use client";

// One row per source: what it says of a place, how far to trust it, and, opened, where
// it comes from. Used by the card of a point.

import type { Text } from "@/lib/i18n";
import type { Row, TrustKind } from "@/lib/rows";
import type { Lang } from "@/lib/start";
import { Sparkline } from "./Charts";

export function Dot({ trust, t }: { trust: TrustKind; t: Text }) {
  return (
    <span className={`egms-dot egms-dot-${trust}`}>
      <span aria-hidden="true" />
      {t.trust[trust]}
    </span>
  );
}

export function Swatch({ colour }: { colour: string }) {
  return colour === "egms" ? (
    <span className="egms-swatch egms-swatch-egms" aria-hidden="true" />
  ) : (
    <span
      className="egms-swatch"
      style={{ background: colour }}
      aria-hidden="true"
    />
  );
}

export function RowView({
  row,
  t,
  lang,
  open,
  onToggle,
}: {
  row: Row;
  t: Text;
  lang: Lang;
  open: boolean;
  onToggle: () => void;
}) {
  const d = row.detail;
  return (
    <li className={`egms-row ${open ? "open" : ""}`}>
      <button
        type="button"
        className="egms-row-head"
        aria-expanded={open}
        onClick={onToggle}
      >
        <Swatch colour={row.colour} />
        <span className="egms-row-text">
          <span className="egms-row-title">{row.title}</span>
          <span className="egms-row-value">{row.value}</span>
          <span className="egms-row-sub">{row.sub}</span>
          {row.series && (
            <Sparkline
              values={row.series}
              label={`${row.title}: ${row.series.length}`}
            />
          )}
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
              {d.score !== null
                ? ` (${t.score(d.score.toLocaleString(t.locale))})`
                : ""}
            </dd>
            <dt>{t.licenceLabel}</dt>
            <dd>
              {d.licence}
              {d.attribution && (
                <span className="text-secondary"> · {d.attribution}</span>
              )}
            </dd>
          </dl>
          <a href={`/dati?lang=${lang}#${d.slug}`}>{t.howMade}</a>
        </div>
      )}
    </li>
  );
}
