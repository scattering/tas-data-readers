from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
from typing import Any

from tas_copilot_contracts import TASDataFileMetadata


SOURCE_READER_PROVENANCE = {
    "ansto_taipan_nexus_hdf5": "Ho2Ti2O7/ANSTO/exp1337/Datafiles/nxs_reader.py",
    "ansto_taipan_dat": "Ho2Ti2O7/ANSTO/exp1337/Datafiles/taipan_reader.py",
    "hfir_hb1a_dat": "Ho2Ti2O7/Ho2Ti2O7/utilities/read_hfir.py",
    "murr_triax_dat": "Fe5GeTe2/Fe3GaTe2/MURR April 2024/exp141/Datafiles/murr_reader.py",
    "ncnr_bt4_legacy": "tripleaxisproject/tripleaxisproject/eclipse/src/utilities/readncnr.py",
    "ncnr_bt7_ice_nice": "bt7grouping.copilot_plugin",
}

BT4_HEADER_RE = re.compile(
    r"'(?P<header_filename>[^']+)'\s+"
    r"'(?P<header_date>[^']+)'\s+"
    r"'(?P<header_scan_variable>[^']+)'\s+"
    r"(?P<monitor>[-+0-9.]+)\s+"
    r"(?P<prefactor>[-+0-9.]+)\s+"
    r"'(?P<count_base>[^']+)'\s+"
    r"(?P<points>\d+)\s+"
    r"'(?P<raw_type>[^']+)'"
)


def classify_path(path: str, header: str | None = None) -> dict[str, Any]:
    p = Path(path)
    name = p.name
    lower_name = name.lower()
    lower_path = str(p).lower()
    header_text = (header or "").lower()

    if lower_name.endswith(".nx.hdf") or "nexus" in header_text or "nxentry" in header_text:
        return _result("ansto_taipan_nexus_hdf5", "ANSTO", "TAIPAN", "NeXus/HDF5", path)
    if lower_name.endswith(".ill"):
        return _result("ill_export", None, None, "ILL export", path)
    if re.match(r"taipan_exp\d+_scan\d+\.dat$", lower_name):
        return _result("ansto_taipan_dat", "ANSTO", "TAIPAN", "TAIPAN dat", path)
    if re.match(r"hb1a_exp\d+_scan\d+\.dat$", lower_name) or "hb-1a" in lower_path or "hb1a" in lower_path:
        return _result("hfir_hb1a_dat", "HFIR", "HB-1A", "HB-1A dat", path)
    if re.match(r"triax_exp\d+_scan\d+\.dat$", lower_name) or "triax" in lower_path:
        return _result("murr_triax_dat", "MURR", "TRIAX", "TRIAX dat", path)
    if lower_name.endswith(".bt4") or lower_name.endswith(".bt4.html"):
        return _result("ncnr_bt4_legacy", "NCNR", "BT-4", "BT-4 legacy", path)
    if lower_name.endswith(".bt7") or "/bt7/" in lower_path or "/bt-7/" in lower_path:
        return _result("ncnr_bt7_ice_nice", "NCNR", "BT-7", "BT-7 ICE/NICE", path)
    if lower_name.endswith(".dat"):
        return _result("generic_tas_dat", None, None, "generic TAS dat", path, confidence=0.2)
    return _result("unknown", None, None, None, path, confidence=0.0)


def read_metadata(path: str, header: str | None = None, path_only: bool = False) -> dict[str, Any]:
    detected = classify_path(path, header=header)
    native = _native_ids(path)
    if path_only:
        enrichment = {
            "raw_metadata": {
                "metadata_mode": "path_only",
                "reader_strategy": "path_only_filename_detection",
                "content_status": "path_only_not_attempted",
                "hydration_status": "not_attempted",
                "stat_status": "not_attempted",
                "checksum_status": "not_attempted",
                "warnings": ["cataloged by explicit path only; file content, stat, checksum, and hydration were not attempted"],
            }
        }
    else:
        enrichment = _bt4_header_metadata(path, header) if detected["format_family"] == "ncnr_bt4_legacy" else _generic_text_metadata(path, header)
    raw_metadata = {
        "filename": Path(path).name,
        "detection_method": "path_header_signature",
        **enrichment.pop("raw_metadata", {}),
    }
    role = _scan_role(path, raw_metadata)
    if role:
        raw_metadata["scan_role"] = role
    return TASDataFileMetadata(
        **detected,
        native_scan_id=native.get("scan_id"),
        native_experiment_id=native.get("experiment_id"),
        **enrichment,
        raw_metadata=raw_metadata,
    ).model_dump(mode="json")


