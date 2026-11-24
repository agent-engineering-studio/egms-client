"use client";

import { useEffect, useState } from "react";
import { ask, failed } from "@/components/Ground";
import { SOURCE_COLOURS } from "@/lib/records";
import { slug } from "@/lib/rows";
import type { Lang } from "@/lib/start";
import type { SourcesAnswer } from "@/lib/types";

/** The libraries of the series, and where their code is. */
const LIBRARIES: Record<string, string> = {
  "egms-client": "https://github.com/agent-engineering-studio/egms-client",
  "dpc-radar": "https://github.com/agent-engineering-studio/dpc-radar",
  "rainfall-thresholds": "https://github.com/agent-engineering-studio/rainfall-thresholds",
  "ispra-idrogeo": "https://github.com/agent-engineering-studio/ispra-idrogeo",
  "firms-client": "https://github.com/agent-engineering-studio/firms-client",
  "effis-client": "https://github.com/agent-engineering-studio/effis-client",
};

const SCHEMA =
  "https://github.com/agent-engineering-studio/egms-client/blob/main/src/egms_client/schema/opendata-record-v1.json";
const DESIGN = "https://agentengineering.it/egms-client/design/open-data-schema/";

const EGMS_CODE = `import asyncio

from egms_client import EgmsArchive
from egms_client.facts import to_records, velocity


async def main() -> None:
    async with EgmsArchive() as archive:  # the CLMS key, from the environment
        point = await archive.velocity_at(14.1205, 40.8225)  # Rione Terra, Pozzuoli
        facts = velocity([point.file], point.lon, point.lat, release=point.release)
        print(to_records(facts))


asyncio.run(main())`;

const COLUMNS: [string, string, Record<Lang, string>][] = [
  ["tempo", "time", { it: "giorno (2026-10-15) o giorno e ora con il fuso (2026-10-15T12:00:00Z)", en: "a day (2026-10-15) or a day and time with its zone (2026-10-15T12:00:00Z)" }],
  ["lon", "lon", { it: "longitudine, gradi (WGS84)", en: "longitude, degrees (WGS84)" }],
  ["lat", "lat", { it: "latitudine, gradi (WGS84)", en: "latitude, degrees (WGS84)" }],
  ["grandezza", "property", { it: "che cosa si misura: rainfall, water_level, soil_moisture…", en: "what is measured: rainfall, water_level, soil_moisture…" }],
  ["valore", "value", { it: "il numero; vuoto se non misurato (mai 0)", en: "the number; empty if not measured (never 0)" }],
  ["unità", "unit", { it: "codice UCUM: mm, m, Cel, %, mm/a", en: "UCUM code: mm, m, Cel, %, mm/a" }],
  ["fonte", "source", { it: "chi ha misurato", en: "who measured" }],
  ["licenza", "licence", { it: "per esempio CC BY 4.0", en: "for example CC BY 4.0" }],
];
const OPTIONAL: [string, string, Record<Lang, string>][] = [
  ["sensore", "thing", { it: "il nome del sensore: le sue letture diventano una serie", en: "the name of the sensor: its readings become a series" }],
  ["etichetta", "label", { it: "il nome per le persone, per esempio «Pioggia»", en: "the name for people, for example «Rain»" }],
  ["significato", "meaning", { it: "che cosa vuol dire il segno, obbligatorio per velocità e spostamenti", en: "what the sign means, required for velocities and displacements" }],
];

