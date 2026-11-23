# Design: one input schema for open data

Status: **draft for review**. Nothing here is built yet.

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
| `time` | an instant, or `{first, last, exact}` for a window | yes |
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
  "reliability": {"score": 0.92, "reliable": true,
                  "method": "share of measured cells within 500 m, and fit",
                  "reasons": []},
  "notes": ["a velocity is a measurement, not an alert"]
}
```

The same shape carries a rain gauge reading, the radar rain at a point
(dpc-radar), or a crackmeter on a wall.

### 2. `fact`: an answer already computed

What the libraries return today, in one shape: a `question`, a set of named
`values` (each with its unit), and the envelope. For example the ITALICA
threshold for 24 hours in the south (rainfall-thresholds), or the landslides
already mapped in a municipality (ispra-idrogeo).

```json
{
  "schema": "opendata-record/v1",
  "kind": "fact",
  "question": "how much rain in 24 h is enough to trigger landslides here",
  "values": {"cumulated": {"value": 61.4, "unit": "mm"},
             "duration": {"value": 24, "unit": "h"}},
  "source": {"name": "ITALICA, ITALICA_T5 southern", "...": "..."},
  "made_by": {"name": "rainfall-thresholds", "version": "0.3.0"},
  "time": {"first": "1996-01-01", "last": "2021-12-31", "exact": false},
  "where": {"type": "Polygon", "coordinates": ["..."]},
  "reliability": null,
  "notes": ["5th percentile: 5% of the landslides came with less rain"]
}
```

(The numbers above are placeholders for the shape, not data.)

### 3. `layer`: a map

A Cloud-Optimized GeoTIFF or a GeoJSON file, with the envelope, `property`,
`unit`, `meaning`, and a `no_data` rule ("grey = not measured").

## The rules every record keeps

These are the rules egms-client already follows. The schema makes them checkable.

- **Not measured is `null`, never 0.** The validator refuses a record with
  `value: 0` and `reliability.reasons` containing `no data`.
- **Every number has a unit and, if signed, a meaning.**
- **Every record has a time window.** A 2020-2025 velocity is not today's ground.
- **Reliability can be unknown, but not missing.** `null` means "nobody says";
  the app shows it as such.
- **No record is an alert.** There is no `alert` or `risk` field. Official
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

## Open decisions

1. **Where it lives.** A new repository for the schema, its validator and the
   app (proposal), or the app here in egms-client. The current page would stay
   here as a one-source example.
2. **The line with Limen.** Show and explain only (proposal), or also a simple
   combined view.
3. **The first sensor and protocol.** A rain gauge over HTTP SenML, unsigned
   at first (proposal), or an inclinometer or piezometer.
4. **Schema language.** JSON Schema 2020-12 (proposal), with Pydantic models
   generated from it for the Python side.

## Steps, once agreed

1. The schema file, a validator, and examples from four libraries.
2. `to_records()` in egms-client, with the conformance test (one PR).
3. The app with file input and two sources.
4. HTTP SenML input and a simulated rain gauge.
5. `to_records()` in the other libraries, one PR each.