def _scan_role(path: str, raw_metadata: dict[str, Any]) -> str | None:
    filename = Path(path).name.lower()
    native = _bt4_scan_id(Path(path).name)
    header_filename = str(raw_metadata.get("header_filename") or "").lower()
    candidates = [filename, native.lower() if native else "", header_filename]
    if any(value.startswith("fp") for value in candidates if value):
        return "alignment"
    raw_type = str(raw_metadata.get("raw_type") or "").lower()
    scan_variable = str((raw_metadata.get("legacy_metadata") or {}).get("file_info", {}).get("scantype") or "").lower()
    if raw_type == "align" or scan_variable in {"align", "alignment"}:
        return "alignment"
    return None


def scan_directory(root: str, max_files: int | None = None, paths: list[str] | None = None, path_only: bool = False) -> dict[str, Any]:
    records = []
    warnings = []
    explicit_path_only = bool(paths and path_only)
    for path in _iter_scan_paths(root, paths):
        if not explicit_path_only and not path.is_file():
            continue
        detected = classify_path(str(path))
        if detected["format_family"] == "unknown":
            if explicit_path_only:
                warnings.append(f"unrecognized explicit path-only TAS format: {path}")
            continue
        records.append(read_metadata(str(path), path_only=path_only))
        if max_files is not None and len(records) >= int(max_files):
            break
    return {
        "root": root,
        "record_count": len(records),
        "records": records,
        "explicit_path_count": len(paths or []),
        "metadata_mode": "path_only" if path_only else "read_prefix",
        "content_status": "path_only_not_attempted" if path_only else "read_prefix_attempted",
        "hydration_status": "not_attempted" if path_only else "unknown",
        "warnings": warnings,
        "format_counts": _counts(record["format_family"] for record in records),
        "instrument_counts": _counts(record["instrument"] or "unknown" for record in records),
    }


def _iter_scan_paths(root: str, paths: list[str] | None = None):
    if paths:
        for item in paths:
            yield Path(item).expanduser()
        return
    root_path = Path(root).expanduser()
    if root_path.is_file():
        yield root_path
        return
    yield from sorted(root_path.rglob("*"))


def _result(format_family: str, facility: str | None, instrument: str | None, native_format: str | None, path: str, confidence: float = 0.95) -> dict[str, Any]:
    return {
        "path": path,
        "format_family": format_family,
        "facility": facility,
        "instrument": instrument,
        "native_format": native_format,
        "source_adapter": "tas-data-readers.format_detection",
        "source_reader": SOURCE_READER_PROVENANCE.get(format_family),
        "confidence": confidence,
    }


def _native_ids(path: str) -> dict[str, str | None]:
    p = Path(path)
    filename = p.name
    patterns = [
        r"(?P<instrument>TAIPAN)_exp(?P<experiment_id>\d+)_scan(?P<scan_id>\d+)\.dat",
        r"(?P<instrument>HB1A)_exp(?P<experiment_id>\d+)_scan(?P<scan_id>\d+)\.dat",
        r"(?P<instrument>TRIAX)_exp(?P<experiment_id>\d+)_scan(?P<scan_id>\d+)\.dat",
        r"(?P<prefix>TPN)(?P<scan_id>\d+)\.nx\.hdf",
    ]
    for pattern in patterns:
        match = re.match(pattern, filename, flags=re.IGNORECASE)
        if match:
            data = match.groupdict()
            return {
                "experiment_id": data.get("experiment_id"),
                "scan_id": data.get("scan_id"),
            }
    bt4_scan_id = _bt4_scan_id(filename)
    if bt4_scan_id:
        return {"experiment_id": _bt4_experiment_id(p), "scan_id": bt4_scan_id}
    return {"experiment_id": None, "scan_id": None}


