# Design: one input schema for open data

Status: **agreed** on 24 November 2026. Built step by step, below.

## The problem

The page in `demo/web` shows one dataset, EGMS. A visitor learns how much the
ground moves at Pozzuoli. They do not learn how to do the same with other open
data, or with their own sensor.

The goal is a page that shows anyone how to reuse open data in a practical
way. For each piece of data it shows three things:

1. **where it comes from**: the source, the licence, the dates, how far to trust it;
2. **how to get it**: a few lines of Python, or one HTTP call;
3. **how it sits next to the others**: rain, landslides, ground motion, a local sensor.

## What exists today

| Library | Answers as data | Common keys | MCP |
|---|---|---|---|
| dpc-radar | `facts.py` (rain grid, trust, rarity, alert zones) | `source`, `unit`, `time`, `score`, `reliable` | yes |
| rainfall-thresholds | `facts.py` (threshold, events) | `source`, `unit` in key names (`_mm`, `_h`) | yes |
| ispra-idrogeo | `grounding.py`, `reliability.py` | `source`, `reliability` | yes |
| egms-client | `facts.py` (velocity, area, moving points) | `unit`, `measured`, `reliability`, `window`, `files`, `licence`, `notes` | yes |
| firms-client | `summary.py` | few | yes |
| effis-client | none yet | none | no |

The libraries already say most of the same things, with different names.
`unit` is sometimes a key and sometimes a suffix (`max_mm`). The time is
sometimes a stamp (`time`) and sometimes a window (`window.first`,
`window.last`). "Not measured" is `measured: false` in one library and a
`None` value in another.

Limen already has a standard input for sensors
(`limen/integrations/iot/schemas.py`). `Observation` follows OGC
SensorThings: `thing_id`, `observed_property`, `phenomenon_time`,
`result_value`, `result_unit` (UCUM). Devices send SenML over MQTT or signed
HTTP, and each reading goes through quality control: range, spike, flat line,
gap.

## The idea: a contract by schema, not by import

The libraries do not import each other, and egms-client must stay so (a test
checks it). So the shared part is **a JSON Schema file and its examples**, not
a Python package. Each source writes JSON that is valid against it. The app
reads only that JSON.

Any source can then feed the app:

- a library of the series, through a small `to_records()` function;
- an IoT sensor, through SenML over HTTP;
- a CSV or GeoJSON from a municipality or an ARPA;
- an open API (open-meteo, ARPA), through a small adapter.

## The schema: three record types

All three share an **envelope**, the part that makes a number honest:

| Field | Meaning | Required |
|---|---|---|
| `schema` | `"opendata-record/v1"` | yes |
| `kind` | `observation`, `fact` or `layer` | yes |
| `source` | `{name, url, licence, attribution}` | yes |
| `made_by` | the library or device that wrote it, with its version | yes |
| `time` | `{instant}`, or `{first, last, exact}` for a window, or `null` when the source gives no dates | yes, may be `null` |
| `where` | GeoJSON geometry, WGS84 (EPSG:4326) | yes |
| `reliability` | `{score, reliable, method, reasons}`, or `null` if unknown | yes, may be `null` |
| `notes` | short sentences a reader must see | no |

### 1. `observation`: one value at one place and time

Aligned with SensorThings and with Limen's `Observation`, so a Limen v2
message converts field by field.

