"use client";

import type { Text } from "@/lib/i18n";
import { notMeasured, numberText, timeText, type Group } from "@/lib/records";
import type { Lang } from "@/lib/start";
import type { Filed, OpenRecord } from "@/lib/types";

/** The libraries of the series, and where their code is. A record made by another is shown the same. */
const LIBRARIES: Record<string, string> = {
  "egms-client": "https://github.com/agent-engineering-studio/egms-client",
  "dpc-radar": "https://github.com/agent-engineering-studio/dpc-radar",
  "rainfall-thresholds": "https://github.com/agent-engineering-studio/rainfall-thresholds",
  "ispra-idrogeo": "https://github.com/agent-engineering-studio/ispra-idrogeo",
  "firms-client": "https://github.com/agent-engineering-studio/firms-client",
  "effis-client": "https://github.com/agent-engineering-studio/effis-client",
};

/** The badge of how far to trust a record: from the record, never guessed. */
export function Trust({ r, t }: { r: OpenRecord; t: Text }) {
  if (notMeasured(r)) return <span className="badge bg-secondary">{t.notMeasured}</span>;
  const rel = r.reliability;
  if (!rel || rel.reliable === null || rel.reliable === undefined)
    return <span className="badge bg-light text-dark border">{t.trustLabel}: {t.trustUnknown}</span>;
  return rel.reliable ? (
    <span className="badge bg-success">{t.reliable}</span>
  ) : (
    <span className="badge bg-warning text-dark">{t.notReliable}</span>
  );
}

/** A "+" before a value only when its meaning says what a positive value is. */
const signed = (meaning?: string) => /positiv/i.test(meaning ?? "");

function value(r: OpenRecord, lang: Lang, t: Text): string {
  if (r.value === null || r.value === undefined) return t.gap;
  return numberText(r.value, r.unit ?? "", lang, signed(r.meaning));
}

/** Source, time, trust and licence: the same footer on every card. */
export function Footer({ r, t, lang }: { r: OpenRecord; t: Text; lang: Lang }) {
  const rel = r.reliability;
  const score = rel?.score;
  return (
    <dl className="egms-facts small mb-1">
      <dt>{t.sourceLabel}</dt>
      <dd>{r.source.url ? <a href={r.source.url} target="_blank" rel="noreferrer">{r.source.name}</a> : r.source.name}</dd>
      <dt>{t.whenLabel}</dt>
      <dd>{timeText(r, lang) ?? t.noDates}</dd>
      <dt>{t.trustLabel}</dt>
      <dd>
        {!rel
          ? t.trustUnknown
          : [
              score !== null && score !== undefined ? t.score(score.toLocaleString(t.locale)) : null,
              rel.reliable === true ? t.reliableShort : rel.reliable === false ? t.notReliableShort : null,
            ]
              .filter(Boolean)
              .join(", ") || t.trustUnknown}
        {rel && <div className="text-secondary">{t.methodLabel}: {rel.method}</div>}
      </dd>
      <dt>{t.licenceLabel}</dt>
      <dd>
        {r.source.licence}
        {r.source.attribution && <div className="text-secondary">{r.source.attribution}</div>}
      </dd>
    </dl>
  );
}

/** How a record was made: who wrote it, the file, the command that checks it, the record itself. */
export function HowMade({ items, t, code }: { items: Filed[] | OpenRecord[]; t: Text; code?: string }) {
  const first = items[0];
  const record = "record" in first ? first.record : first;
  const file = "record" in first ? first.file : null;
  const repo = LIBRARIES[record.made_by.name];
  const shown = items.slice(-3).map((i) => ("record" in i ? i.record : i));
  return (
    <details className="egms-how small">
      <summary>{t.howMade}</summary>
      <p className="mb-1">
        {t.madeBy}{" "}
        {repo ? (
          <a href={repo} target="_blank" rel="noreferrer">
            {record.made_by.name}
          </a>
        ) : (
          record.made_by.name
        )}
        {record.made_by.version ? ` ${record.made_by.version}` : ""}. {file ? t.fromFile(file) : ""}
      </p>
      {repo && !code && (
        <>
          <p className="mb-1">{t.install}</p>
          <pre>
            <code>pip install {record.made_by.name}</code>
          </pre>
        </>
      )}
      {code && (
        <>
          <p className="mb-1">{t.egmsCode}</p>
          <pre>
            <code>{code}</code>
          </pre>
        </>
      )}
      {file && (
        <>
          <p className="mb-1">{t.checkIt}</p>
          <pre>
            <code>egms records {file}</code>
          </pre>
        </>
      )}
      <p className="mb-1">{t.theRecord}</p>
      <pre className="egms-json">
        <code>{JSON.stringify(shown.length === 1 ? shown[0] : shown, null, 2)}</code>
      </pre>
    </details>
  );
}

/** One card for a group of records: a fact, one observation, or a series of one thing. */
export function RecordCard({ group, t, lang }: { group: Group; t: Text; lang: Lang }) {
  const last = group.items[group.items.length - 1].record;
  // A series has a trust per reading: it is in the table, not one badge for all.
  const series = last.kind === "observation" && group.items.length > 1;
  const title = last.kind === "fact" ? last.question : `${last.thing ?? last.source.name} · ${last.property}`;
  return (
    <section className="egms-record mb-3">
      <h3 className="h6 d-flex flex-wrap align-items-center gap-2 mb-1">
        <span>{title}</span> {series ? null : <Trust r={last} t={t} />}
      </h3>
      <p className="small text-secondary mb-1">{t.away(Math.round(group.distance))}</p>
      {last.kind === "fact" && last.values && (
        <ul className="list-unstyled mb-1">
          {Object.entries(last.values).map(([name, q]) => (
            <li key={name}>
              <span className="text-secondary">{name}</span>:{" "}
              <strong>{q.value === null ? t.gap : numberText(q.value, q.unit, lang, signed(q.meaning))}</strong>
              {q.meaning && <span className="small text-secondary"> · {q.meaning}</span>}
            </li>
          ))}
        </ul>
      )}
      {last.kind === "observation" && group.items.length === 1 && (
        <p className="mb-1">
          <strong>{value(last, lang, t)}</strong>
          {last.meaning && <span className="small text-secondary"> · {last.meaning}</span>}
        </p>
      )}
      {last.kind === "observation" && group.items.length > 1 && (
        <>
          <p className="small mb-1">{t.series(group.items.length)}</p>
          <table className="table table-sm small mb-1">
            <tbody>
              {group.items.slice(-5).map(({ record: r }, i) => (
                <tr key={i}>
                  <td className="text-nowrap">{timeText(r, lang, true)}</td>
                  <td className="text-end fw-semibold">{value(r, lang, t)}</td>
                  <td className="text-secondary">{r.quality?.flags.map((f) => t.flags[f] ?? f).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {last.notes && last.notes.length > 0 && (
        <ul className="small text-secondary mb-1 ps-3">
          {last.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <Footer r={last} t={t} lang={lang} />
      <HowMade items={group.items} t={t} />
    </section>
  );
}
