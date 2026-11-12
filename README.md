# TAS Data Readers

General triple-axis data-reader format detection and lightweight metadata adapters for the TAS co-pilot.

This repo is the common reader boundary for non-BT-7 and cross-instrument TAS data. It should not become a reduction package or a catalog service.

Initial format families:

- NCNR BT-7 ICE/NICE text data
- NCNR BT-4 legacy `.bt4` data
- ANSTO TAIPAN NeXus/HDF5 `*.nx.hdf`
- ANSTO TAIPAN exported `TAIPAN_exp*_scan*.dat`
- ILL-style `*.ILL` export
- HFIR HB-1A `HB1A_exp*_scan*.dat`
- MURR TRIAX `TRIAX_exp*_scan*.dat`

## Source Provenance

Format conventions were cross-checked against the historical NCNR
tripleaxisproject readers (`readncnr.py`, `readicp*.py`,
`data_abstraction.py`), TAIPAN `nxs_reader.py`/`taipan_reader.py`,
HFIR `read_hfir.py`, and MURR `murr_reader.py`.
Those historical project directories and experimental data are not bundled.
The implementation and synthetic format fixtures used here are included.

## Co-pilot Tools

- `tas.data_reader.classify_tas_format`
- `tas.data_reader.read_tas_metadata`
- `tas.data_reader.scan_tas_directory`
- `tas.data_reader.read_ncnr_legacy_file`

The first implementation is conservative: it detects format families from paths, filenames, and small optional header snippets supplied by the caller. It does not hydrate large Box files or parse full scientific data arrays.

For NCNR BT-4 legacy files, the metadata field meanings are aligned with the historical `readncnr.py` layout from the triple-axis project. This package carries a small Python 3 metadata port of that layout for catalog fields such as scan variable, sample line, timestamp, monitor base, count base, point count, lattice, d-spacing, fixed-energy metadata, first Q/E/T point, and Q-step hints. It does not port full data-array parsing or reduction behavior; those should remain in a proper reader implementation.

`read_ncnr_legacy_file` is the read-only Python 3 boundary for NCNR legacy files. It returns metadata, normalized column names, numeric table rows, basic column stats, and a count of non-tabular lines skipped. It does not execute legacy code, write files, or perform reduction.

For Box placeholder or cloud-backed paths, call `scan_tas_directory` with explicit `paths` and `path_only=true`. In that mode the reader preserves the path as an intended TAS data-file reference, classifies from the path string, marks metadata as `path_only`, and does not open, stat, checksum, or hydrate the file. Hydrated HFIR/MURR fixture tests can be enabled locally with `TAS_DATA_READERS_HYDRATED_FIXTURE=/path/to/sanitized/file`.

## Reproducibility Tests

Install the shared contracts from the
[TASCopilot paper repository](https://github.com/scattering/tascopilot-paper)
and this package into a Python 3.11 or newer environment:

```sh
TASCOPILOT_PAPER=/absolute/path/to/tascopilot-paper
python -m pip install -e "$TASCOPILOT_PAPER/packages/tas_copilot_contracts"
python -m pip install -e . pytest
python -m pytest -q -rs
```

Tests use local fixtures. Optional upstream runtimes or explicitly supplied
archive fixtures are reported as skipped when unavailable. No instrument
connection is required. No full papers, private corpus, or development
handoff documents are included.