| Field | Meaning |
|---|---|
| `property` | what is measured: `rainfall`, `displacement`, `velocity`, `soil_moisture`, ... (Limen's list) |
| `value` | the number, or `null` when **not measured** (never 0) |
| `unit` | UCUM code: `mm`, `mm/a`, `mm/h`, `kPa`, `Cel` |
| `meaning` | what the sign says: `"positive = up"` |
| `quality` | the QC flags: `range`, `spike`, `flatline`, `gap` |

```json
{
  "schema": "opendata-record/v1",
  "kind": "observation",
  "source": {"name": "EGMS L3 2020-2025", "url": "https://egms.land.copernicus.eu/",
             "licence": "Copernicus data policy",
             "attribution": "Copernicus Land Monitoring Service, © European Union"},
  "made_by": {"name": "egms-client", "version": "0.8.0"},
  "time": {"first": "2020-12-09", "last": "2025-11-19", "exact": true},
  "where": {"type": "Point", "coordinates": [14.1205, 40.8225]},
  "property": "velocity",
  "value": 145.2,
  "unit": "mm/a",
  "meaning": "vertical; positive = up",
  "reliability": {"score": 1.0, "reliable": true,
                  "method": "share of measured cells within 500 m, and fit",
                  "reasons": []},
  "notes": ["a velocity is a measurement, not an alert"]
}
```

The same shape carries a rain gauge reading, the radar rain at a point
(dpc-radar), or a crackmeter on a wall.

### 2. `fact`: an answer already computed

What the libraries return today, in one shape: a `question`, a set of named
`values` (each with its unit), and the envelope. This one is real: the
e-ITALICA threshold for 24 hours in southern Italy, from
`rainfall_thresholds.facts.threshold_facts("southern", 24)`.

```json
{
  "schema": "opendata-record/v1",
  "kind": "fact",
  "question": "How much rain in 24 hours is like the rain that triggered landslides in southern Italy?",
  "values": {"cumulated": {"value": 27.1, "unit": "mm"},
             "intensity": {"value": 1.13, "unit": "mm/h"},
             "duration": {"value": 24, "unit": "h"}},
  "source": {"name": "e-ITALICA v4, threshold ITALICA_T5 (southern)",
             "url": "https://doi.org/10.5281/zenodo.14204473",
             "licence": "CC BY 4.0", "attribution": "Brunetti et al. 2024, e-ITALICA v4"},
  "made_by": {"name": "rainfall-thresholds", "version": "0.3.0"},
  "time": null,
  "where": {"type": "Point", "coordinates": [16.6044, 40.6664]},
  "reliability": {"method": "5th percentile of 1,425 rainfall events that triggered landslides in southern Italy",
                  "reasons": []},
  "notes": ["A threshold exceeded is not an alert. ..."]
}
```

`time` is `null` here: the library does not give the dates of the catalogue,
and the record does not invent them.

### 3. `layer`: a map

A Cloud-Optimized GeoTIFF or a GeoJSON file, with the envelope, `property`,
`unit`, `meaning`, and a `no_data` rule ("grey = not measured").

## The rules every record keeps

These are the rules egms-client already follows. The schema makes them checkable.

- **Not measured is `null`, never 0 or NaN.** The validator refuses a value
  that is not `null` when `reliability.reasons` contains `not_measured`.
- **Every number has a unit and, if signed, a meaning.**
- **Every record says its time, or says it has none.** A 2020-2025 velocity
  is not today's ground. `null` means the source gives no dates; nobody
  guesses them.
- **Reliability can be unknown, but not missing.** `null` means "nobody says";
  the app shows it as such.
- **No record is an alert.** There is no `alert` or `risk` field, and no
  property or value may be named so (in English or Italian). Official
  warnings stay with the Civil Protection; risk scores stay with Limen.

## How data comes in

| Way | For | Notes |
|---|---|---|
| file in a folder | CSV, GeoJSON, Parquet, JSON | a CSV needs a small mapping file: which column is time, value, unit |
| HTTP `POST /records` | IoT gateways | SenML (RFC 8428), as in Limen v2. Signature later |
| adapter | open APIs, the libraries | a script that runs on a schedule and writes records |

## How a library adopts it

1. A function `to_records(facts) -> list[dict]` next to its `facts.py`.
2. A copy of the schema file in its tests, and one test that validates its
   output against it. No import of any other library.
3. Its MCP tools may return records too, so an assistant sees the same shape.

## The app

One place, many sources. You choose a municipality or click a point. Cards appear:

- **rain now** (dpc-radar);
- **how much rain is enough** (rainfall-thresholds);
- **where it has already slid** (ispra-idrogeo);
- **where the ground moves** (egms-client);
- **your sensor** (IoT, or a CSV you drop in).

Every card has the same footer: source, dates, how far to trust it, licence.
And a tab, **"how it is made"**, with the code or the HTTP call that produced it.

A guide page shows how to add a source: write one JSON record, drop it in,
see it on the map.

**The line with Limen.** The app shows data side by side and explains it. It
does not combine the data into a score, and it does not raise alerts. That is
Limen's job.

## Decisions (24 November 2026)

1. **It lives here, in egms-client.** egms-client is a standalone
   application with a library inside. Limen keeps using the library, and the
   application does not compete with Limen: it shows and explains, Limen
   scores. The application reads other sources only as records (files, HTTP),
   never by importing their libraries.
2. **Show and explain only.** No combined score, no alerts.
3. **The first sensor is a rain gauge**, over HTTP SenML, unsigned at first.
4. **JSON Schema 2020-12**, with checks in Python for the rules a schema
   cannot say.

## Steps

1. ✅ The schema file (`src/egms_client/schema/opendata-record-v1.json`),
   the validator (`egms_client.records`, `egms records`), and real examples
   in `examples/records`: egms-client, rainfall-thresholds, dpc-radar, and a
   simulated rain gauge. ispra-idrogeo needs the network: it comes in step 5.
2. ✅ `egms_client.facts.to_records()`: a velocity is one observation; an area
   and the moving cells are one fact, then one observation per cell listed.
   `scripts/example_records.py` writes the egms examples, and a test checks
   that `to_records` still gives them.
3. ✅ The app reads records from folders (`EGMS_UI_RECORDS`; in Docker the
   examples and `records/`, read-only). `demo/api.py` adds `/api/sources`
   and `/api/records`, and refuses a file with an invalid record, saying
   why. The page has three tabs: the point (EGMS, then the other sources
   within 2 km, each with «how it is made»), the sources, and how to add one.
4. HTTP SenML input and a simulated rain gauge.
5. `to_records()` in the other libraries, one PR each.
