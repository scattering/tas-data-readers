"""TAS co-pilot plugin entry points for general TAS data readers."""

from __future__ import annotations


def get_tool_specs():
    from tas_copilot_contracts import Availability, ImplementationType, PermissionLevel, SideEffectLevel, ToolSpec

    common = {
        "version": "0.1.0",
        "availability": Availability.available,
        "implementation_type": ImplementationType.python_entrypoint,
        "required_dependencies": ["tas-data-readers"],
        "provenance_policy": "Record path, detected format family, source adapter, and legacy reader provenance.",
        "permissions_required": [PermissionLevel.read_only],
        "enabled_by_default": True,
        "owner_repo": "git@github.com:scattering/tas-data-readers.git",
        "maintainer": "William Ratcliff",
    }
    return [
        ToolSpec(
            name="classify_tas_format",
            namespace="tas.data_reader",
            description="Classify a TAS data file format from path and optional header snippet.",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}, "header": {"type": "string"}, "path_only": {"type": "boolean"}},
            },
            output_schema={"type": "object"},
            side_effect_level=SideEffectLevel.none,
            preconditions=["A local path string is supplied."],
            postconditions=["No file or instrument state is modified."],
            **common,
        ),
        ToolSpec(
            name="read_tas_metadata",
            namespace="tas.data_reader",
            description="Read lightweight TAS data-file metadata without parsing full data arrays.",
            input_schema={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "header": {"type": "string"}}},
            output_schema={"type": "TASDataFileMetadata"},
            side_effect_level=SideEffectLevel.none,
            preconditions=["A local path string is supplied."],
            postconditions=["Metadata summary preserves native IDs and adapter provenance."],
            **common,
        ),
        ToolSpec(
            name="scan_tas_directory",
            namespace="tas.data_reader",
            description="Scan a directory for recognized TAS data-file formats.",
            input_schema={
                "type": "object",
                "required": ["root"],
                "properties": {
                    "root": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "max_files": {"type": "integer"},
                    "path_only": {"type": "boolean"},
                },
            },
            output_schema={"type": "object", "properties": {"records": {"items": {"type": "TASDataFileMetadata"}}}},
            side_effect_level=SideEffectLevel.none,
            preconditions=["A local directory path is supplied."],
            postconditions=["Recognized file summaries are returned without modifying files."],
            **common,
        ),
        ToolSpec(
            name="read_ncnr_legacy_file",
            namespace="tas.data_reader",
            description="Read NCNR legacy TAS metadata and numeric columns using the Python 3 readncnr.py port boundary.",
            input_schema={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "max_rows": {"type": "integer"}}},
            output_schema={"type": "object"},
            side_effect_level=SideEffectLevel.none,
            preconditions=["A local NCNR legacy TAS file path is supplied."],
            postconditions=["Metadata, column names, numeric rows, and column stats are returned without modifying files."],
            **common,
        ),
    ]


def run_tool(call):
    from tas_copilot_contracts import ProvenanceRecord, ToolError, ToolResult, ToolResultStatus

    try:
        from .format_detection import classify_path, read_metadata, scan_directory
        from .ncnr_legacy import read_ncnr_legacy_file

        if (call.tool_namespace, call.tool_name) == ("tas.data_reader", "classify_tas_format"):
            output = classify_path(str(call.arguments.get("path")), header=call.arguments.get("header"))
        elif (call.tool_namespace, call.tool_name) == ("tas.data_reader", "read_tas_metadata"):
            output = read_metadata(str(call.arguments.get("path")), header=call.arguments.get("header"), path_only=bool(call.arguments.get("path_only")))
        elif (call.tool_namespace, call.tool_name) == ("tas.data_reader", "scan_tas_directory"):
            output = scan_directory(
                str(call.arguments.get("root")),
                max_files=call.arguments.get("max_files"),
                paths=call.arguments.get("paths"),
                path_only=bool(call.arguments.get("path_only")),
            )
        elif (call.tool_namespace, call.tool_name) == ("tas.data_reader", "read_ncnr_legacy_file"):
            output = read_ncnr_legacy_file(str(call.arguments.get("path")), max_rows=call.arguments.get("max_rows"))
        else:
            return ToolResult(
                status=ToolResultStatus.validation_failed,
                errors=[ToolError(code="unknown_tool", message=f"Unknown TAS data-reader tool {call.tool_namespace}.{call.tool_name}")],
                tool_name=call.tool_name,
                tool_namespace=call.tool_namespace,
                tool_version="0.1.0",
            )
        return ToolResult(
            status=ToolResultStatus.success,
            output=output,
            provenance=[ProvenanceRecord(source_type="tool", source_id="tas-data-readers", method=call.tool_name)],
            tool_name=call.tool_name,
            tool_namespace=call.tool_namespace,
            tool_version="0.1.0",
        )
    except Exception as exc:
        return ToolResult(
            status=ToolResultStatus.error,
            errors=[ToolError(code=exc.__class__.__name__, message=str(exc))],
            tool_name=call.tool_name,
            tool_namespace=call.tool_namespace,
            tool_version="0.1.0",
        )