def _bt4_scan_id(filename: str) -> str | None:
    lower = filename.lower()
    if lower.endswith(".bt4.html"):
        return filename[: -len(".bt4.html")]
    if lower.endswith(".bt4"):
        return filename[: -len(".bt4")]
    return None


def _bt4_experiment_id(path: Path) -> str | None:
    parts = list(path.parts)
    lowered = [part.lower() for part in parts]
    for index, part in enumerate(lowered):
        if part == "bt4" and index + 2 < len(parts):
            cycle = parts[index + 1]
            directory = parts[index + 2]
            return f"{cycle}-{directory}"
    return None


def _bt4_header_metadata(path: str, header: str | None = None) -> dict[str, Any]:
    text = header if header is not None else _read_text_prefix(path)
    if not text:
        return {}

    lines = text.splitlines()
    if not lines:
        return {}

    raw_metadata: dict[str, Any] = {}
    metadata: dict[str, Any] = {"raw_metadata": raw_metadata}
    raw_metadata["reader_strategy"] = "ncnr_legacy_metadata_port"
    raw_metadata["reader_strategy_note"] = "BT-4 field meanings follow the historical NCNR readncnr.py metadata layout."

    header_match = BT4_HEADER_RE.search(lines[0])
    if header_match:
        groups = header_match.groupdict()
        timestamp = _bt4_timestamp(groups["header_date"])
        raw_metadata.update(
            {
                "header_filename": groups["header_filename"],
                "header_date": groups["header_date"],
                "timestamp": timestamp,
                "monitor": _float_or_none(groups["monitor"]),
                "prefactor": _float_or_none(groups["prefactor"]),
                "count_base": groups["count_base"],
                "points": _int_or_none(groups["points"]),
                "raw_type": groups["raw_type"],
                "legacy_metadata": {
                    "count_info": {
                        "monitor_base": _float_or_none(groups["monitor"]),
                        "monitor_prefactor": _float_or_none(groups["prefactor"]),
                        "monitor": _legacy_monitor(groups["monitor"], groups["prefactor"]),
                        "count_type": groups["count_base"].lower(),
                    },
                    "file_info": {
                        "filename": groups["header_filename"],
                        "filebase": groups["header_filename"][0:5],
                        "scantype": groups["header_scan_variable"].lower(),
                        "instrument": "bt4",
                    },
                    "timestamp": timestamp,
                },
            }
        )
        metadata["scan_variable"] = groups["header_scan_variable"].strip() or None

    sample_name = _bt4_sample_line(lines)
    if sample_name:
        metadata["sample_name"] = sample_name
        raw_metadata["sample_line"] = sample_name

    first_row = _bt4_first_data_row(lines)
    if first_row:
        h, k, l, energy, temperature, minutes, counts = first_row
        metadata["temperature"] = temperature
        metadata["q_hint"] = {"h": h, "k": k, "l": l}
        metadata["energy_hint"] = {
            "value": energy,
            "unit": "meV",
            "source": "bt4_first_data_row",
        }
        raw_metadata["first_row_minutes"] = minutes
        raw_metadata["first_row_counts"] = counts
        raw_metadata["count_time"] = minutes * 60.0

    legacy_metadata = raw_metadata.get("legacy_metadata", {})
    legacy_metadata.update(_bt4_legacy_blocks(lines))
    raw_metadata["legacy_metadata"] = legacy_metadata
    instrument_config = _bt4_instrument_config_hint(legacy_metadata)
    if instrument_config:
        raw_metadata["instrument_config_hint"] = instrument_config

    return {key: value for key, value in metadata.items() if value not in ({}, None)}


