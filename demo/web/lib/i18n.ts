// The words of the page, in Italian and in English. The numbers come from the API: the
// EGMS sentences from egms_client.check.words, the others from the records. Here are only
// the words around them.

import type { Lang } from "./start";

const it = {
  locale: "it-IT",
  title: "Il territorio nei dati aperti",
  tagline: "Che cosa dicono i dati aperti del territorio, quanto fidarsi, e dove mancano",
  loadingTitle: (place: string) => `${place}: preparo i dati`,
  loadingWhy:
    "Prima di aprire la mappa la pagina scarica dall'archivio Copernicus i dati EGMS dell'area (circa 60 MB per tessera). Succede solo al primo avvio: poi restano sul server e la pagina risponde subito.",
  loadingArea: "La mappa",
  loadingMb: (got: string, all: string) => `${got} di ${all} MB`,
  loadingStates: {
    waiting: "in attesa",
    checking: "controllo",
    downloading: "scarico",
    ready: "pronta",
    absent: "non c'è nell'archivio",
    failed: "non riuscita",
  },
  loadingComponent: { U: "verticale", E: "est-ovest" },
  loadingRetry: (s: number, error: string) =>
    `L'archivio Copernicus non risponde (${error}). Riprovo tra ${s} secondi.`,
  loadingNoApi: "Il server dei dati non risponde ancora: riprovo.",
  loadingSlow:
    "L'archivio Copernicus non risponde da più di un minuto e mezzo. La pagina continua a provare da sola; intanto puoi entrare con i dati già scaricati.",
  loadingEnter: "Entra con i dati già scaricati",
  purposeTitle: "A cosa serve questa mappa",
  purpose:
    "Mette una accanto all'altra le fonti aperte su questo territorio: il movimento del suolo misurato dai satelliti (EGMS, Copernicus) e le altre fonti pubblicate. Per ogni punto dice che cosa sanno, e quanto fidarsi.",
  purposeGaps:
    "Mostra anche dove i dati mancano. In arancione i buchi di dati: chilometri quadrati dove il satellite misura meno di un quarto delle celle. Non sono zone di pericolo: sono i posti dove un'amministrazione può pubblicare nuovi dati aperti, come livellazioni, stazioni GNSS, rilievi o sensori.",
  gapSummary: (pct: number, gaps: number, blocks: number) =>
    `Nell'area della pagina ${gaps} chilometri quadrati su ${blocks} (${pct}%) sono buchi di dati.`,
  gapSummaryPartial: "Conto parziale: alcune tessere EGMS non sono ancora scaricate.",
  gapComune: (name: string, pct: number, gaps: number, blocks: number) =>
    `Nel Comune di ${name} ${gaps} chilometri quadrati su ${blocks} (${pct}%) sono buchi di dati.`,
  gapLandOnly: "Il mare non è contato: i confini dei Comuni sono quelli dell'ISTAT.",
  gapWithSea: "Attenzione: senza i confini ISTAT anche il mare risulta buco di dati.",
  loadingBoundaries: "Confini dei Comuni (ISTAT)",
  loadingBoundaryStates: {
    waiting: "in attesa",
    downloading: "scarico",
    ready: "pronti",
    none: "non disponibili",
    failed: "non riusciti",
  },
  gapHere: "Buco di dati",
  gapHereText: (pct: number) =>
    `In questo chilometro quadrato il satellite misura il ${pct}% delle celle. Qui un dato aperto in più (una livellazione, una stazione GNSS, un sensore, un rilievo del Comune) direbbe che cosa fa il suolo.`,
  gapCovered: (pct: number) => `In questo chilometro quadrato il satellite misura il ${pct}% delle celle.`,
  addData: "Come aggiungere una fonte",
  language: "Lingua",
  dataLink: "I dati e come riusarli",
  mapLabel: "Mappa del territorio con le fonti di dati aperti",
  hint: "Clicca un punto della mappa: ogni fonte dice che cosa sa di lì.",
  loading: "Lettura dei dati…",
  downloading:
    "Prima volta in questa zona: scarico i dati EGMS dall'archivio Copernicus (circa 60 MB). Può servire un minuto; le volte dopo è immediato.",
  mapLoading: "Carico la mappa del suolo…",
  mapDownloading: "Scarico la mappa del suolo dall'archivio (la prima volta, circa un minuto)…",
  mapFailed: "La mappa del suolo qui non è disponibile: riprovo tra due minuti.",
  mapPartial: (tiles: string[]) =>
    `Mappa parziale: a righe le zone ancora da scaricare (${tiles.join(", ")}). La pagina riprova da sola.`,
  here: "Qui",
  near: "Vicino",
  noneNear: "Nessun'altra fonte ha dati entro 2 km.",
  outside: "Qui la pagina non ha dati EGMS caricati (non vuol dire «non misurato»).",
  failed: "La richiesta non è riuscita",
  missingTiles: (tiles: string[]) =>
    `I dati EGMS di questa zona (${tiles.join(", ")}) non sono ancora stati scaricati dall'archivio Copernicus: la pagina continua a provare da sola. Riprova tra qualche minuto. Non vuol dire «non misurato».`,
  // The ground, from EGMS.
  groundU: "Suolo, movimento verticale",
  groundE: "Suolo, movimento est-ovest",
  up: (v: string) => `sale di ${v} mm/anno`,
  down: (v: string) => `scende di ${v} mm/anno`,
  east: (v: string) => `verso est, ${v} mm/anno`,
  west: (v: string) => `verso ovest, ${v} mm/anno`,
  zero: "0 mm/anno",
  between: (a: string, b: string) => `dal ${a} al ${b}`,
  around: (pct: number, metres: number, median: string | null, km: number) =>
    `la cella di questo punto non ha misure, ma entro ${metres} m è misurato il ${pct}% delle celle` +
    (median === null ? "" : `; mediana entro ${km} km: ${median} mm/anno`),
  releaseYears: (r: string) => `release ${r}`,
  demo: "Modalità dimostrativa: dati EGMS solo per alcuni luoghi.",
  // Trust.
  trust: { reliable: "affidabile", weak: "poco affidabile", unmeasured: "non misurato", unknown: "affidabilità non indicata" },
  trustHelp: "Quanto fidarsi lo dice la fonte; dove non lo dice, la pagina non lo inventa.",
  // Details of a row.
  details: "Dettagli",
  sourceLabel: "Fonte",
  whenLabel: "Quando",
  trustLabel: "Quanto fidarsi",
  licenceLabel: "Licenza",
  noDates: "la fonte non dà date",
  score: (s: string) => `${s} su 1`,
  lastReading: (when: string) => `ultima lettura ${when}`,
  at: (when: string) => `alle ${when}`,
  lastMissing: (when: string) => `ultima lettura (${when}): nessuna misura`,
  readings: (n: number) => `${n} letture`,
  noValue: "nessuna misura",
  away: (m: number) => (m < 1 ? "qui" : `a ${m.toLocaleString("it-IT")} m`),
  howMade: "Come è fatto →",
  notesLang: "Le note sono quelle della fonte, nella sua lingua.",
  // Layers.
  layers: "Livelli",
  layerGround: "Movimento del suolo (EGMS)",
  layerMoving: "Celle che si muovono",
  outsideArea: (km: number) =>
    `Fuori dall'area della pagina: mostra ${km.toLocaleString("it-IT")} km intorno al Comune, e lì fuori non legge dati.`,
  areaNote: (km: number) => `Area della pagina: ${km.toLocaleString("it-IT")} km intorno al Comune.`,
  legendDown: "scende",
  legendUp: "sale",
  legendNone: "nessuna misura",
  legendMissing: "non ancora scaricato",
  legendGap: "buco di dati",
  close: "Chiudi",
  openPanel: "Apri il pannello",
  closePanel: "Riduci il pannello",
  notAlert: "Questi dati sono misure, non allerte. Per i rischi la parola ufficiale è della Protezione Civile.",
  credit:
    "Dati: EGMS, Copernicus Land Monitoring Service, © Unione europea; confini dei Comuni: ISTAT, CC BY 4.0; le altre fonti come indicato per ciascuna.",
  source: "Codice",
};

