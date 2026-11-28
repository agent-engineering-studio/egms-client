# Records of open data

A record is one piece of open data in a shape every source can write and the
application can read: an `observation`, a `fact` or a `layer`. The schema is
[`opendata-record-v1.json`](https://github.com/agent-engineering-studio/egms-client/blob/main/src/egms_client/schema/opendata-record-v1.json)
(JSON Schema 2020-12). Why it exists, and what comes next, is in the
[design](../design/open-data-schema.md).

Version 2,
[`opendata-record-v2.json`](https://github.com/agent-engineering-studio/egms-client/blob/main/src/egms_client/schema/opendata-record-v2.json),
adds the kind `event`, a place that may be absent and how wide it is, how
wide a date is, and values that are yes/no or a category. A record says
which version it follows in its `schema` field; v1 is not changed. Both files
are served at their id: `https://agentengineering.it/egms-client/schema/opendata-record-v1.json`
and `.../opendata-record-v2.json`. Examples of v2, from ispra-idrogeo and
rainfall-thresholds, are in
[`examples/records-v2`](https://github.com/agent-engineering-studio/egms-client/tree/main/examples/records-v2).

Real examples of v1 are in
[`examples/records`](https://github.com/agent-engineering-studio/egms-client/tree/main/examples/records):
two EGMS points (one not measured), an EGMS map, an e-ITALICA threshold
(rainfall-thresholds), the radar reliability at a point (dpc-radar) and a
simulated rain gauge.

The answers of `egms_client.facts` become records with
`egms_client.facts.to_records`:

```python
from egms_client.facts import to_records, velocity

records = to_records(velocity(tiffs, 14.1205, 40.8225, release="2020-2025"))
```

A CSV with the columns of the template (`tempo, lon, lat, grandezza,
valore, unità, fonte, licenza`, or the same in English) reads as
observations; an empty `valore` is not measured.

Check a file from the command line:

```bash
pip install "egms-client[records]"
egms records examples/records/*
```

::: egms_client.records