def _bt4_instrument_config_hint(legacy_metadata: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    ef = (legacy_metadata.get("energy_info") or {}).get("ef")
    if ef is not None:
        config["fixed_energy_mode"] = "fixed_final_energy"
        config["fixed_energy"] = {"value": ef, "unit": "meV"}
    dspacing = legacy_metadata.get("dspacing") or {}
    if dspacing.get("monochromator_dspacing") is not None:
        config["monochromator"] = f"d={dspacing['monochromator_dspacing']}"
    if dspacing.get("analyzer_dspacing") is not None:
        config["analyzer"] = f"d={dspacing['analyzer_dspacing']}"
    collimations = legacy_metadata.get("collimations") or {}
    if collimations:
        config["collimation"] = "-".join(str(collimations.get(key)) for key in ["coll1", "coll2", "coll3", "coll4"])
    return config


def _generic_text_metadata(path: str, header: str | None = None) -> dict[str, Any]:
    text = header if header is not None else _read_text_prefix(path, max_lines=80)
    if not text:
        return {}

    lines = text.splitlines()
    raw_metadata: dict[str, Any] = {"reader_strategy": "generic_tas_text_metadata"}
    metadata: dict[str, Any] = {"raw_metadata": raw_metadata}

    key_values = _parse_key_values(lines)
    if key_values:
        raw_metadata["header_fields"] = key_values

    scan_variable = _first_value(key_values, ["scan_variable", "scan variable", "scan", "scan_axis", "scan axis", "scantype"])
    if scan_variable:
        metadata["scan_variable"] = str(scan_variable)

    sample_name = _first_value(key_values, ["sample", "sample_name", "sample name", "sample title"])
    if sample_name:
        metadata["sample_name"] = str(sample_name)

    q_hint = _q_from_key_values(key_values)
    energy_hint = _energy_from_key_values(key_values)
    temperature = _float_first(key_values, ["temperature", "temp", "t-act", "tact", "t"])
    magnetic_field = _float_first(key_values, ["field", "magnetic_field", "magnetic field", "hfield", "h field"])
    monitor_counts = _float_first(key_values, ["monitor", "monitor_counts", "monitor counts", "mon"])
    count_time = _float_first(key_values, ["count_time", "count time", "time", "seconds", "sec"])

    table = _first_numeric_table(lines)
    if table:
        raw_metadata["table_columns"] = table["columns"]
        raw_metadata["first_numeric_row"] = table["row"]
        q_hint = q_hint or _q_from_table(table)
        energy_hint = energy_hint or _energy_from_table(table)
        temperature = temperature if temperature is not None else _table_value(table, ["temp", "temperature", "t-act", "tact", "t"])
        magnetic_field = magnetic_field if magnetic_field is not None else _table_value(table, ["field", "magnetic_field", "hfield"])
        monitor_counts = monitor_counts if monitor_counts is not None else _table_value(table, ["monitor", "mon"])
        count_time = count_time if count_time is not None else _table_value(table, ["time", "count_time", "seconds", "sec", "min"])

    if q_hint:
        metadata["q_hint"] = q_hint
    if energy_hint:
        metadata["energy_hint"] = energy_hint
    if temperature is not None:
        metadata["temperature"] = temperature
    if magnetic_field is not None:
        metadata["magnetic_field"] = magnetic_field

    instrument_config = _instrument_config_from_key_values(key_values)
    if instrument_config:
        raw_metadata["instrument_config_hint"] = instrument_config
    lattice = _lattice_from_key_values(key_values)
    if lattice:
        raw_metadata["lattice"] = lattice
    scattering_plane = _scattering_plane_from_key_values(key_values)
    if scattering_plane:
        raw_metadata["scattering_plane"] = scattering_plane
    ub_matrix = _ub_matrix_from_key_values(key_values)
    if ub_matrix:
        raw_metadata["ub_matrix"] = ub_matrix
        raw_metadata["ub_convention"] = _ub_convention_for_path(path, key_values)
    if monitor_counts is not None:
        raw_metadata["monitor_counts"] = monitor_counts
    if count_time is not None:
        raw_metadata["count_time"] = count_time

    return {key: value for key, value in metadata.items() if value not in ({}, None)}


def _parse_key_values(lines: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for line in lines:
        cleaned = line.strip().lstrip("#").strip()
        if not cleaned:
            continue
        if "=" in cleaned:
            key, value = cleaned.split("=", 1)
        elif ":" in cleaned:
            key, value = cleaned.split(":", 1)
        else:
            continue
        key = _normalize_key(key)
        value = value.strip().strip("'\"")
        if key and value:
            fields[key] = _coerce_value(value)
    return fields


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _coerce_value(value: str) -> Any:
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value):
        return float(value)
    return value


def _first_value(fields: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        key = _normalize_key(alias)
        if key in fields and fields[key] not in ("", None):
            return fields[key]
    return None


def _float_first(fields: dict[str, Any], aliases: list[str]) -> float | None:
    value = _first_value(fields, aliases)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _q_from_key_values(fields: dict[str, Any]) -> dict[str, float] | None:
    h = _float_first(fields, ["h", "qh", "q_h", "q1"])
    k = _float_first(fields, ["k", "qk", "q_k", "q2"])
    l = _float_first(fields, ["l", "ql", "q_l", "q3"])
    if any(value is not None for value in [h, k, l]):
        return {"h": h or 0.0, "k": k or 0.0, "l": l or 0.0}
    return None


def _energy_from_key_values(fields: dict[str, Any]) -> dict[str, Any] | None:
    transfer = _float_first(fields, ["energy_transfer", "energy transfer", "en", "e", "delta_e"])
    if transfer is not None:
        return {"value": transfer, "unit": "meV", "source": "header_energy_transfer"}
    ei = _float_first(fields, ["ei", "incident_energy", "incident energy"])
    ef = _float_first(fields, ["ef", "final_energy", "final energy"])
    if ei is not None or ef is not None:
        output: dict[str, Any] = {"unit": "meV", "source": "header_energy"}
        if ei is not None:
            output["ei"] = ei
        if ef is not None:
            output["ef"] = ef
            output["value"] = 0.0
        return output
    return None


def _instrument_config_from_key_values(fields: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    ei = _float_first(fields, ["ei", "incident_energy", "incident energy"])
    ef = _float_first(fields, ["ef", "final_energy", "final energy"])
    if ef is not None:
        config["fixed_energy_mode"] = "fixed_final_energy"
        config["fixed_energy"] = {"value": ef, "unit": "meV"}
    elif ei is not None:
        config["fixed_energy_mode"] = "fixed_incident_energy"
        config["fixed_energy"] = {"value": ei, "unit": "meV"}
    mono = _first_value(fields, ["monochromator", "mono"])
    analyzer = _first_value(fields, ["analyzer", "ana"])
    filters = _first_value(fields, ["filter", "filters"])
    collimation = _first_value(fields, ["collimation", "collimations", "coll"])
    if mono:
        config["monochromator"] = str(mono)
    if analyzer:
        config["analyzer"] = str(analyzer)
    if filters:
        config["filters"] = [item.strip() for item in str(filters).split(",") if item.strip()]
    if collimation:
        config["collimation"] = str(collimation)
    return config


def _lattice_from_key_values(fields: dict[str, Any]) -> dict[str, float] | None:
    keys = ["a", "b", "c", "alpha", "beta", "gamma"]
    values = {key: _float_first(fields, [f"lattice_{key}", key]) for key in keys}
    if all(value is not None for value in values.values()):
        return {key: float(value) for key, value in values.items() if value is not None}
    return None


def _scattering_plane_from_key_values(fields: dict[str, Any]) -> dict[str, Any] | None:
    orient1 = _vector_from_fields(fields, ["orient1", "orientation1", "u", "plane_vector_1", "scattering_plane_1"])
    orient2 = _vector_from_fields(fields, ["orient2", "orientation2", "v", "plane_vector_2", "scattering_plane_2"])
    label = _first_value(fields, ["scattering_plane", "scattering plane", "plane"])
    if orient1 and orient2:
        return {"orient1": [orient1], "orient2": [orient2], "label": str(label) if label else None}
    if label:
        return {"label": str(label)}
    return None


def _ub_matrix_from_key_values(fields: dict[str, Any]) -> list[list[float]] | None:
    direct = _first_value(fields, ["ub", "ub_matrix", "ub matrix"])
    matrix = _parse_matrix(direct)
    if matrix:
        return matrix
    rows = [
        _vector_from_fields(fields, ["ub_row1", "ub row1", "ub1"]),
        _vector_from_fields(fields, ["ub_row2", "ub row2", "ub2"]),
        _vector_from_fields(fields, ["ub_row3", "ub row3", "ub3"]),
    ]
    if all(row is not None and len(row) == 3 for row in rows):
        return [row for row in rows if row is not None]
    return None


def _ub_convention_for_path(path: str, fields: dict[str, Any]) -> str:
    explicit = _first_value(fields, ["ub_convention", "ub convention"])
    if explicit:
        return str(explicit)
    detected = classify_path(path)
    if detected["format_family"] in {"hfir_hb1a_dat", "murr_triax_dat"}:
        return "hfir_murr_instrument_control"
    return "unknown"


def _vector_from_fields(fields: dict[str, Any], aliases: list[str]) -> list[float] | None:
    value = _first_value(fields, aliases)
    vector = _parse_vector(value)
    if vector:
        return vector
    for alias in aliases:
        base = _normalize_key(alias)
        components = [_float_first(fields, [f"{base}_{axis}", f"{base}{axis}"]) for axis in ["h", "k", "l"]]
        if all(component is not None for component in components):
            return [float(component) for component in components if component is not None]
    return None


def _parse_vector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None
    cleaned = str(value).strip().strip("[]()")
    parts = [part for part in re.split(r"[\s,]+", cleaned) if part]
    if len(parts) != 3:
        return None
    try:
        return [float(part) for part in parts]
    except ValueError:
        return None


def _parse_matrix(value: Any) -> list[list[float]] | None:
    if value is None:
        return None
    rows = [row for row in str(value).strip().strip("[]").split(";") if row.strip()]
    matrix = [_parse_vector(row) for row in rows]
    if len(matrix) == 3 and all(row is not None and len(row) == 3 for row in matrix):
        return [row for row in matrix if row is not None]
    return None


def _first_numeric_table(lines: list[str]) -> dict[str, Any] | None:
    for index, line in enumerate(lines):
        columns = [_normalize_column_name(value) for value in line.strip().lstrip("#").split()]
        if len(columns) < 2 or not _looks_like_tas_columns(columns):
            continue
        for candidate in lines[index + 1 :]:
            values = candidate.split()
            if len(values) < len(columns):
                continue
            try:
                numeric = [float(value) for value in values[: len(columns)]]
            except ValueError:
                continue
            return {"columns": columns, "row": dict(zip(columns, numeric))}
    return None


def _looks_like_tas_columns(columns: list[str]) -> bool:
    names = set(columns)
    has_q = bool(names & {"h", "qh", "q_h", "qx"}) and bool(names & {"k", "qk", "q_k", "qy"})
    has_detector = bool(names & {"counts", "detector", "det", "monitor", "mon"})
    return has_q or has_detector


def _q_from_table(table: dict[str, Any]) -> dict[str, float] | None:
    h = _table_value(table, ["h", "qh", "q_h", "qx"])
    k = _table_value(table, ["k", "qk", "q_k", "qy"])
    l = _table_value(table, ["l", "ql", "q_l", "qz"])
    if any(value is not None for value in [h, k, l]):
        return {"h": h or 0.0, "k": k or 0.0, "l": l or 0.0}
    return None


def _energy_from_table(table: dict[str, Any]) -> dict[str, Any] | None:
    value = _table_value(table, ["e", "en", "energy", "energy_transfer"])
    if value is None:
        return None
    return {"value": value, "unit": "meV", "source": "first_numeric_row"}


def _table_value(table: dict[str, Any], aliases: list[str]) -> float | None:
    row = table.get("row", {})
    for alias in aliases:
        key = _normalize_column_name(alias)
        if key in row:
            return float(row[key])
    return None


def _read_text_prefix(path: str, max_lines: int = 32) -> str | None:
    try:
        lines: list[str] = []
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(max_lines):
                line = handle.readline()
                if line == "":
                    break
                lines.append(line)
        return "".join(lines)
    except OSError:
        return None


def _bt4_sample_line(lines: list[str]) -> str | None:
    if len(lines) < 3:
        return None
    sample = lines[2].strip()
    return sample or None


def _bt4_first_data_row(lines: list[str]) -> tuple[float, float, float, float, float, float, int] | None:
    for index, line in enumerate(lines):
        if "Q(x)" not in line or "Q(y)" not in line or "T-act" not in line:
            continue
        for candidate in lines[index + 1 :]:
            values = candidate.split()
            if len(values) < 7:
                continue
            try:
                return (
                    float(values[0]),
                    float(values[1]),
                    float(values[2]),
                    float(values[3]),
                    float(values[4]),
                    float(values[5]),
                    int(values[6]),
                )
            except ValueError:
                continue
    return None


def _bt4_legacy_blocks(lines: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}

    experiment_values = _numeric_line_from_index(lines, 3)
    if experiment_values and len(experiment_values) >= 11:
        parsed["collimations"] = {
            "coll1": experiment_values[0],
            "coll2": experiment_values[1],
            "coll3": experiment_values[2],
            "coll4": experiment_values[3],
        }
        parsed["mosaic"] = {
            "mosaic_monochromator": experiment_values[4],
            "mosaic_sample": experiment_values[5],
            "mosaic_analyzer": experiment_values[6],
        }
        parsed["energy_info"] = {"wavelength": experiment_values[7]}
        parsed["temperature_info"] = {"Tstart": experiment_values[8], "Tstep": experiment_values[9]}
        parsed["magnetic_field"] = {"Hfield": experiment_values[10]}

    lattice_values = _numeric_line_after(lines, "Collimation")
    if lattice_values and len(lattice_values) >= 6:
        parsed["lattice"] = {
            "a": lattice_values[0],
            "b": lattice_values[1],
            "c": lattice_values[2],
            "alpha": lattice_values[3],
            "beta": lattice_values[4],
            "gamma": lattice_values[5],
        }

    energy_values = _numeric_line_after(lines, "Lattice Parameters")
    if energy_values and len(energy_values) >= 7:
        parsed.setdefault("energy_info", {})
        parsed["energy_info"]["ef"] = energy_values[2]
        parsed["q_center"] = {"e_center": energy_values[0]}
        parsed["q_step"] = {"delta_e": energy_values[1]}
        parsed["dspacing"] = {
            "monochromator_dspacing": energy_values[3],
            "analyzer_dspacing": energy_values[4],
        }
        parsed.setdefault("temperature_info", {})
        parsed["temperature_info"].update({"Tstart": energy_values[5], "Tstep": energy_values[6]})

    q_values = _numeric_line_after(lines, "E start")
    if q_values and len(q_values) >= 7:
        parsed.setdefault("q_center", {})
        parsed["q_center"].update({"h_center": q_values[0], "k_center": q_values[1], "l_center": q_values[2]})
        parsed.setdefault("q_step", {})
        parsed["q_step"].update({"delta_h": q_values[3], "delta_k": q_values[4], "delta_l": q_values[5]})
        parsed.setdefault("magnetic_field", {})
        parsed["magnetic_field"]["hfield"] = q_values[6]

    return parsed


def _numeric_line_from_index(lines: list[str], start_index: int) -> list[float] | None:
    for candidate in lines[start_index:]:
        values = candidate.split()
        if not values:
            continue
        try:
            return [float(value) for value in values]
        except ValueError:
            continue
    return None


def _numeric_line_after(lines: list[str], marker: str) -> list[float] | None:
    for index, line in enumerate(lines):
        if marker.lower() not in line.lower():
            continue
        for candidate in lines[index + 1 :]:
            values = candidate.split()
            if not values:
                continue
            try:
                return [float(value) for value in values]
            except ValueError:
                continue
    return None


def _normalize_column_name(value: str) -> str:
    lower = value.strip().lower()
    aliases = {
        "q(x)": "qx",
        "q(y)": "qy",
        "q(z)": "qz",
        "t-act": "temp",
        "two_theta": "a4",
        "2theta": "a4",
    }
    return aliases.get(lower, _normalize_key(lower))


def _bt4_timestamp(value: str) -> dict[str, Any]:
    try:
        parsed = datetime.strptime(" ".join(value.split()), "%b %d %Y %H:%M")
    except ValueError:
        return {"raw": value}
    return {
        "raw": value,
        "iso_local": parsed.isoformat(timespec="minutes"),
        "year": parsed.year,
        "month": parsed.month,
        "day": parsed.day,
        "time": parsed.strftime("%H:%M"),
    }


def _legacy_monitor(monitor: str, prefactor: str) -> float | None:
    monitor_value = _float_or_none(monitor)
    prefactor_value = _float_or_none(prefactor)
    if monitor_value is None or prefactor_value is None:
        return None
    return monitor_value * prefactor_value


def _float_or_none(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