const TEXT = {
  it: {
    back: "← Torna alla mappa",
    title: "I dati e come riusarli",
    intro:
      "La mappa mette una accanto all'altra fonti di dati aperti diverse. Ognuna resta com'è, con i suoi limiti: la pagina non le mescola in un punteggio e non dà allerte. Qui c'è come è fatta ogni fonte, e come aggiungerne una.",
    sources: "Le fonti",
    egmsName: "EGMS, European Ground Motion Service (Copernicus)",
    egmsWhat:
      "Quanto si muove il suolo, misurato dai satelliti Sentinel-1: velocità verticale ed est-ovest, in mm/anno, su celle di 100 m. Le misure si fermano alla fine della finestra della release: non descrivono il suolo di oggi.",
    egmsTrust:
      "Quanto fidarsi: la quota di celle misurate entro 500 m e quanto la serie segue il modello. È una stima fatta da egms-client, non dall'EGMS.",
    egmsCode: "Gli stessi numeri, in Python:",
    licence: "Licenza",
    writer: "Scritto da",
    what: "Che cosa",
    method: "Quanto fidarsi, come è stimato",
    files: "File",
    records: (n: number) => `${n} record`,
    noMethod: "la fonte non lo dice",
    add: "Aggiungere una fonte",
    addIntro:
      "Una fonte entra nella pagina scrivendo i suoi dati come record, un formato JSON aperto, o come tabella CSV. Chi gestisce la pagina li carica dal backoffice o li mette nella cartella records/ del server.",
    templates: "I template",
    json: "Template JSON (record.json)",
    csv: "Template CSV (record.csv)",
    csvColumns: "Le colonne del CSV",
    csvNote: "Il separatore può essere la virgola o il punto e virgola, e il decimale la virgola, come salva un foglio di calcolo. Le intestazioni si possono scrivere anche in inglese.",
    required: "Obbligatorie",
    optional: "Facoltative",
    column: "Colonna",
    english: "In inglese",
    meaning: "Che cosa contiene",
    check: "Controllare un file prima di caricarlo",
    rules: "Le regole",
    rulesList: [
      "Dove non c'è misura il valore è vuoto (null), mai 0.",
      "Un valore con segno dice che cosa vuol dire il segno.",
      "Ogni record dice fonte, licenza, tempo e luogo, e quanto fidarsi, o che nessuno lo dice.",
      "Un record è una misura, non un'allerta: niente campi alert o rischio.",
    ],
    format: "Il formato",
    formatText: "Lo schema JSON dei record (opendata-record/v1) e il perché delle sue regole:",
    schema: "lo schema",
    design: "il documento di progetto",
    refused: "File rifiutati",
    refusedIntro: "Per chi gestisce la pagina: un file con anche un solo record non valido è rifiutato per intero.",
  },
  en: {
    back: "← Back to the map",
    title: "The data and how to reuse them",
    intro:
      "The map puts different open data sources side by side. Each stays as it is, with its limits: the page does not blend them into a score and gives no alerts. Here is how each source is made, and how to add one.",
    sources: "The sources",
    egmsName: "EGMS, European Ground Motion Service (Copernicus)",
    egmsWhat:
      "How much the ground moves, measured by the Sentinel-1 satellites: vertical and east-west velocity, in mm/year, on 100 m cells. The measurements stop at the end of the release window: they do not describe the ground of today.",
    egmsTrust:
      "How far to trust it: the share of measured cells within 500 m, and how well the series fits the model. An estimate made by egms-client, not by EGMS.",
    egmsCode: "The same numbers, in Python:",
    licence: "Licence",
    writer: "Written by",
    what: "What",
    method: "How far to trust it, how it is estimated",
    files: "Files",
    records: (n: number) => `${n} record${n === 1 ? "" : "s"}`,
    noMethod: "the source does not say",
    add: "Adding a source",
    addIntro:
      "A source joins the page by writing its data as records, an open JSON format, or as a CSV table. Whoever runs the page loads them from the back office or puts them in the folder records/ on the server.",
    templates: "The templates",
    json: "JSON template (record.json)",
    csv: "CSV template (record.csv)",
    csvColumns: "The columns of the CSV",
    csvNote: "The separator may be a comma or a semicolon, and a decimal a comma, as a spreadsheet saves it. The headers may also be in English.",
    required: "Required",
    optional: "Optional",
    column: "Column",
    english: "In English",
    meaning: "What it holds",
    check: "Check a file before loading it",
    rules: "The rules",
    rulesList: [
      "Where there is no measurement the value is empty (null), never 0.",
      "A signed value says what its sign means.",
      "Every record says its source, licence, time and place, and how far to trust it, or that nobody says.",
      "A record is a measurement, not an alert: no alert or risk fields.",
    ],
    format: "The format",
    formatText: "The JSON schema of the records (opendata-record/v1), and the reasons for its rules:",
    schema: "the schema",
    design: "the design document",
    refused: "Files refused",
    refusedIntro: "For whoever runs the page: a file with even one invalid record is refused whole.",
  },
};

