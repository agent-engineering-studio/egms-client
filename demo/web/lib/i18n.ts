// The words of the page, in Italian and in English. The numbers come from the API
// (egms_client.facts); the sentences that hold them come from egms_client.check.words,
// in the language asked. Here are only the words around them.

import type { Lang } from "./start";
import type { Reliability } from "./types";

const it = {
  locale: "it-IT",
  title: "Il suolo si muove?",
  tagline: "Il movimento del suolo misurato dai satelliti (EGMS, Copernicus)",
  language: "Lingua",
  mapLabel: "Mappa della velocità verticale del suolo",
  hint: "Clicca un punto della mappa: la velocità del suolo lì, e quanto fidarsi.",
  zoomIn: "Avvicinati per vedere la mappa della velocità (al massimo mezzo grado di lato).",
  loading: "Lettura dei dati…",
  vertical: "Verticale",
  east: "Est-ovest",
  noEast: "Nessun dato est-ovest caricato qui.",
  trust: "Quanto fidarsi",
  reliable: "Affidabile",
  notReliable: "Poco affidabile",
  notMeasured: "Non misurato",
  notMeasuredText: "Qui il satellite non ha misure: non misurato non vuol dire fermo.",
  coverage: (pct: number, m: number) => `Ha un valore il ${pct} % delle celle entro ${m} m.`,
  fewTargets: "Pochi bersagli stabili intorno (vegetazione, campi, neve?).",
  loose: (rmse: number) => `La serie si adatta poco al modello (scarto ${rmse.toLocaleString("it-IT")} mm).`,
  window: (first: string, last: string) => `Misurato dal ${first} al ${last}: i dati si fermano lì.`,
  windowYears: (release: string) => `Release ${release}: le date esatte non sono note.`,
  moving: "Celle che si muovono più dei dintorni",
  showMoving: "Mostra le celle che si muovono",
  hideMoving: "Nascondi",
  legend: "Velocità verticale (mm/anno)",
  legendDown: "scende",
  legendUp: "sale",
  legendNone: "nessuna misura",
  notAlert:
    "Una velocità del suolo è una misura, non un'allerta. Per i rischi la parola ufficiale è della Protezione Civile.",
  demo: "Modalità dimostrativa: solo alcuni luoghi (Pozzuoli, Bologna, Murge, Foresta Umbra, Ancona).",
  outside: "Qui la pagina non ha dati caricati. Non vuol dire «non misurato».",
  failed: "La richiesta non è riuscita",
  credit:
    "Dati: European Ground Motion Service (EGMS), Copernicus Land Monitoring Service, © Unione europea. Software: egms-client.",
  source: "Codice e documentazione",
};

const en: typeof it = {
  locale: "en-GB",
  title: "Is the ground moving?",
  tagline: "Ground motion measured by satellites (EGMS, Copernicus)",
  language: "Language",
  mapLabel: "Map of the vertical velocity of the ground",
  hint: "Click a point of the map: the velocity of the ground there, and how far to trust it.",
  zoomIn: "Zoom in to see the velocity map (at most half a degree across).",
  loading: "Reading the data…",
  vertical: "Vertical",
  east: "East-west",
  noEast: "No east-west data loaded here.",
  trust: "How far to trust it",
  reliable: "Reliable",
  notReliable: "Not very reliable",
  notMeasured: "Not measured",
  notMeasuredText: "The satellite has no measurement here: not measured is not still.",
  coverage: (pct: number, m: number) => `${pct}% of the cells within ${m} m have a value.`,
  fewTargets: "Few stable targets around (vegetation, fields, snow?).",
  loose: (rmse: number) => `The series fits the model loosely (rmse ${rmse} mm).`,
  window: (first: string, last: string) => `Measured from ${first} to ${last}: the data stop there.`,
  windowYears: (release: string) => `Release ${release}: the exact dates are not known.`,
  moving: "Cells that move more than their surroundings",
  showMoving: "Show the cells that move",
  hideMoving: "Hide",
  legend: "Vertical velocity (mm/year)",
  legendDown: "down",
  legendUp: "up",
  legendNone: "no measurement",
  notAlert:
    "A ground velocity is a measurement, not an alert. For hazards, the official word is the Civil Protection's.",
  demo: "Demo mode: only a few places (Pozzuoli, Bologna, the Murge, the Foresta Umbra, Ancona).",
  outside: "The page has no data loaded here. That is not «not measured».",
  failed: "The request failed",
  credit:
    "Data: European Ground Motion Service (EGMS), Copernicus Land Monitoring Service, © European Union. Software: egms-client.",
  source: "Code and documentation",
};

export type Text = typeof it;
export const TEXT: Record<Lang, Text> = { it, en };

/** The reasons to doubt a number, in the language of the page, from the facts' own numbers. */
export function reasons(r: Reliability, measured: boolean, t: Text): string[] {
  if (!measured) return [t.notMeasuredText];
  // The coverage itself is in the sentence of the template: here only what it means.
  const out: string[] = [];
  if (r.coverage < 0.5) out.push(t.fewTargets);
  if (r.fit !== null && r.fit < 1 && r.rmse_mm !== null) out.push(t.loose(r.rmse_mm));
  return out;
}
