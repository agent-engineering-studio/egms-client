// The words of the page, in Italian and in English. The numbers come from the API
// (egms_client.facts); the sentences that hold them come from egms_client.check.words,
// in the language asked. Here are only the words around them.

import type { Lang } from "./start";
import type { Reliability } from "./types";

const it = {
  locale: "it-IT",
  title: "Il territorio nei dati aperti",
  tagline: "Fonti aperte una accanto all'altra: da dove vengono, come si usano, quanto fidarsi",
  language: "Lingua",
  mapLabel: "Mappa della velocità verticale del suolo",
  hint: "Clicca un punto della mappa: ogni fonte dice che cosa sa di lì, da dove viene il dato e quanto fidarsi.",
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
    "Dati: European Ground Motion Service (EGMS), Copernicus Land Monitoring Service, © Unione europea; le altre fonti come indicato su ogni scheda. Software: egms-client.",
  source: "Codice e documentazione",
  // Open data side by side: the records of any source.
  tabPoint: "Punto",
  tabSources: "Fonti",
  tabAdd: "Aggiungi una fonte",
  egmsTitle: "Il suolo si muove? (EGMS, Copernicus)",
  nearTitle: (km: number) => `Le altre fonti, entro ${km} km`,
  noneNear: "Nessun'altra fonte ha dati entro 2 km da qui. Puoi aggiungerne una: «Aggiungi una fonte».",
  howMade: "Come è fatto",
  fromFile: (file: string) => `Letto dal file ${file}.`,
  madeBy: "Scritto da",
  checkIt: "Controllare il file:",
  theRecord: "Il record",
  install: "La libreria che l'ha scritto:",
  egmsCode: "Gli stessi numeri, in Python:",
  sourceLabel: "Fonte",
  licenceLabel: "Licenza",
  whenLabel: "Quando",
  trustLabel: "Quanto fidarsi",
  noDates: "la fonte non dà date",
  trustUnknown: "nessuno lo dice",
  score: (s: string) => `${s} su 1`,
  reliableShort: "affidabile",
  notReliableShort: "poco affidabile",
  methodLabel: "Come è stimato",
  series: (n: number) => `${n} misure; le ultime:`,
  gap: "nessuna misura",
  flags: { ok: "ok", gap: "buco", flatline: "valore piatto", spike: "picco", range: "fuori scala", unit: "unità" } as Record<string, string>,
  notesLang: "Le note sono quelle della fonte, nella sua lingua.",
  away: (m: number) => (m < 1 ? "qui" : `a ${m.toLocaleString("it-IT")} m`),
  sourcesIntro:
    "Le fonti che questa pagina legge. Ognuna resta com'è: la pagina le mette una accanto all'altra, non le mescola in un punteggio.",
  egmsLive: (mode: string): string =>
    mode === "demo"
      ? "EGMS, Copernicus: letto dai ritagli del benchmark (modalità dimostrativa)."
      : "EGMS, Copernicus: letto dall'archivio, con la chiave CLMS.",
  recordsOf: (n: number) => `${n} record`,
  filesLabel: "File",
  whatLabel: "Che cosa",
  refusedTitle: "File rifiutati",
  refusedIntro: "Un file con anche un solo record non valido è rifiutato per intero. Ecco perché:",
  noSources: "Nessun file di record nelle cartelle.",
  addIntro:
    "Qualsiasi fonte può comparire qui: un sensore, un file del Comune, una libreria. Basta scrivere i dati come record, un formato JSON aperto, con fonte, licenza, tempo, luogo e quanto fidarsi.",
  addStep1: "1. Scrivi un record. Per esempio, la pioggia di un pluviometro:",
  addStep2: "2. Controllalo:",
  addStep3:
    "3. Mettilo nella cartella records/, accanto a compose.yaml (o in quella di EGMS_RECORDS_DIR). La pagina lo legge alla richiesta successiva; se non è valido, lo dice in «Fonti».",
  addRules: "Le regole:",
  rules: [
    "dove non c'è misura il valore è null, mai 0;",
    "un valore con segno dice che cosa vuol dire il segno (meaning);",
    "ogni record dice fonte, licenza, tempo e luogo, e quanto fidarsi (o null, se nessuno lo dice);",
    "un record è una misura, non un'allerta: niente campi alert o rischio.",
  ],
  addMore: "Lo schema e il perché",
};

const en: typeof it = {
  locale: "en-GB",
  title: "Your area in open data",
  tagline: "Open sources side by side: where they come from, how to use them, how far to trust them",
  language: "Language",
  mapLabel: "Map of the vertical velocity of the ground",
  hint: "Click a point of the map: each source says what it knows of the place, where the data come from and how far to trust it.",
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
    "Data: European Ground Motion Service (EGMS), Copernicus Land Monitoring Service, © European Union; the other sources as stated on each card. Software: egms-client.",
  source: "Code and documentation",
  tabPoint: "Point",
  tabSources: "Sources",
  tabAdd: "Add a source",
  egmsTitle: "Is the ground moving? (EGMS, Copernicus)",
  nearTitle: (km: number) => `The other sources, within ${km} km`,
  noneNear: "No other source has data within 2 km of here. You can add one: «Add a source».",
  howMade: "How it is made",
  fromFile: (file: string) => `Read from the file ${file}.`,
  madeBy: "Written by",
  checkIt: "Check the file:",
  theRecord: "The record",
  install: "The library that wrote it:",
  egmsCode: "The same numbers, in Python:",
  sourceLabel: "Source",
  licenceLabel: "Licence",
  whenLabel: "When",
  trustLabel: "How far to trust it",
  noDates: "the source gives no dates",
  trustUnknown: "nobody says",
  score: (s: string) => `${s} out of 1`,
  reliableShort: "reliable",
  notReliableShort: "not very reliable",
  methodLabel: "How it is estimated",
  series: (n: number) => `${n} readings; the last ones:`,
  gap: "no reading",
  flags: { ok: "ok", gap: "gap", flatline: "flat line", spike: "spike", range: "out of range", unit: "unit" } as Record<string, string>,
  notesLang: "The notes are the source's, in its language.",
  away: (m: number) => (m < 1 ? "here" : `${m.toLocaleString("en-GB")} m away`),
  sourcesIntro:
    "The sources this page reads. Each stays as it is: the page puts them side by side, it does not blend them into a score.",
  egmsLive: (mode: string): string =>
    mode === "demo"
      ? "EGMS, Copernicus: read from the benchmark crops (demo mode)."
      : "EGMS, Copernicus: read from the archive, with the CLMS key.",
  recordsOf: (n: number) => `${n} record${n === 1 ? "" : "s"}`,
  filesLabel: "Files",
  whatLabel: "What",
  refusedTitle: "Files refused",
  refusedIntro: "A file with even one invalid record is refused whole. Here is why:",
  noSources: "No record files in the folders.",
  addIntro:
    "Any source can show here: a sensor, a file of the Comune, a library. Write the data as records, an open JSON format with source, licence, time, place and how far to trust it.",
  addStep1: "1. Write a record. For example, the rain of a rain gauge:",
  addStep2: "2. Check it:",
  addStep3:
    "3. Put it in the folder records/, next to compose.yaml (or the one of EGMS_RECORDS_DIR). The page reads it at the next request; if it is not valid, «Sources» says why.",
  addRules: "The rules:",
  rules: [
    "where there is no measurement the value is null, never 0;",
    "a signed value says what its sign means (meaning);",
    "every record says its source, licence, time and place, and how far to trust it (or null, if nobody says);",
    "a record is a measurement, not an alert: no alert or risk fields.",
  ],
  addMore: "The schema, and why",
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