const en: typeof it = {
  locale: "en-GB",
  title: "Your area in open data",
  tagline: "What the open data of the area say, how far to trust them, and where they are missing",
  loadingTitle: (place: string) => `${place}: getting the data ready`,
  loadingWhy:
    "Before the map opens, the page downloads the EGMS data of the area from the Copernicus archive (about 60 MB per tile). This happens only at the first start: then they stay on the server and the page answers at once.",
  loadingArea: "The map",
  loadingMb: (got: string, all: string) => `${got} of ${all} MB`,
  loadingStates: {
    waiting: "waiting",
    checking: "checking",
    downloading: "downloading",
    ready: "ready",
    absent: "not in the archive",
    failed: "failed",
  },
  loadingComponent: { U: "vertical", E: "east-west" },
  loadingRetry: (s: number, error: string) =>
    `The Copernicus archive does not answer (${error}). Trying again in ${s} seconds.`,
  loadingNoApi: "The data server does not answer yet: trying again.",
  loadingSlow:
    "The Copernicus archive has not answered for more than a minute and a half. The page keeps trying by itself; meanwhile you can enter with the data already downloaded.",
  loadingEnter: "Enter with the data already downloaded",
  purposeTitle: "What this map is for",
  purpose:
    "It puts the open sources on this area side by side: the ground motion measured by satellites (EGMS, Copernicus) and the other published sources. For each point it says what they know, and how far to trust them.",
  purposeGaps:
    "It also shows where data are missing. In amber, the data gaps: square kilometres where the satellite measures less than a quarter of the cells. They are not dangerous places: they are where an administration can publish new open data, such as levelling, GNSS stations, surveys or sensors.",
  gapSummary: (pct: number, gaps: number, blocks: number) =>
    `In the area of the page, ${gaps} square kilometres out of ${blocks} (${pct}%) are data gaps.`,
  gapSummaryPartial: "A partial count: some EGMS tiles are not downloaded yet.",
  gapComune: (name: string, pct: number, gaps: number, blocks: number) =>
    `In the Comune of ${name}, ${gaps} square kilometres out of ${blocks} (${pct}%) are data gaps.`,
  gapLandOnly: "The sea is not counted: the boundaries of the Comuni are ISTAT's.",
  gapWithSea: "Beware: without the ISTAT boundaries the sea counts as a data gap too.",
  loadingBoundaries: "Boundaries of the Comuni (ISTAT)",
  loadingBoundaryStates: {
    waiting: "waiting",
    downloading: "downloading",
    ready: "ready",
    none: "not available",
    failed: "failed",
  },
  gapHere: "Data gap",
  gapHereText: (pct: number) =>
    `In this square kilometre the satellite measures ${pct}% of the cells. Here one more open dataset (levelling, a GNSS station, a sensor, a survey of the Comune) would tell what the ground does.`,
  gapCovered: (pct: number) => `In this square kilometre the satellite measures ${pct}% of the cells.`,
  addData: "How to add a source",
  language: "Language",
  dataLink: "The data and how to reuse them",
  mapLabel: "Map of the area with the open data sources",
  hint: "Click a point of the map: each source says what it knows of the place.",
  loading: "Reading the data…",
  downloading:
    "First time in this area: downloading the EGMS data from the Copernicus archive (about 60 MB). It may take a minute; afterwards it is immediate.",
  mapLoading: "Loading the ground map…",
  mapDownloading: "Downloading the ground map from the archive (the first time, about a minute)…",
  mapFailed: "The ground map is not available here: trying again in two minutes.",
  mapPartial: (tiles: string[]) =>
    `Partial map: striped, the zones still to download (${tiles.join(", ")}). The page keeps trying.`,
  here: "Here",
  near: "Nearby",
  noneNear: "No other source has data within 2 km.",
  outside: "The page has no EGMS data loaded here (that is not «not measured»).",
  failed: "The request failed",
  missingTiles: (tiles: string[]) =>
    `The EGMS data of this area (${tiles.join(", ")}) are not downloaded from the Copernicus archive yet: the page keeps trying by itself. Try again in a few minutes. That is not «not measured».`,
  groundU: "Ground, vertical motion",
  groundE: "Ground, east-west motion",
  up: (v: string) => `rises by ${v} mm/year`,
  down: (v: string) => `sinks by ${v} mm/year`,
  east: (v: string) => `eastward, ${v} mm/year`,
  west: (v: string) => `westward, ${v} mm/year`,
  zero: "0 mm/year",
  between: (a: string, b: string) => `from ${a} to ${b}`,
  around: (pct: number, metres: number, median: string | null, km: number) =>
    `the cell of this point has no measure, but within ${metres} m ${pct}% of the cells are measured` +
    (median === null ? "" : `; median within ${km} km: ${median} mm/year`),
  releaseYears: (r: string) => `release ${r}`,
  demo: "Demo mode: EGMS data for a few places only.",
  trust: { reliable: "reliable", weak: "not very reliable", unmeasured: "not measured", unknown: "reliability not given" },
  trustHelp: "How far to trust a number is the source's to say; where it does not, the page does not make it up.",
  details: "Details",
  sourceLabel: "Source",
  whenLabel: "When",
  trustLabel: "How far to trust it",
  licenceLabel: "Licence",
  noDates: "the source gives no dates",
  score: (s: string) => `${s} out of 1`,
  lastReading: (when: string) => `last reading ${when}`,
  at: (when: string) => `at ${when}`,
  lastMissing: (when: string) => `last reading (${when}): no measurement`,
  readings: (n: number) => `${n} readings`,
  noValue: "no measurement",
  away: (m: number) => (m < 1 ? "here" : `${m.toLocaleString("en-GB")} m away`),
  howMade: "How it is made →",
  notesLang: "The notes are the source's, in its language.",
  layers: "Layers",
  layerGround: "Ground motion (EGMS)",
  layerMoving: "Cells that move",
  outsideArea: (km: number) =>
    `Outside the area of the page: it shows ${km.toLocaleString("en-GB")} km around the Comune, and reads no data beyond it.`,
  areaNote: (km: number) => `Area of the page: ${km.toLocaleString("en-GB")} km around the Comune.`,
  legendDown: "down",
  legendUp: "up",
  legendNone: "no measurement",
  legendMissing: "not downloaded yet",
  legendGap: "data gap",
  close: "Close",
  openPanel: "Open the panel",
  closePanel: "Shrink the panel",
  notAlert: "These data are measurements, not alerts. For hazards, the official word is the Civil Protection's.",
  credit:
    "Data: EGMS, Copernicus Land Monitoring Service, © European Union; boundaries of the Comuni: ISTAT, CC BY 4.0; the other sources as stated for each.",
  source: "Code",
};

export type Text = typeof it;
export const TEXT: Record<Lang, Text> = { it, en };
