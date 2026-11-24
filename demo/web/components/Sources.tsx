"use client";

import type { Text } from "@/lib/i18n";
import { SOURCE_COLOURS } from "@/lib/records";
import type { SourcesAnswer } from "@/lib/types";

/** The sources the page reads, each as it is, and the files refused with their reasons. */
export default function Sources({ answer, t }: { answer: SourcesAnswer | null; t: Text }) {
  if (!answer) return <p>{t.loading}</p>;
  return (
    <div className="small">
      <p>{t.sourcesIntro}</p>
      <ul className="list-unstyled">
        <li className="egms-source mb-3">
          <span className="egms-swatch egms-swatch-egms" aria-hidden="true" /> {t.egmsLive(answer.egms)}
        </li>
        {answer.sources.length === 0 && <li className="text-secondary">{t.noSources}</li>}
        {answer.sources.map((s, i) => (
          <li key={s.name} className="egms-source mb-3">
            <div className="fw-semibold">
              <span className="egms-swatch" style={{ background: SOURCE_COLOURS[i % SOURCE_COLOURS.length] }} aria-hidden="true" />{" "}
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.name}
                </a>
              ) : (
                s.name
              )}{" "}
              <span className="text-secondary fw-normal">· {t.recordsOf(s.records)}</span>
            </div>
            <div>
              {t.licenceLabel}: {s.licence}
            </div>
            {s.attribution && <div className="text-secondary">{s.attribution}</div>}
            <div>
              {t.madeBy}: {s.made_by.join(", ")}
            </div>
            <div>
              {t.whatLabel}: {s.properties.join("; ")}
            </div>
            <div className="text-secondary">
              {t.filesLabel}: {s.files.join(", ")}
            </div>
          </li>
        ))}
      </ul>
      {answer.refused.length > 0 && (
        <div className="alert alert-warning small">
          <div className="fw-semibold">{t.refusedTitle}</div>
          <p className="mb-1">{t.refusedIntro}</p>
          <ul className="mb-0 ps-3">
            {answer.refused.map((r) => (
              <li key={r.file}>
                <code>{r.file}</code>
                <ul className="ps-3">
                  {r.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
