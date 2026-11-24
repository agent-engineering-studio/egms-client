# Records of open data

A record is one piece of open data in a shape every source can write and the
application can read: an `observation`, a `fact` or a `layer`. The schema is
[`opendata-record-v1.json`](https://github.com/agent-engineering-studio/egms-client/blob/main/src/egms_client/schema/opendata-record-v1.json)
(JSON Schema 2020-12). Why it exists, and what comes next, is in the
[design](../design/open-data-schema.md).

Real examples are in
[`examples/records`](https://github.com/agent-engineering-studio/egms-client/tree/main/examples/records):
two EGMS points (one not measured), an EGMS map, an e-ITALICA threshold
(rainfall-thresholds), the radar reliability at a point (dpc-radar) and a
simulated rain gauge.

Check a file from the command line:

```bash
pip install "egms-client[records]"
egms records examples/records/*
```

::: egms_client.records