export default function DataPage({ lang }: { lang: Lang }) {
  const t = TEXT[lang];
  const [answer, setAnswer] = useState<SourcesAnswer | null>(null);
  useEffect(() => {
    ask<SourcesAnswer>("sources", {}).then((a) => {
      if (!failed(a)) setAnswer(a);
    });
  }, []);
  // The anchor of a source, once the sources are there.
  useEffect(() => {
    if (answer && window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
  }, [answer]);
  const others = (answer?.sources ?? []).filter((s) => !s.made_by.every((m) => m === "egms-client"));

  return (
    <div className="egms-data">
      <header className="egms-header">
        <div className="egms-brand">
          <div className="egms-brand-title">{t.title}</div>
        </div>
        <nav className="egms-nav">
          <a href={`/?lang=${lang}`} className="egms-nav-link">
            {t.back}
          </a>
          <a href={`/dati?lang=${lang === "it" ? "en" : "it"}`} className="egms-lang">
            {lang === "it" ? "EN" : "IT"}
          </a>
        </nav>
      </header>

      <article className="egms-data-body">
        <p className="lead">{t.intro}</p>

        <h2>{t.sources}</h2>
        <section id="egms" className="egms-source-card">
          <h3>
            <span className="egms-swatch egms-swatch-egms" aria-hidden="true" /> {t.egmsName}
          </h3>
          <p>{t.egmsWhat}</p>
          <p>{t.egmsTrust}</p>
          <p>
            {t.licence}: Copernicus data policy, free and open · Contains modified Copernicus Land Monitoring Service
            information (EGMS), © European Union
          </p>
          <p className="mb-1">{t.egmsCode}</p>
          <pre>
            <code>{EGMS_CODE}</code>
          </pre>
        </section>

        {others.map((s, i) => (
          <section id={slug(s.name)} key={s.name} className="egms-source-card">
            <h3>
              <span className="egms-swatch" style={{ background: SOURCE_COLOURS[i % SOURCE_COLOURS.length] }} aria-hidden="true" />{" "}
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.name}
                </a>
              ) : (
                s.name
              )}{" "}
              <small className="text-secondary">· {t.records(s.records)}</small>
            </h3>
            <dl className="egms-facts">
              <dt>{t.licence}</dt>
              <dd>
                {s.licence}
                {s.attribution ? ` · ${s.attribution}` : ""}
              </dd>
              <dt>{t.writer}</dt>
              <dd>
                {s.made_by.map((m, j) => (
                  <span key={m}>
                    {j > 0 && ", "}
                    {LIBRARIES[m] ? (
                      <a href={LIBRARIES[m]} target="_blank" rel="noreferrer">
                        {m}
                      </a>
                    ) : (
                      m
                    )}
                  </span>
                ))}
              </dd>
              <dt>{t.what}</dt>
              <dd>{s.properties.join("; ")}</dd>
              <dt>{t.method}</dt>
              <dd>{s.methods.length ? s.methods.join("; ") : t.noMethod}</dd>
              <dt>{t.files}</dt>
              <dd>{s.files.join(", ")}</dd>
            </dl>
            {s.made_by.filter((m) => LIBRARIES[m]).map((m) => (
              <pre key={m}>
                <code>pip install {m}</code>
              </pre>
            ))}
          </section>
        ))}

        <h2 id="aggiungi">{t.add}</h2>
        <p>{t.addIntro}</p>
        <h3>{t.templates}</h3>
        <ul>
          <li>
            <a href="/templates/record.json" download>
              {t.json}
            </a>
          </li>
          <li>
            <a href="/templates/record.csv" download>
              {t.csv}
            </a>
          </li>
        </ul>
        <h3>{t.csvColumns}</h3>
        <div className="table-responsive">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>{t.column}</th>
                <th>{t.english}</th>
                <th>{t.meaning}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th colSpan={3}>{t.required}</th>
              </tr>
              {COLUMNS.map(([it, en, what]) => (
                <tr key={it}>
                  <td>
                    <code>{it}</code>
                  </td>
                  <td>
                    <code>{en}</code>
                  </td>
                  <td>{what[lang]}</td>
                </tr>
              ))}
              <tr>
                <th colSpan={3}>{t.optional}</th>
              </tr>
              {OPTIONAL.map(([it, en, what]) => (
                <tr key={it}>
                  <td>
                    <code>{it}</code>
                  </td>
                  <td>
                    <code>{en}</code>
                  </td>
                  <td>{what[lang]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small">{t.csvNote}</p>
        <h3>{t.check}</h3>
        <pre>
          <code>{'pip install "egms-client[records]"\negms records record.csv'}</code>
        </pre>
        <h3>{t.rules}</h3>
        <ul>
          {t.rulesList.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <h3>{t.format}</h3>
        <p>
          {t.formatText}{" "}
          <a href={SCHEMA} target="_blank" rel="noreferrer">
            {t.schema}
          </a>
          ,{" "}
          <a href={DESIGN} target="_blank" rel="noreferrer">
            {t.design}
          </a>
          .
        </p>

        {answer && answer.refused.length > 0 && (
          <section className="alert alert-warning small mt-4">
            <div className="fw-semibold">{t.refused}</div>
            <p className="mb-1">{t.refusedIntro}</p>
            <ul className="mb-0">
              {answer.refused.map((r) => (
                <li key={r.file}>
                  <code>{r.file}</code>: {r.problems.join("; ")}
                </li>
              ))}
            </ul>
          </section>
        )}
      </article>
    </div>
  );
}
