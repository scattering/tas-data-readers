from pathlib import Path
import os

import pytest
from tas_copilot_contracts import TASDataFileMetadata, ToolCall, ToolResultStatus

from tas_data_readers.copilot_plugin import get_tool_specs, run_tool
from tas_data_readers.format_detection import classify_path, read_metadata, scan_directory
from tas_data_readers.ncnr_legacy import read_ncnr_legacy_file


def test_classify_known_tas_formats():
    cases = [
        ("TPN0115523.nx.hdf", "ansto_taipan_nexus_hdf5", "ANSTO", "TAIPAN"),
        ("TAIPAN_exp1337_scan115516.dat", "ansto_taipan_dat", "ANSTO", "TAIPAN"),
        ("HB1A_exp1083_scan0001.dat", "hfir_hb1a_dat", "HFIR", "HB-1A"),
        ("TRIAX_exp0153_scan0001.dat", "murr_triax_dat", "MURR", "TRIAX"),
        ("fmx01008.bt4.html", "ncnr_bt4_legacy", "NCNR", "BT-4"),
        ("scan001.bt7", "ncnr_bt7_ice_nice", "NCNR", "BT-7"),
        ("TPN0115528.ILL", "ill_export", None, None),
    ]
    for path, family, facility, instrument in cases:
        result = classify_path(path)
        assert result["format_family"] == family
        assert result["facility"] == facility
        assert result["instrument"] == instrument


def test_classify_real_smoke_matrix_filenames():
    cases = [
        ("L_scan_2527.bt7", "ncnr_bt7_ice_nice", "NCNR", "BT-7"),
        ("CaB10003.bt4", "ncnr_bt4_legacy", "NCNR", "BT-4"),
        ("TPN0115552.nx.hdf", "ansto_taipan_nexus_hdf5", "ANSTO", "TAIPAN"),
        ("TAIPAN_exp1337_scan115387.dat", "ansto_taipan_dat", "ANSTO", "TAIPAN"),
        ("HB1A_exp1083_scan0059.dat", "hfir_hb1a_dat", "HFIR", "HB-1A"),
        ("TRIAX_exp0153_scan0023.dat", "murr_triax_dat", "MURR", "TRIAX"),
    ]

    for filename, family, facility, instrument in cases:
        result = classify_path(filename)
        assert result["format_family"] == family
        assert result["facility"] == facility
        assert result["instrument"] == instrument


def test_read_metadata_extracts_native_ids():
    metadata = read_metadata("/data/HB1A_exp1083_scan0001.dat")

    assert metadata["native_experiment_id"] == "1083"
    assert metadata["native_scan_id"] == "0001"
    assert metadata["source_adapter"] == "tas-data-readers.format_detection"
    TASDataFileMetadata.model_validate(metadata)


def test_read_metadata_extracts_native_ids_across_real_smoke_matrix():
    cases = [
        ("TAIPAN_exp1337_scan115387.dat", "1337", "115387"),
        ("HB1A_exp1083_scan0059.dat", "1083", "0059"),
        ("TRIAX_exp0153_scan0023.dat", "0153", "0023"),
        ("TPN0115552.nx.hdf", None, "0115552"),
        ("/data/bt4/201708/udovic/CaB10003.bt4", "201708-udovic", "CaB10003"),
        ("/data/bt4/201708/udovic/fmx01563.bt4.html", "201708-udovic", "fmx01563"),
    ]

    for filename, experiment_id, scan_id in cases:
        metadata = read_metadata(filename)
        TASDataFileMetadata.model_validate(metadata)
        assert metadata["native_experiment_id"] == experiment_id
        assert metadata["native_scan_id"] == scan_id


