# Humanitarian Data Layer

Public humanitarian, population and health data, standardized onto one set of admin areas, with provenance on every number.

One flat table, one row per value: area, metric, breakdown, period, source, status and method. It is built to be read by people in a spreadsheet and by tools (including Claude skills) without a database.

Status: v2 alpha, November 2026. First countries: Somalia, South Sudan, Yemen, Lebanon, Haiti, Nigeria.

## What is in it

| Source | What | Grain | In public releases |
|---|---|---|---|
| OCHA COD-AB (via HDX) | admin boundaries, the area spine | admin 0 to 3 | yes |
| WorldPop Global2 R2025A | population total, under-1, under-5, women 15-49; 2025 and projections to 2030 | every admin area | yes |
| GRID3 / WorldPop Nigeria v3.0 | second Nigeria population estimate | state, LGA | yes |
| HDX HAPI | humanitarian needs (HNO), IPC acute food insecurity, 3W presence, IDPs, refugees, returnees, funding, conflict (ACLED-derived), INFORM risk, COD-PS population | national to admin 2 | not yet (terms being checked) |
| WUENIC (UNICEF) | DTP1, DTP3, MCV1/2, PCV3, Pol3 coverage | national | not yet |
| DHS Program API | contraception, unmet need, vaccination, wasting, stunting, mortality, fertility | national, admin 1 | not yet |
| Meta Relative Wealth Index | mean and population-weighted relative wealth | admin 0 to 3 | not yet (CC BY-NC) |
| UN DESA family planning (FPET) | modern contraceptive prevalence, unmet need, users | national | needs an API token |
| IHME vaccine coverage 2025 (snapshot) | DTP1, DTP3, MCV1, under-1 weighted mean with lower/upper bounds | every admin area | no; one-time download, rows carry `as_of` |

Snapshot sources come from a one-time download or a shared folder rather than a URL the build can refetch. Every row from them carries an `as_of` date, and a build without the files on disk skips them and says so (GitHub runners never have them). IHME's snapshot is dated 2026-08-27 and covers Somalia, South Sudan, Yemen, Lebanon and Nigeria; it does not include Haiti. Area means use WorldPop under-1 weights on HDL's areas, so they differ by 1 to 3 points from IHME's own admin tables, which use IHME's boundaries and population.

Planned: IPC acute malnutrition (API key requested), IATI, OpenCelliD.

## Rules the data follows

- Missing is not zero. A source with no value for an area writes no row.
- National figures are never copied down to admin areas.
- A source area that does not match a pinned admin area stays `unmatched` with its own code or label. No fuzzy matching.
- Sources stay separate. WorldPop and COD-PS population, or IPC and HNO, are never merged into one number.
- Every value carries `status`: `sourced`, `derived` (HDL computed it, e.g. a raster sum), `projection`, `stale`, `partial`, `missing`.
- Every downloaded file has a receipt (URL, bytes, SHA-256, time). Every release has a manifest with checksums.

## The table

`hdl_long.parquet` / `hdl_long.csv.gz`, columns:

`area_id, iso3, admin_level, pcode, area_name, source_id, domain, metric, breakdown, value, unit, period, period_start, period_end, status, geo_match, method, source_release, as_of, note`

`area_id` is `ISO3.level.pcode`, for example `SOM.2.SO1101`. `breakdown` holds key=value pairs such as `sector=Nutrition` or `ipc_type=current;phase=3+`. `areas.csv` lists every area with its parent, and `boundaries/` holds the geometries.

## Build it yourself

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
hdl build --countries SOM --sources all --release my-test
```

Outputs land in `build/<release>/full` (every source) and `build/<release>/public` (only sources marked `publish: true` in `src/hdl/config/sources.yaml`). Downloads are cached in `data/raw/` with receipts; `--offline` rebuilds from the cache without touching the network. Each run has a hard request cap (`--max-requests`), spaces requests out, and stops on 401, 403 or 429.

Heavy builds (WorldPop rasters for many countries) run on GitHub Actions through the manual `build` workflow. It uploads the public bundle only.

## Licenses

Code: MIT. Data keeps its source's license; see `DATA_LICENSES.md` in each release and `src/hdl/config/sources.yaml`. A source goes into public releases only after someone has read its terms and set `publish: true`.
