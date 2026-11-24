"use client";

import type { Text } from "@/lib/i18n";

/** A record any sensor can write: the shape of examples/records/rain-gauge-simulated.jsonl. */
const EXAMPLE = {
  schema: "opendata-record/v1",
  kind: "observation",
  source: { name: "Pluviometro del Comune", licence: "CC BY 4.0" },
  made_by: { name: "pluvio-01" },
  thing: "pluvio-01",
  time: { instant: "2026-10-15T12:00:00Z" },
  where: { type: "Point", coordinates: [14.1262, 40.8262] },
  property: "rainfall",
  value: 0.4,
  unit: "mm",
  reliability: null,
  notes: ["Pioggia dei 10 minuti prima dell'ora indicata."],
};

/** How to add a source: write a record, check it, drop it in the folder. */
export default function AddSource({ t }: { t: Text }) {
  return (
    <div className="small">
      <p>{t.addIntro}</p>
      <p className="mb-1 fw-semibold">{t.addStep1}</p>
      <pre className="egms-json">
        <code>{JSON.stringify(EXAMPLE, null, 2)}</code>
      </pre>
      <p className="mb-1 fw-semibold">{t.addStep2}</p>
      <pre>
        <code>{'pip install "egms-client[records]"\negms records pluvio-01.json'}</code>
      </pre>
      <p className="fw-semibold">{t.addStep3}</p>
      <p className="mb-1">{t.addRules}</p>
      <ul className="ps-3">
        {t.rules.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <a href="https://agentengineering.it/egms-client/design/open-data-schema/" target="_blank" rel="noreferrer">
        {t.addMore}
      </a>
    </div>
  );
}