def test_read_metadata_extracts_bt4_header_metadata():
    header = """'CaB10003.bt4' 'Aug 12 2017 10:00' 'T'      63000.    1  'NEUT'  114  'RAW'
  Filename         Date            Scan       Mon    Prf  Base   #pts  Type
CaB10H10/0.5396g/fltplt/dried200C/4K/2020Cu
  20  20  99  99       0  0  0           0 0 0   0.000    0 0 0
 Collimation        Mosaic              Xstal Orientation
     0.000     0.000     0.000     0.000     0.000     0.000
Lattice Parameters in real space
    50.160     0.400      155.050        1.278   3.354      0.00000   0.00000
    E start   Delta E      E final       M-dsp   A-dsp     Tmp strt   Tmp inc
  0.000   0.000   0.000    0.0000  0.0000  0.0000      0.0000
   Q (hkl scan center)        Delta Q (hkl)            Hfield
    Q(x)    Q(y)    Q(z)     E       T-act    min       Counts
  0.0000  0.0000  0.0000  50.1600  4.22050    5.32         266
"""

    metadata = read_metadata("/data/bt4/201708/udovic/CaB10003.bt4", header=header)

    TASDataFileMetadata.model_validate(metadata)
    assert metadata["scan_variable"] == "T"
    assert metadata["sample_name"] == "CaB10H10/0.5396g/fltplt/dried200C/4K/2020Cu"
    assert metadata["temperature"] == 4.2205
    assert metadata["q_hint"] == {"h": 0.0, "k": 0.0, "l": 0.0}
    assert metadata["energy_hint"] == {"value": 50.16, "unit": "meV", "source": "bt4_first_data_row"}
    assert metadata["raw_metadata"]["monitor"] == 63000.0
    assert metadata["raw_metadata"]["points"] == 114
    assert metadata["raw_metadata"]["first_row_counts"] == 266
    assert abs(metadata["raw_metadata"]["count_time"] - 319.2) < 1e-9
    assert metadata["raw_metadata"]["instrument_config_hint"]["fixed_energy_mode"] == "fixed_final_energy"
    assert metadata["raw_metadata"]["instrument_config_hint"]["fixed_energy"] == {"value": 155.05, "unit": "meV"}
    assert metadata["raw_metadata"]["reader_strategy"] == "ncnr_legacy_metadata_port"
    assert metadata["raw_metadata"]["timestamp"]["iso_local"] == "2017-08-12T10:00"
    legacy = metadata["raw_metadata"]["legacy_metadata"]
    assert legacy["count_info"]["monitor"] == 63000.0
    assert legacy["file_info"]["scantype"] == "t"
    assert legacy["lattice"]["a"] == 0.0
    assert legacy["energy_info"]["ef"] == 155.05
    assert legacy["dspacing"]["monochromator_dspacing"] == 1.278
    assert legacy["q_center"] == {"e_center": 50.16, "h_center": 0.0, "k_center": 0.0, "l_center": 0.0}


def test_read_metadata_marks_likely_bt4_alignment_files():
    header = """'fp001.bt4' 'Aug 12 2017 10:00' 'A3'      30.    1  'TIME'  2  'RAW'
  Filename         Date            Scan       Mon    Prf  Base   #pts  Type
alignment scan
    Q(x)    Q(y)    Q(z)     E       T-act    min       Counts
  0.0000  0.0000  0.0000  32.9300 75.83200    0.50          16
"""

    metadata = read_metadata("/data/bt4/201708/udovic/fp001.bt4", header=header)

    TASDataFileMetadata.model_validate(metadata)
    assert metadata["raw_metadata"]["scan_role"] == "alignment"


def test_read_metadata_extracts_generic_tas_text_hints(tmp_path):
    path = tmp_path / "TAIPAN_exp1337_scan115387.dat"
    path.write_text(
        """# Sample: Ho2Ti2O7
# Scan variable: en
# Ei: 14.7
# Ef: 14.7
# Monochromator: PG(002)
# Analyzer: PG(002)
# Filter: PG
# Collimation: open-open-open-open
# lattice_a: 10.1
# lattice_b: 10.1
# lattice_c: 10.1
# alpha: 90
# beta: 90
# gamma: 90
# orient1: 1 0 0
# orient2: 0 1 0
# h k l en temp monitor time counts
1.0 0.0 0.0 0.5 4.2 10000 60 123
""",
        encoding="utf-8",
    )

    metadata = read_metadata(str(path))

    TASDataFileMetadata.model_validate(metadata)
    assert metadata["sample_name"] == "Ho2Ti2O7"
    assert metadata["scan_variable"] == "en"
    assert metadata["q_hint"] == {"h": 1.0, "k": 0.0, "l": 0.0}
    assert metadata["energy_hint"] == {"ei": 14.7, "ef": 14.7, "source": "header_energy", "unit": "meV", "value": 0.0}
    assert metadata["temperature"] == 4.2
    assert metadata["raw_metadata"]["instrument_config_hint"]["fixed_energy_mode"] == "fixed_final_energy"
    assert metadata["raw_metadata"]["instrument_config_hint"]["filters"] == ["PG"]
    assert metadata["raw_metadata"]["lattice"]["a"] == 10.1
    assert metadata["raw_metadata"]["scattering_plane"]["orient1"] == [[1.0, 0.0, 0.0]]
    assert metadata["raw_metadata"]["monitor_counts"] == 10000.0
    assert metadata["raw_metadata"]["count_time"] == 60.0


