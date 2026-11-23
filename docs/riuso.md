# Riuso nella Pubblica Amministrazione

egms-client legge i dati aperti dell'European Ground Motion Service (EGMS),
il servizio Copernicus che misura dallo spazio quanto si muove il terreno in
tutta Europa, e li rende usabili da chiunque. Questa pagina è per un ente che
vuole usarlo: che cosa trova pronto, che cosa resta a lui, e come il progetto
entra nel Catalogo del software di Developers Italia.

!!! note "Prima versione"
    Oggi egms-client è una libreria Python con riga di comando e un server
    MCP. La pagina per il sito del Comune, da installare con Docker, è in
    lavorazione ([roadmap, fase 6](https://github.com/agent-engineering-studio/egms-client/issues/22)):
    questa pagina crescerà con lei.

## Che cosa trova pronto

- Le mappe della **velocità verticale** ed **est-ovest** del terreno, in
  millimetri all'anno, una cella ogni 100 metri, su qualsiasi area.
- I **punti di misura** con la loro serie temporale, come tabelle e
  GeoParquet, da aprire in QGIS.
- Le serie che **accelerano** o **cambiano velocità**, e gli errori di
  elaborazione da non scambiare per movimento.
- Un **server MCP** perché un assistente AI risponda con i numeri dei dati,
  citando release e file.

Serve una chiave di servizio gratuita del Copernicus Land Monitoring Service
(CLMS): come ottenerla è nella [pagina iniziale](index.md#2-get-a-service-key-once-2-minutes).

## Che cosa resta all'ente

Il progetto dà il software. Queste cose sono di chi lo usa.

- **Non è un'allerta.** Una velocità del terreno è una misura, non un
  giudizio sulla sicurezza di un edificio, di un versante o di un'area. Per
  il pericolo valgono le comunicazioni ufficiali della Protezione Civile.
- **Che cosa i dati non vedono.** Dove ci sono bosco, campi arati o neve il
  satellite trova pochi punti o nessuno: lì la risposta è «non misurato», non
  zero. I movimenti molto rapidi si perdono, e quello nord-sud non si vede.
  I numeri descrivono la finestra della release (oggi 2020-2025), non il
  terreno di oggi.
- **Attribuzione dei dati.** I dati EGMS sono © Unione europea, Copernicus
  Land Monitoring Service, liberi e aperti secondo la
  [politica dei dati Copernicus](https://land.copernicus.eu/en/data-policy).
  Chi pubblica qualcosa ricavato da questi dati deve citarne la fonte, per
  esempio: «Contiene informazioni modificate del Copernicus Land Monitoring
  Service (EGMS), © Unione europea».
- **La chiave CLMS.** È personale e non scade: va tenuta come una password,
  fuori dal codice e dai repository, in una variabile d'ambiente o in un
  segreto di Docker.
- **Dati personali.** Il software non ne raccoglie: niente account, niente
  cookie. Su disco restano solo i file scaricati dall'archivio.

## Intelligenza artificiale

I numeri della libreria sono calcolati dai dati con codice aperto e
verificato. Il server MCP dà a un assistente AI questi numeri, e le sue
istruzioni gli chiedono di citarli come sono, con release e file, e di non
trasformare mai una velocità in un giudizio di sicurezza. La classe di
rischio, la valutazione d'impatto e l'informativa agli utenti riguardano
l'uso che l'ente ne fa, e sono sue.

## Il Catalogo di Developers Italia

**Oggi: software open source di terze parti.** Il codice non è di una PA.
Entra nel Catalogo con il file [`publiccode.yml`](https://github.com/agent-engineering-studio/egms-client/blob/main/publiccode.yml)
nel repository, con `codiceIPA` vuoto, e una segnalazione sul repository
[`italia/catalogo-software`](https://github.com/italia/catalogo-software).

**Domani: software a riuso.** Se un ente lo adotta e ne diventa titolare (art.
69 del CAD), lo dichiara con l'[onboarding](https://onboarding.developers.italia.it/)
di Developers Italia; `codiceIPA` prende il codice dell'ente, e gli enti che
lo usano vanno in `usedBy`.

- [x] Repository pubblico, licenza Apache-2.0
- [x] README, documentazione, `CONTRIBUTING.md`, `CHANGELOG.md`
- [x] `publiccode.yml` valido per il validatore ufficiale, controllato a ogni modifica dalla CI
- [ ] Installazione con Docker e pagina per il Comune con Bootstrap Italia
- [ ] Segnalazione su `italia/catalogo-software`

## Fonti

- [Developers Italia: pubblicare software per la PA](https://developers.italia.it/it/guide/pubblicare-software-per-la-pa)
- [Lo standard publiccode.yml](https://yml.publiccode.tools/)
- [EGMS](https://egms.land.copernicus.eu/) e la [politica dei dati Copernicus](https://land.copernicus.eu/en/data-policy)
