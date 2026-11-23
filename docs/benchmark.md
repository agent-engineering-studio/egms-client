# Benchmark: places where we know the answer

A library that reads ground motion should say the right thing where the
answer is already known. These are five such places. The expected ranges
come from a source outside EGMS (INGV, ARPAE, IFFI, the geology), never from
the data under test.

Every check runs the library the way a user or the MCP server would, on
small crops of the real archive committed in
[`benchmarks/data/`](https://github.com/agent-engineering-studio/egms-client/tree/main/benchmarks/data)
(9.5 MB, release 2020-2025, fetched on 23 November 2026). CI scores them
offline on every pull request: no key, no network.

```bash
make bench                                  # the same as CI: compare with results.json
uv run python -m benchmarks.run             # the table, measured now
uv run python -m benchmarks.fetch           # crop the cases again (needs the CLMS key)
```

## The cases

- **Campi Flegrei** (moving). The caldera rises: INGV's GNSS station at Rione
  Terra, Pozzuoli, rose about 10 cm a year from 2020, and faster after.
- **Bologna** (moving). The plain sinks, from groundwater pumping (ARPAE).
- **The Murge at Gioia del Colle** (still). A limestone plateau, with no
  active landslides or subsidence reported.
- **Foresta Umbra, Gargano** (blind). A beech forest: the radar finds almost
  nothing to measure under the trees.
- **Ancona, the Posatora slope** (moving). A landslide active since 1982;
  here the L2B points are also turned into vertical and east-west maps
  (`decompose`) and checked against L3.

## Results

| Case | Check | Expected | Measured | |
|---|---|---|---|---|
| campi-flegrei | Rione Terra, Pozzuoli | velocity ≥ 50.0 | 145.2 | ✅ |
| campi-flegrei | the caldera rises | share_above ≥ 0.5 | 0.987 | ✅ |
| campi-flegrei | the gulf of Pozzuoli (sea) | not measured | not measured | ✅ |
| bologna | a share of the plain sinks faster than 2 mm/year | share_below ≥ 0.1 | 0.966 | ✅ |
| bologna | the fastest cells sink by more than 5 mm/year | p5 ≤ -5.0 | -11.3 | ✅ |
| murge | vertical: almost every cell inside ±2 mm/year | share_below ≤ 0.05 | 0.052 | ❌ |
| murge | vertical: almost no cell rising | share_above ≤ 0.05 | 0 | ✅ |
| murge | east-west: the median is about zero | -1.0 ≤ median ≤ 1.0 | 1.6 | ❌ |
| foresta-umbra | most of the forest has no cell | coverage ≤ 0.5 | 0.007 | ✅ |
| ancona | the slope: coherent points that move away from the satellite | min ≤ -3.0 | -9.4 | ✅ |
| ancona | vertical from L2B against L3 | correlation ≥ 0.85 | 0.925 | ✅ |
| ancona | vertical from L2B against L3, median difference | median_abs_diff ≤ 1.5 | 0.603 | ✅ |
| ancona | analysis.fit gives back the archive's mean_velocity | median_abs_diff ≤ 0.1 | 0.025 | ✅ |

**11 of 13** checks pass.

**Check:** 11 of 13. The two that fail are kept failing on purpose: they
show where an expectation about EGMS was wrong.

## What it taught

- **"Still" is not zero.** At the Murge, east-west, the whole box moves east
  by 1.6 mm/year (median; 95 % of cells between 0.5 and 2.7). Ancona shows
  2.0. It is a regional offset, not a local motion: most likely the
  Adriatic plate moving against the reference of the L3 product. Vertical,
  the median is -0.9 mm/year, and 5.2 % of cells are below -2 mm/year. A
  velocity should be read against its region, not against zero.
- **Blind is real, and large.** In the Foresta Umbra 0.7 % of the cells
  have a value. At the Murge, open farmland, 45 % do. Where there is no
  cell, the answer is "not measured", and the benchmark checks that the
  sea at Pozzuoli gives exactly that.
- **The library gives back the archive.** `analysis.fit` reproduces the
  archive's own `mean_velocity` within 0.025 mm/year (median), and
  `decompose` matches L3 with correlation 0.93.

## What is not there

- **A truth per pixel.** The sources give a range for a place, not a
  velocity for each 100 m cell. A GNSS comparison point by point is not done.
- **Bologna is an easy check.** 97 % of the cells in the box sink faster
  than 2 mm/year: the check would catch a sign error, not a subtle one.
- **One release.** Every case is on 2020-2025. A new release must be
  fetched, scored and recorded again; phase 3 of the roadmap watches for it.
- **Snow, steep mountains, fast landslides.** No case yet where InSAR loses
  motion that is too fast, or where snow hides the ground in winter.

*Data: EGMS, © European Union, Copernicus Land Monitoring Service.*