def test_read_metadata_preserves_hfir_murr_ub_matrix_with_convention(tmp_path):
    path = tmp_path / "HB1A_exp1083_scan0059.dat"
    path.write_text(
        """# UB: 1 0 0; 0 1 0; 0 0 1
# h k l en monitor time
1 0 0 0 1000 30
""",
        encoding="utf-8",
    )

    metadata = read_metadata(str(path))

    assert metadata["raw_metadata"]["ub_matrix"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert metadata["raw_metadata"]["ub_convention"] == "hfir_murr_instrument_control"


def test_scan_directory_counts_recognized_formats(tmp_path):
    for name in ["HB1A_exp1083_scan0001.dat", "TRIAX_exp0153_scan0001.dat", "notes.txt", "Aug032017_01.LOG", "index.html"]:
        (tmp_path / name).write_text("fixture", encoding="utf-8")

    summary = scan_directory(str(tmp_path))

    assert summary["record_count"] == 2
    for record in summary["records"]:
        TASDataFileMetadata.model_validate(record)
    assert summary["format_counts"]["hfir_hb1a_dat"] == 1
    assert summary["instrument_counts"]["TRIAX"] == 1


def test_scan_directory_accepts_explicit_file_list_without_directory_walk(tmp_path):
    hfir = tmp_path / "HB1A_exp1083_scan0059.dat"
    murr = tmp_path / "TRIAX_exp0153_scan0023.dat"
    notes = tmp_path / "notes.txt"
    hfir.write_text("# h k l en\n1 0 0 0\n", encoding="utf-8")
    murr.write_text("# h k l en\n1 0 0 0\n", encoding="utf-8")
    notes.write_text("ignore", encoding="utf-8")

    summary = scan_directory(str(tmp_path / "not-walked"), paths=[str(hfir), str(notes), str(murr)])

    assert summary["record_count"] == 2
    assert summary["explicit_path_count"] == 3
    assert summary["format_counts"] == {"hfir_hb1a_dat": 1, "murr_triax_dat": 1}


def test_scan_directory_accepts_single_file_root(tmp_path):
    path = tmp_path / "HB1A_exp1083_scan0059.dat"
    path.write_text("# h k l en\n1 0 0 0\n", encoding="utf-8")

    summary = scan_directory(str(path))

    assert summary["record_count"] == 1
    assert summary["records"][0]["native_scan_id"] == "0059"


def test_path_only_metadata_avoids_content_read_for_box_placeholders():
    path = "/cloud/HB1A_exp1083_scan0059.dat"

    metadata = read_metadata(path, path_only=True)

    TASDataFileMetadata.model_validate(metadata)
    assert metadata["format_family"] == "hfir_hb1a_dat"
    assert metadata["native_experiment_id"] == "1083"
    assert metadata["native_scan_id"] == "0059"
    assert metadata["raw_metadata"]["metadata_mode"] == "path_only"
    assert metadata["raw_metadata"]["content_status"] == "path_only_not_attempted"
    assert metadata["raw_metadata"]["hydration_status"] == "not_attempted"
    assert metadata["raw_metadata"]["stat_status"] == "not_attempted"
    assert metadata["raw_metadata"]["checksum_status"] == "not_attempted"
    assert metadata["raw_metadata"]["warnings"]


def test_scan_directory_path_only_on_explicit_files_does_not_require_files_to_exist():
    summary = scan_directory(
        "/cloud/not-walked",
        paths=["/cloud/HB1A_exp1083_scan0059.dat", "/cloud/TRIAX_exp0153_scan0023.dat"],
        path_only=True,
    )

    assert summary["record_count"] == 2
    assert summary["metadata_mode"] == "path_only"
    assert summary["content_status"] == "path_only_not_attempted"
    assert summary["hydration_status"] == "not_attempted"
    assert summary["format_counts"] == {"hfir_hb1a_dat": 1, "murr_triax_dat": 1}
    assert {record["raw_metadata"]["metadata_mode"] for record in summary["records"]} == {"path_only"}
    assert {record["native_scan_id"] for record in summary["records"]} == {"0059", "0023"}


def test_scan_directory_path_only_explicit_files_does_not_call_is_file(monkeypatch):
    def fail_is_file(self):
        raise AssertionError("explicit path_only should not stat/check file existence")

    monkeypatch.setattr(Path, "is_file", fail_is_file)

    summary = scan_directory(
        "/cloud/not-walked",
        paths=["/cloud/HB1A_exp1083_scan0059.dat"],
        path_only=True,
    )

    assert summary["record_count"] == 1
    assert summary["records"][0]["raw_metadata"]["reader_strategy"] == "path_only_filename_detection"


def test_scan_directory_path_only_reports_unrecognized_explicit_paths():
    summary = scan_directory(
        "/cloud/not-walked",
        paths=["/cloud/not_a_tas_file.txt"],
        path_only=True,
    )

    assert summary["record_count"] == 0
    assert summary["warnings"] == ["unrecognized explicit path-only TAS format: /cloud/not_a_tas_file.txt"]


def test_optional_hydrated_hfir_or_murr_fixture_hook():
    fixture = os.environ.get("TAS_DATA_READERS_HYDRATED_FIXTURE")
    if not fixture:
        pytest.skip("set TAS_DATA_READERS_HYDRATED_FIXTURE to a tiny sanitized hydrated HFIR or MURR file")

    metadata = read_metadata(fixture)

    assert metadata["format_family"] in {"hfir_hb1a_dat", "murr_triax_dat"}
    assert metadata["raw_metadata"]["metadata_mode"] != "path_only"


def test_bt4_directory_noise_is_not_classified_as_data():
    assert classify_path("/data/bt4/201708/udovic/Aug032017_01.LOG")["format_family"] == "unknown"
    assert classify_path("/data/bt4/201708/udovic/index.html")["format_family"] == "unknown"
    assert classify_path("/data/bt4/201708/udovic/CaB10003.bt4")["format_family"] == "ncnr_bt4_legacy"


def test_plugin_specs_and_run():
    specs = get_tool_specs()
    assert {spec.name for spec in specs} == {"classify_tas_format", "read_tas_metadata", "scan_tas_directory", "read_ncnr_legacy_file"}

    result = run_tool(
        ToolCall(
            tool_namespace="tas.data_reader",
            tool_name="classify_tas_format",
            arguments={"path": "TRIAX_exp0153_scan0001.dat"},
        )
    )

    assert result.status == ToolResultStatus.success
    assert result.output["format_family"] == "murr_triax_dat"


def test_read_ncnr_legacy_file_returns_columns_and_stats(tmp_path):
    path = tmp_path / "CaB10003.bt4"
    path.write_text(
        """'CaB10003.bt4' 'Aug 12 2017 10:00' 'T'      63000.    1  'NEUT'  114  'RAW'
  Filename         Date            Scan       Mon    Prf  Base   #pts  Type
CaB10H10/0.5396g/fltplt/dried200C/4K/2020Cu
  20  20  99  99       0  0  0           0 0 0   0.000    0 0 0
 Collimation        Mosaic              Xstal Orientation
     0.000     0.000     0.000     0.000     0.000     0.000
Lattice Parameters in real space
    50.160     0.400      155.050        1.278   3.354      0.00000   0.00000
    E start   Delta E      E final       M-dsp   A-dsp     Tmp strt   Tmp inc
  0.000   0.000   0.000    0.0000  0.0000  0.0000      0.0000
   Q (hkl scan center)        Delta Q (hkl)            Hfield
    Q(x)    Q(y)    Q(z)     E       T-act    min       Counts
  0.0000  0.0000  0.0000  50.1600  4.22050    5.32         266
 63000,8,8,4,6,6,8,4,4,5,8,9,7,7,6,8
  0.0000  0.0000  0.0000  50.6900  4.21610    6.46         329
""",
        encoding="utf-8",
    )

    output = read_ncnr_legacy_file(str(path))

    assert output["columns"] == ["qx", "qy", "qz", "e", "temp", "min", "counts"]
    assert output["row_count"] == 2
    assert output["skipped_non_tabular_lines"] == 1
    assert output["rows"][0]["e"] == 50.16
    assert output["rows"][1]["counts"] == 329.0
    assert output["column_stats"]["e"] == {"min": 50.16, "max": 50.69, "first": 50.16, "last": 50.69}
    assert output["metadata"]["sample_name"].startswith("CaB10H10")


def test_plugin_reads_ncnr_legacy_file(tmp_path):
    path = tmp_path / "short.bt4"
    path.write_text(
        """'short.bt4' 'Aug 12 2017 10:00' 'T'      30.    1  'TIME'  2  'RAW'
  Filename         Date            Scan       Mon    Prf  Base   #pts  Type
sample
    Q(x)    Q(y)    Q(z)     E       T-act    min       Counts
  0.0000  0.0000  0.0000  32.9300 75.83200    0.50          16
  0.0000  0.0000  0.0000  34.0900 75.47800    0.50          18
""",
        encoding="utf-8",
    )

    result = run_tool(
        ToolCall(
            tool_namespace="tas.data_reader",
            tool_name="read_ncnr_legacy_file",
            arguments={"path": str(path), "max_rows": 1},
        )
    )

    assert result.status == ToolResultStatus.success
    assert result.output["row_count"] == 1
    assert result.output["rows"][0]["counts"] == 16.0
