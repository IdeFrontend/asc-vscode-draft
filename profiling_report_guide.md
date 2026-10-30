# NPU profiling report guide

This guide describes NPUSim profiling report features, their metrics, and the
underlying `.npu-rep` tables in the current Ascend950 workflow without an object
file. Each feature and shared-data section includes a UI mapping template for
completion by the UI team. Feature identifiers and order retain
the established feature list, including repeated numeric identifiers.

Each available feature identifies its related tables and describes all fields
of the tables defined in that section. Shared tables have one field reference
and are linked from the other features that use them. A table or view appears
as a same-named CSV only when it has rows and can be queried. The manifest remains
the authority for the exact schema and export status of a particular archive.

For each UI element, fill in its source tables and fields, display rules
(including units, formatting, aggregation, and filtering), and screenshot
references. Add screenshots under `figures/` alongside this document and insert
them into the corresponding section. UI templates are also reserved for features
that are not currently available.

- [NPU report format](#npu-report-format)
- [General Features](#general-features)
- [Performance Hints](#performance-hints)

## NPU report format

### Generate and locate an archive

Generate reports from an existing simulation record:

```bash
npusim report -e /path/to/record -o /path/to/report
```

For the record command and collection options, see the existing
[user guide (Chinese)](../../zh/user_guide/01_user_guide.md).

The export stage writes one archive per processed contract database. A typical
location is:

```text
report/
└── results/
    └── <launch_id>_<kernel_name>_reports/
        └── <db_stem>.npu-rep
```

The archive filename comes from the database filename. The report directory can
also use a database-stem-based name. If the exporter cannot locate the matching
report directory, it writes a CSV-only archive, with its manifest, directly under
the report output directory. Export failures produce warnings and do not fail
the report run; check those warnings if an expected archive is missing.

### Understand the payload

| Payload | Inclusion rule | Purpose |
| --- | --- | --- |
| `manifest.json` | Written by the database exporter | Database identity, export time, object inventory, columns, row counts, and query errors |
| `<table_name>.csv` | Written for each nonempty, successfully queried user table | Collected events, dictionaries, metadata, and analysis results |
| `<view_name>.csv` | Written for each nonempty, successfully queried user view | Materialized aggregations and joins at export time |
| Report JSON files | Copied from the matching report directory | Summaries, instruction traces, core activity, and optional reports |

The exporter enumerates all database tables and views except names beginning
with `sqlite_`; it does not use a fixed allowlist. As a result, additional
database objects can appear in later builds. `manifest.json` is the inventory of
database objects for this export, while the container entries are the inventory
of all packaged files, including report JSON.

The standard export stages CSV and JSON files in a flat temporary directory and
removes that directory after packing. An illustrative logical payload is:

```text
<db_stem>.npu-rep
├── manifest.json
├── KernelInfo.csv
├── ExecutedInstructions.csv
├── CoreTypes.csv
├── InstrTypes.csv
├── PipesUtilization.csv
├── summary.json
├── aicore_utilization.json
├── core_0_tracing_report_0.json
├── core_0_tracing_report_1.json
├── core_0_smart_pipe_report_0.json
├── core_0_critical_path_report_0.json
├── <db_stem>_vf_report.json
├── MemoryHeatmapLayout.csv
└── MemoryHeatmapCells.csv
```

Packing happens before the report directory is reorganized for the dashboard.
Consequently, archive entries retain engine filenames such as
`core_0_tracing_report_0.json`, even when the corresponding file on disk is later
named `core_0/trace_core0.json`. Files ending in `.json.gz` are decompressed and
stored as `.json` entries. Consumers must handle multiple trace chunks.

The standard export does not package the SQLite database itself, raw simulator
logs, the kernel executable, HTML reports, or dashboard HTML/JavaScript/CSS.
This document covers the current workflow without an object file. Source
correlation and call-tree datasets are unavailable in this workflow.

### Read the manifest and CSV files

The manifest contains:

| Field | Meaning |
| --- | --- |
| `database` | Absolute path of the exported database on the generating machine |
| `exported_at` | UTC export timestamp in ISO 8601 format |
| `total_objects`, `total_tables`, `total_views` | Counts of discovered database objects, including empty objects |
| `total_rows` | Sum of exported object row counts; includes both tables and views |
| `objects` | Object metadata records |

Each object record has `name`, `type` (`table` or `view`), `row_count`, and
`columns`. Each column has a `name` and a declared SQLite `type`, which can be an
empty string for an expression or view column. The optional `file` field names
the emitted CSV. An `error` field records a failure to query the object.

An empty object has `row_count: 0` and no CSV file. Distinguish this from an
object that is absent from the schema or has an export error. Also, `total_rows`
is not a count of unique execution events: views can repeat or aggregate table
data.

CSV files use UTF-8, comma separators, a header row in database column order, and
Python `csv.writer` quoting with CRLF record endings. SQL `NULL` becomes an empty
field, binary values become lowercase hexadecimal text prefixed with `0x`, and
other values retain their numeric or text representation. An empty text value
and SQL `NULL` cannot be distinguished after export. Use a CSV parser, especially
for columns containing JSON or instruction parameters, and do not assume a
stable row order: the export query has no `ORDER BY`.

### Read the binary container

The `.npu-rep` file is a custom binary container. Its layout is a header,
an array of file descriptors, and concatenated file payloads. Integer fields are
little-endian, with no alignment padding.

The 36-byte header uses Python struct format `<8sIHHIIIQ`:

| Field | Size in bytes | Value or meaning |
| --- | --- | --- |
| `magic` | 8 | ASCII `npu-rep` followed by a zero byte |
| `version` | 4 | `0x00010000`; major, minor, and patch encoded as `major << 16`, `minor << 8`, and `patch` |
| `origin` | 2 | `1` for profiling |
| `repHeadLength` | 2 | `36` |
| `fileInfoCount` | 4 | Number of entries |
| `fileInfoLength` | 4 | `160` |
| `reserved` | 4 | `0` |
| `npuRepLength` | 8 | Total size of this container |

Each 160-byte descriptor uses struct format `<8s128sHHIQQ`:

| Field | Size in bytes | Value or meaning |
| --- | --- | --- |
| `magic` | 8 | Same magic as the header |
| `fileName` | 128 | Basename, at most 127 encoded bytes, padded with zero bytes |
| `type` | 2 | Payload type identifier |
| `reserved` | 2 | `0` |
| `reserved1` | 4 | `0` |
| `fileLength` | 8 | Payload size in bytes |
| `fileRepOffset` | 8 | Payload offset from the beginning of this container |

Type identifiers are `1` for a nested report, `2` for JSON, `3` for JSONL, `4`
for CSV, `5` for SQLite3, and `6` for protobuf. These are container capabilities;
the standard export described above supplies CSV and JSON payloads.

The packer sorts entries by encoded filename. If supplied with subdirectories,
it recursively stores each as `<directory_name>.npu.rep` with type `1`; offsets
in that nested container start at its own beginning. This differs from the
flat payload supplied by the standard export. The container stores payload bytes
without compression. See the [packer implementation](../../../npusim/prof/tools/pack_npu_rep.py)
for validation rules.

### Shared Metadata

The following metadata, dictionaries, and instruction-mix summaries are shared
by the features below.
Dynamic instruction IDs join per-execution analysis results; PCs identify static
addresses and may repeat across executions. Keep core ID and core type together
when distinguishing execution contexts. Numeric IDs are local to an archive.

Instruction timing fields are simulator ticks; duration is end minus start.
With frequency `f` GHz, `duration_ns = duration_ticks / f`. Chrome trace `ts` and
`dur` are microseconds even when `displayTimeUnit` is `ns`; conversion normally
uses the architecture frequency. `--no-ticks-to-ns` instead treats one tick as
one nanosecond before converting to microseconds.

SQLite types below are declared affinities. `not declared` identifies a column
or view expression without a declared type; expressions can still be numeric.
SQL NULL becomes an empty CSV field, and boolean values are encoded as 0 or 1.
`AnalysisState` records successful execution, which does not guarantee nonempty
output. Feature options can be passed through the backend's `BIPROF_OPTS`
environment variable. An enabled analyzer still requires suitable collected data.
The [semantic parameter accessor](../../../npusim/prof/src/common/extend_params.py)
lists the `ExtendParams` fields consumed by the analyses.

<a id="table-kernelinfo"></a>

#### KernelInfo

Database table.

One attribute/value record per kernel metadata item. Common attributes include `name`, `launch_id`,
`arch`, `frequency_ghz`, `exec_time_ticks`, `exec_time_ns`, `instrs_exec_num`, `ai_core_active`,
`scalar_ipc`, `helper_version`, and `contract_version`. Values have attribute-specific units and may
be stored as text.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `KernelInfoAttr` | `VARCHAR(20)` | Metadata attribute name, such as `exec_time_ticks` or `frequency_ghz`. |
| `KernelInfoVal` | not declared | Value for the named attribute; parse according to that attribute, rather than assuming all rows have one numeric type. |

<a id="table-coretypes"></a>

#### CoreTypes

Database table.

Core component dictionary. Use this table to resolve numeric IDs rather than hardcoding a mapping.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreTypeId` | `INTEGER` | Numeric core component identifier. |
| `CoreTypeName` | `VARCHAR(20)` | Readable core component name. |

<a id="table-instrtypes"></a>

#### InstrTypes

Database table.

Instruction pipeline/type dictionary. Use this table to resolve numeric IDs rather than hardcoding a
mapping.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `InstrTypeId` | `INTEGER` | Numeric instruction pipeline/type identifier. |
| `InstrTypeName` | `VARCHAR(20)` | Readable instruction pipeline/type name. |

<a id="table-instrqueuetypes"></a>

#### InstrQueueTypes

Database table.

Instruction queue/group dictionary. Use this table to resolve numeric IDs rather than hardcoding a
mapping.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `InstrQueueTypeId` | `INTEGER` | Numeric instruction queue/group identifier. |
| `InstrQueueTypeName` | `VARCHAR(20)` | Readable instruction queue/group name. |

<a id="table-analysisstate"></a>

#### AnalysisState

Database table.

Completion status for registered analyses.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `AnalysisName` | `VARCHAR(70)` | Internal analysis identifier. |
| `AnalysisPassed` | `BOOLEAN` | 1 when the analysis completed successfully, 0 when it did not; not a kernel performance assessment. |

The histogram views summarize recorded instruction counts and summed durations
by pipeline/type or mnemonic. They describe the kernel-wide instruction mix.
`ActiveInstrTypes` lists the types present in the dynamic stream. Summed
instruction duration can exceed elapsed kernel time because instructions overlap.

<a id="table-instrtypehistcount"></a>

#### InstrTypeHistCount

Database view exported as CSV.

Instruction histogram grouped by pipeline/type name.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Type` | `VARCHAR(20)` | Instruction type/pipeline name from `InstrTypes`. |
| `Count` | not declared | Number of dynamic instructions in this group. |

<a id="table-instrtypehistclocks"></a>

#### InstrTypeHistClocks

Database view exported as CSV.

Instruction histogram grouped by pipeline/type name.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Type` | `VARCHAR(20)` | Instruction type/pipeline name from `InstrTypes`. |
| `TickCount` | not declared | Sum of instruction durations in this group, in simulator ticks. |

<a id="table-instrnamehistcount"></a>

#### InstrNameHistCount

Database view exported as CSV.

Instruction histogram grouped by recorded mnemonic.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Name` | `VARCHAR(100)` | Instruction mnemonic from `ExecutedInstructions`. |
| `Count` | not declared | Number of dynamic instructions in this group. |

<a id="table-instrnamehistclocks"></a>

#### InstrNameHistClocks

Database view exported as CSV.

Instruction histogram grouped by recorded mnemonic.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Name` | `VARCHAR(100)` | Instruction mnemonic from `ExecutedInstructions`. |
| `TickCount` | not declared | Sum of instruction durations in this group, in simulator ticks. |

<a id="table-activeinstrtypes"></a>

#### ActiveInstrTypes

Database view exported as CSV.

Distinct instruction pipeline/type names represented in the dynamic stream.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Name` | `VARCHAR(20)` | Instruction pipeline/type name from `InstrTypes`. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

## General Features

### 1. Architecture Diagram

The architecture diagram summarizes data movement between compute and memory
components. The data comes from transfer analysis, matrix/fixpipe parameters,
and pipeline utilization. The archive contains the supporting metrics as CSV;
the rendered architecture files are separate report artifacts.
`UbRwStatistics` supplies collected per-instruction UB traffic statistics used
by this architecture-level bandwidth analysis.

`ArchDiagramMetrics` stores named values. A `_gbs` suffix identifies a path's
aggregate transfer rate, `_cnt` a transaction count, and `_ratio` its
transaction-normalized rate. Other named metrics retain their own definitions.
Aggregate rates divide processed bytes by active core count, kernel elapsed
seconds, and `2^30`; despite the field names, the byte scale is binary gigabytes.
The transaction-normalized rate is not a simple arithmetic mean of individual
transaction rates. Compare the same path and denominator across runs.

**Related tables:** [ArchDiagramMetrics](#table-archdiagrammetrics), [KernelInfo](#table-kernelinfo), [DmaMovProcessedBytes](#table-dmamovprocessedbytes), [UbRwStatistics](#table-ubrwstatistics), [MmadParams](#table-mmadparams), [FixpParams](#table-fixpparams), [PipesUtilization](#table-pipesutilization).

[Implementation](../../../npusim/prof/src/backend/analyzers/arch_diagram_analyzer.py).

<a id="table-archdiagrammetrics"></a>

#### ArchDiagramMetrics

Database table.

Named metrics calculated for architecture-level analysis, including path throughput, transaction
counts, and selected ratios. The metric name determines the unit of the value.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ArchDiagramId` | `INTEGER` | Identifier of this metric row. |
| `ArchDiagramParameterName` | `VARCHAR(20)` | Metric name; path suffixes include `_gbs` for aggregate rate, `_cnt` for transaction count, and `_ratio` for the path's transaction-normalized rate. Other named ratios have their own definitions. |
| `ArchDiagramParameterValue` | `REAL` | Numeric metric value; see the bandwidth definitions and analyzer formulas for the named metric. |

<a id="table-ubrwstatistics"></a>

#### UbRwStatistics

Database table.

Collector-provided per-instruction UB traffic statistics, used for vector/shared-memory bandwidth
analysis.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ProcessedBytes` | `INTEGER` | Number of bytes processed by the instruction according to the corresponding analysis. |
| `UbAccessType` | `INTEGER` | Access category code: 1 SIMT read, 2 SIMT write, 3 SIMD read, or 4 SIMD write in the current enumeration. |
| `SimtDataCache` | `BOOLEAN` | Flag identifying the SIMT data-cache path, encoded as 0 or 1. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 3. AICore Utilization

Data is available; visualization is not currently available.

`AiCoreOccupancy` gives the first-to-last instruction interval for each recorded
core component. Gaps within the interval are included. The associated
`aicore_utilization.json` uses the component span divided by the overall
first-to-last span as its coverage percentage. This measures time coverage,
not the fraction of cycles during which a pipeline executes work.

**Related tables:** [AiCoreOccupancy](#table-aicoreoccupancy), [ExecutedInstructions](#table-executedinstructions), [CoreTypes](#table-coretypes).

[Implementation](../../../npusim/prof/src/frontend/tracing/chrome_tracing_aicore_occupancy.py).

<a id="table-aicoreoccupancy"></a>

#### AiCoreOccupancy

Database view exported as CSV.

One first-to-last recorded instruction span per core/component. Gaps inside the span are included;
this is not pipeline busy time.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `TickStart` | not declared | Start of the recorded interval, in simulator ticks. |
| `TickEnd` | not declared | End of the recorded interval, in simulator ticks. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 4. Sub-Core Utilization

Data is available; visualization is not currently available.

`UnitUtilization` records changes in simultaneous pipeline activity. `Util` is
a fraction: the number of distinct active pipeline types divided by the number
configured for this component. The current AIC set contains CUBE, FIXP, MTE1,
and MTE2; the AIV set contains MTE2, MTE3, and PUSHQ. With smart-pipe analysis,
only the relevant EXEC subqueue records contribute. This differs from both
component time coverage and queue depth.

**Related tables:** [UnitUtilization](#table-unitutilization), [ExecutedInstructions](#table-executedinstructions), [CoreTypes](#table-coretypes), [SubQueueTypes](#table-subqueuetypes).

[Implementation](../../../npusim/prof/src/backend/analyzers/david/unit_utilization_analyzer.py).

<a id="table-unitutilization"></a>

#### UnitUtilization

Database table.

Activity state changes for a core/component. In the Ascend950 analyzer, the denominator is four
configured pipelines for AIC and three for AIV.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Tick` | `INTEGER` | Simulator tick at which this event or state is recorded. |
| `Util` | `REAL` | Fraction of configured pipeline types simultaneously active at this tick; not queue depth or a percentage. |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 6. Speed-of-Light

This feature is not currently available. No supported result dataset is documented for it.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 7. Roofline

This feature is not currently available.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 11. Pipelines Utilization

`PipesUtilization` describes busy time per core, component, and instruction
queue. The analyzer merges selected instruction intervals and divides the union
length by kernel elapsed ticks. Wait and marker instructions are filtered
according to the queue rules.

The CSV stores percentages. `summary.json` converts these to fractions in
`pipe_utilization.pipeline_util_summary` and reports mean/min/max. Its optional
`per_core` array does not contain explicit core IDs; use the CSV for the mapping.
`PipeUtilizationHist` is the mean by queue and component type across cores.
The highest mean utilization identifies the summary's dominant pipeline, but
utilization alone does not prove a bottleneck cause.

**Related tables:** [PipesUtilization](#table-pipesutilization), [PipeUtilizationHist](#table-pipeutilizationhist), [ExecutedInstructions](#table-executedinstructions), [KernelInfo](#table-kernelinfo), [InstrQueueTypes](#table-instrqueuetypes), [CoreTypes](#table-coretypes).

[Implementation](../../../npusim/prof/src/backend/analyzers/david/pipe_utilization_analyzer.py).

<a id="table-pipesutilization"></a>

#### PipesUtilization

Database table.

One aggregate per core, core component, and queue grouping. Selected instruction intervals are
merged before dividing their union length by kernel elapsed ticks.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `InstrQueueTypeId` | `INTEGER` | Queue grouping identifier; joins to `InstrQueueTypes.InstrQueueTypeId`. |
| `PipeUtilization` | `REAL` | Pipeline busy-time percentage, from 0 to 100 under normal recorded bounds; the JSON summary converts it to a fraction. |

<a id="table-pipeutilizationhist"></a>

#### PipeUtilizationHist

Database view exported as CSV.

Mean pipeline utilization across recorded core IDs, grouped by queue name and core component type.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `PipeName` | `VARCHAR(20)` | Queue/group name from `InstrQueueTypes`. |
| `CoreName` | `VARCHAR(20)` | Core component name from `CoreTypes`. |
| `Utilization` | not declared | Arithmetic mean of `PipesUtilization.PipeUtilization`, in percent. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 1. Instruction Execution Timeline

The instruction timeline is built from the dynamic execution stream. Main
trace files are named `core_<id>_tracing_report_<chunk>.json` inside the archive.
Metadata names the tracks, duration events carry execution intervals, and flow
events show available synchronization relationships. An execution record can
have a PC even when source files and static disassembly are unavailable.

The tables below supply the instruction stream, its timing and execution
context, and parameters attached to individual instruction events. These include
DMA processed bytes and layout, matrix dimensions, fixpipe modes, and marked
execution regions. Metrics
with their own feature sections, such as vector utilization and bank conflicts,
are linked from those sections.

`--smart-pipes` enables subqueue classification and an additional
`core_<id>_smart_pipe_report_<chunk>.json`. It also changes selected timing and
unit-activity calculations. `IssueQueueUtilization.Util` and
`ExecQueueUtilization.Util` are queue depths, not percentages.

Static source/assembly mapping, call-stack enrichment, and warp-utilization
reports are unavailable in this workflow without an object file.

**Related tables:** [ExecutedInstructions](#table-executedinstructions), [DispatchTime](#table-dispatchtime), [SubQueueTypes](#table-subqueuetypes), [IssueQueueUtilization](#table-issuequeueutilization), [ExecQueueUtilization](#table-execqueueutilization), [PipeDependency](#table-pipedependency), [RegionNames](#table-regionnames), [Regions](#table-regions), [QueueFullEvents](#table-queuefullevents), [ICacheEvents](#table-icacheevents), [ICacheRefillEvents](#table-icacherefillevents), [SprWriteEvents](#table-sprwriteevents), [SprInfoPerInstr](#table-sprinfoperinstr), [UnitsUsageMetrics](#table-unitsusagemetrics), [KernelInfo](#table-kernelinfo), [CoreTypes](#table-coretypes), [InstrTypes](#table-instrtypes), [InstrQueueTypes](#table-instrqueuetypes), [AnalysisState](#table-analysisstate), [DmaMovProcessedBytes](#table-dmamovprocessedbytes), [DmaMovSimpleParams](#table-dmamovsimpleparams), [DmaMovMultiParams](#table-dmamovmultiparams), [DmaMovLoad2dParams](#table-dmamovload2dparams), [DmaMovLoad3dParams](#table-dmamovload3dparams), [DmaMovNdDmaParams](#table-dmamovnddmaparams), [MmadParams](#table-mmadparams), [FixpParams](#table-fixpparams).

[Implementation](../../../npusim/prof/src/frontend/tracing/chrome_tracing_default.py).

<a id="table-executedinstructions"></a>

#### ExecutedInstructions

Database table.

One recorded dynamic instruction execution per row. This is the central join target for
instruction-level analysis. The exclusion/classification fields below are collector-provided
metadata, rather than performance measurements.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Identifier of this dynamic instruction execution; referenced by per-instruction analysis tables. |
| `SourceInstrAddr` | `INTEGER` | Static instruction address in bytes from the recorded execution stream; available even when source/disassembly tables are empty. |
| `ExecInstrTickStart` | `INTEGER` | Instruction start tick. |
| `ExecInstrTickEnd` | `INTEGER` | Instruction end tick; subtract the start to obtain its recorded duration. |
| `ExecInstrName` | `VARCHAR(100)` | Recorded instruction mnemonic. |
| `ExecInstrParams` | `VARCHAR(100)` | Collector-formatted instruction operand/parameter text; not the structured `ExtendParams` object. |
| `InstrTypeId` | `INTEGER` | Instruction pipeline/type identifier; joins to `InstrTypes.InstrTypeId`. |
| `ExecInstrCoreId` | `INTEGER` | Core identifier for this execution; combine with `CoreTypeId`. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `ExtendParams` | `TEXT` | JSON object of semantic instruction parameters. Keys depend on instruction kind; missing keys mean not applicable. See the parameter accessor linked at the start of this reference. |
| `SourceInstrEncoding` | `VARCHAR(24)` | Instruction encoding as hexadecimal text, when supplied by the collector. |
| `ExecInstrIsWait` | `BOOLEAN` | Collector flag identifying a wait instruction, encoded as 0 or 1. |
| `ExecInstrIsSynchronization` | `BOOLEAN` | Collector flag identifying a synchronization instruction, encoded as 0 or 1. |
| `ExecInstrIsDurationExcluded` | `BOOLEAN` | Collector flag marking an instruction for exclusion from applicable duration calculations, encoded as 0 or 1. |
| `ExecInstrVfClass` | `INTEGER` | Collector classification code for the instruction's VF role; preserve the code and interpret it with the producing contract version. |
| `ExecInstrVfSimtClass` | `INTEGER` | Collector classification code for the instruction's SIMT VF role; preserve the code and interpret it with the producing contract version. |

<a id="table-dispatchtime"></a>

#### DispatchTime

Database table.

Recorded dispatch timing for a dynamic instruction. Execution start/end remain in
`ExecutedInstructions`.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `DispatchTimeTick` | `INTEGER` | Tick when the instruction is dispatched into its pipeline queue. |

<a id="table-subqueuetypes"></a>

#### SubQueueTypes

Database table.

Assigns a subqueue stage to an execution record for supported pipelines.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `SubQueueType` | `INTEGER` | Subqueue stage code: 1 EXEC, 2 FLAG, or 3 PUSH_PB in the current analyzer enumeration. |

<a id="table-issuequeueutilization"></a>

#### IssueQueueUtilization

Database table.

Queue-depth state changes for each core/component and instruction pipeline, derived from dispatch,
start, and retire events.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Tick` | `INTEGER` | Simulator tick at which this event or state is recorded. |
| `Util` | `REAL` | Number of instructions currently in the issue queue after this state transition; not a utilization percentage. |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `InstrTypeId` | `INTEGER` | Instruction pipeline/type identifier; joins to `InstrTypes.InstrTypeId`. |

<a id="table-execqueueutilization"></a>

#### ExecQueueUtilization

Database table.

Queue-depth state changes for each core/component and instruction pipeline, derived from dispatch,
start, and retire events.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `Tick` | `INTEGER` | Simulator tick at which this event or state is recorded. |
| `Util` | `REAL` | Number of instructions currently in the execution queue after this state transition; not a utilization percentage. |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `InstrTypeId` | `INTEGER` | Instruction pipeline/type identifier; joins to `InstrTypes.InstrTypeId`. |

<a id="table-pipedependency"></a>

#### PipeDependency

Database table.

Endpoints of reconstructed synchronization flows. Pair entries by `EventId` within the relevant
context; `ExecInstrId` identifies the endpoint instruction.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `EventId` | `INTEGER` | Reconstructed flow identifier shared by the flow endpoints; not a reference to another event table's primary key. |
| `EventName` | `VARCHAR(50)` | Readable synchronization description, such as a consumer pipeline awaiting a producer event. |
| `FlowEnd` | `INTEGER` | 0 for a flow start, 1 for a flow end. |
| `CategoryId` | `INTEGER` | Dependency category: 1 flag, 2 intra-block, 3 buffer, or 4 FFTS synchronization in the current enumeration. |

<a id="table-regionnames"></a>

#### RegionNames

Database table.

Name dictionary for reconstructed execution regions.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `RegionNameId` | `INTEGER` | Region name identifier; joins to `RegionNames.RegionNameId`. |
| `RegionName` | `VARCHAR(20)` | Region label, such as a VF or marked code-region name. |

<a id="table-regions"></a>

#### Regions

Database table.

Execution intervals reconstructed from recorded markers and added to the
instruction trace. Rows are produced only when matching region markers are
present. Scalar DFX and SIMD custom-region analysis work without an object file;
SIMT custom-region analysis is not enabled in the current workflow.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `RegionNameId` | `INTEGER` | Region name identifier; joins to `RegionNames.RegionNameId`. |
| `RegionStart` | `INTEGER` | Region start tick. |
| `RegionEnd` | `INTEGER` | Region end tick. |
| `RegionCoreId` | `INTEGER` | Core identifier owning the region. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `RegionTypeId` | `INTEGER` | Region classification code emitted by the region analyzer, based on its queue/group enumeration. |
| `InstrQueueTypeId` | `INTEGER` | Queue grouping identifier; joins to `InstrQueueTypes.InstrQueueTypeId`. |
| `WarpId` | `INTEGER` | Warp identifier within the associated execution region or block. |

<a id="table-queuefullevents"></a>

#### QueueFullEvents

Database table.

Collector-provided queue-full intervals associated with an instruction. These events are distinct
from aggregated queue-full stall counters.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `EventId` | `INTEGER` | Identifier of the event row within this table. |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `EventBeginTick` | `INTEGER` | Start of the event, in simulator ticks. |
| `EventEndTick` | `INTEGER` | End of the event, in simulator ticks. |

<a id="table-icacheevents"></a>

#### ICacheEvents

Database table.

Recorded instruction-cache access events. The cache-event type distinguishes scalar and vector fetch
contexts.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ICacheEventId` | `INTEGER` | Identifier of this instruction-cache event. |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `EventTimeTick` | `INTEGER` | Tick of the cache access. |
| `SourceInstrAddr` | `INTEGER` | Static instruction address in bytes from the recorded execution stream; available even when source/disassembly tables are empty. |
| `EventSize` | `INTEGER` | Size of the recorded cache access, in bytes. |
| `HitStatus` | `BOOLEAN` | Recorded hit/miss flag: 1 for a hit, 0 for a miss. |
| `ICacheEventType` | `INTEGER` | Instruction-cache event context: 1 scalar or 2 vector in the current enumeration. |

<a id="table-icacherefillevents"></a>

#### ICacheRefillEvents

Database table.

Instruction-cache refill intervals used by the summary and trace reports.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `EventId` | `INTEGER` | Identifier of the event row within this table. |
| `SourceInstrAddr` | `INTEGER` | Static instruction address in bytes from the recorded execution stream; available even when source/disassembly tables are empty. |
| `ICacheEventType` | `INTEGER` | Instruction-cache refill context: 1 scalar or 2 vector in the current enumeration. |
| `CacheLineSize` | `INTEGER` | Refill/cache-line size in bytes. |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `EventBeginTick` | `INTEGER` | Start of the event, in simulator ticks. |
| `EventEndTick` | `INTEGER` | End of the event, in simulator ticks. |

<a id="table-sprwriteevents"></a>

#### SprWriteEvents

Database table.

Collector-provided special-purpose register writes at a core/component tick.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `EventTick` | `INTEGER` | Simulator tick at which the event occurs. |
| `SprName` | `VARCHAR(20)` | Special-purpose register name. |
| `SprValue` | `VARCHAR(20)` | Recorded special-purpose register value as text; preserve its representation. |

<a id="table-sprinfoperinstr"></a>

#### SprInfoPerInstr

Database table.

Special-purpose register values associated with dynamic instructions by register-state analysis.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `SprName` | `VARCHAR(20)` | Special-purpose register name. |
| `SprValue` | `VARCHAR(20)` | Recorded special-purpose register value as text; preserve its representation. |

<a id="table-unitsusagemetrics"></a>

#### UnitsUsageMetrics

Database table.

Coverage of execution units for each static instruction address.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `SourceInstrAddr` | `INTEGER` | Static instruction address in bytes from the recorded execution stream; available even when source/disassembly tables are empty. |
| `UniqueSubCoresUsed` | `INTEGER` | Number of distinct recorded core/component execution contexts that executed this address. |
| `UniqueWarpsUsed` | `INTEGER` | Number of distinct recorded warp identities for this address when calculated; the current analyzer leaves this field NULL. |

**Instruction parameters**

The following tables supply parameters attached to individual instruction events
in the trace. They join to `ExecutedInstructions` through `ExecInstrId` and cover
DMA layout, processed byte counts and transfer rates, matrix dimensions, and
fixpipe modes. Architecture-level analysis can also aggregate these values.

Burst and stride parameters retain the originating instruction's units. Explicit
`ProcessedBytes` fields are byte counts. DMA `CacheHit` records whether the
analyzer has seen the chosen address before. Several MMAD and fixpipe fields
are currently defaults; a row does not establish that every hardware setting
was recovered.

<a id="table-dmamovprocessedbytes"></a>

#### DmaMovProcessedBytes

Database table.

Per-instruction transfer volume and rate. The current DMA analyzer records `CacheHit` by remembering
previously seen source addresses, or destination addresses when a source is absent.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ProcessedBytes` | `INTEGER` | Number of bytes processed by the instruction according to the corresponding analysis. |
| `MemoryTraffic` | `REAL` | `ProcessedBytes / instruction_duration_seconds / 2^30`; a per-instruction transfer rate in binary gigabytes per second, not a byte count. |
| `CacheHit` | `BOOLEAN` | 1 when the chosen address has already been encountered by this analyzer instance, otherwise 0; an address-reuse heuristic rather than a measured cache hit. |

<a id="table-dmamovsimpleparams"></a>

#### DmaMovSimpleParams

Database table.

Burst and stride parameters extracted from supported simple DMA instructions.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `BurstLength` | `INTEGER` | Burst length parameter from `ExtendParams.burst_len`, in the source instruction's units. |
| `BurstNumber` | `INTEGER` | Number of bursts from `ExtendParams.burst_number`. |
| `SrcStride` | `INTEGER` | Source stride parameter from `ExtendParams.src_stride`, in the source instruction's units. |
| `DstStride` | `INTEGER` | Destination stride parameter from `ExtendParams.dst_stride`, in the source instruction's units. |
| `SubBlockId` | `INTEGER` | Sub-block selector when provided by the instruction parameters. |

<a id="table-dmamovmultiparams"></a>

#### DmaMovMultiParams

Database table.

Dimensions for supported multi-dimensional ND/DN-to-NZ DMA instructions.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `N` | `INTEGER` | N dimension parameter copied from `ExtendParams.n`. |
| `D` | `INTEGER` | D dimension parameter copied from `ExtendParams.d`. |

<a id="table-dmamovload2dparams"></a>

#### DmaMovLoad2dParams

Database table.

Starting coordinates and step parameters for supported 2D load instructions.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `MStartPosition` | `INTEGER` | Starting position in the M dimension from `m_start_pos`. |
| `KStartPosition` | `INTEGER` | Starting position in the K dimension from `k_start_pos`. |
| `MStep` | `INTEGER` | M-dimension step/extent parameter from `m_step`, in instruction-defined units. |
| `KStep` | `INTEGER` | K-dimension step/extent parameter from `k_step`, in instruction-defined units. |

<a id="table-dmamovload3dparams"></a>

#### DmaMovLoad3dParams

Database table.

Dimensions and destination descriptor for supported 3D load instructions.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `MStep` | `INTEGER` | M-dimension step/extent parameter from `m_step`, in instruction-defined units. |
| `KStep` | `INTEGER` | K-dimension step/extent parameter from `k_step`, in instruction-defined units. |
| `Dst` | `VARCHAR(100)` | Destination memory name copied from `ExtendParams.dst_mem`. |

<a id="table-dmamovnddmaparams"></a>

#### DmaMovNdDmaParams

Database table.

Loop and padding parameters for supported ND DMA instructions. Values are instruction parameters
rather than elapsed-time metrics.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `Loop0Size` | `INTEGER` | Size of loop dimension 0, copied from `ExtendParams.loop0_size`. |
| `Loop1Size` | `INTEGER` | Size of loop dimension 1, copied from `ExtendParams.loop1_size`. |
| `Loop2Size` | `INTEGER` | Size of loop dimension 2, copied from `ExtendParams.loop2_size`. |
| `Loop3Size` | `INTEGER` | Size of loop dimension 3, copied from `ExtendParams.loop3_size`. |
| `Loop4Size` | `INTEGER` | Size of loop dimension 4, copied from `ExtendParams.loop4_size`. |
| `Loop0LpSize` | `INTEGER` | Left-padding size parameter for loop dimension 0. |
| `Loop0RpSize` | `INTEGER` | Right-padding size parameter for loop dimension 0. |

<a id="table-mmadparams"></a>

#### MmadParams

Database table.

Per-MMAD/MMAD_MX matrix parameters. The current Ascend950 analyzer populates dimensions, data types,
and byte counts from `ExtendParams`; several other columns are retained as defaults.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `M` | `INTEGER` | M dimension of the matrix operation. |
| `K` | `INTEGER` | K reduction dimension of the matrix operation. |
| `N` | `INTEGER` | N dimension of the matrix operation. |
| `MatrixADtype` | `VARCHAR(16)` | Data type of matrix A, when provided. |
| `MatrixBDtype` | `VARCHAR(16)` | Data type of matrix B, when provided. |
| `MatrixCDtype` | `VARCHAR(16)` | Data type of matrix C, when provided. |
| `EnabledMode` | `VARCHAR(16)` | Matrix operation mode descriptor; currently NULL in the Ascend950 analyzer. |
| `MatrixAL0AAddress` | `INTEGER` | Matrix A address in L0A; currently written as 0 by this analyzer, not recovered from the input. |
| `MatrixBL0BAddress` | `INTEGER` | Matrix B address in L0B; currently written as 0 by this analyzer. |
| `MatrixCAddress` | `INTEGER` | Matrix C address; currently written as 0 by this analyzer. |
| `HwChecksUnitFlag` | `BOOLEAN` | Hardware unit-flag check setting; currently NULL in this analyzer. |
| `HwSetsUnitFlag` | `BOOLEAN` | Hardware unit-flag set setting; currently NULL in this analyzer. |
| `GEMVModeEnable` | `BOOLEAN` | GEMV mode flag; currently written as false by this analyzer. |
| `MatrixCInBiasTableBuffer` | `BOOLEAN` | Matrix C bias-buffer flag; currently written as false by this analyzer. |
| `MatrixCInitVal` | `BOOLEAN` | Matrix C initialization flag; currently written as false by this analyzer. |
| `MatrixAProcessedBytes` | `INTEGER` | Matrix A byte count from semantic parameters; defaults to 0 if absent. |
| `MatrixBProcessedBytes` | `INTEGER` | Matrix B byte count from semantic parameters; defaults to 0 if absent. |
| `MatrixCProcessedBytes` | `INTEGER` | Matrix C byte count from semantic parameters; defaults to 0 if absent. |

<a id="table-fixpparams"></a>

#### FixpParams

Database table.

Per-fixpipe dimensions, conversion modes, and transfer volume. The current Ascend950 analyzer
decodes selected pre/post modes and retains defaults for unsupported legacy parameters.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `N` | `INTEGER` | N dimension of the fixpipe operation. |
| `M` | `INTEGER` | M dimension of the fixpipe operation. |
| `L2CacheCtrlMode` | `VARCHAR(50)` | L2 cache-control mode descriptor; currently NULL in this analyzer. |
| `HwChecksUnitFlag` | `BOOLEAN` | Hardware unit-flag check setting; currently false in this analyzer. |
| `HwSetsUnitFlag` | `BOOLEAN` | Hardware unit-flag set setting; currently false in this analyzer. |
| `PreQuantMode` | `VARCHAR(100)` | Readable pre-quantization/conversion mode decoded from `quant_pre`; unknown codes appear as `Unknown(code)`. |
| `PreReluMode` | `VARCHAR(20)` | Readable pre-ReLU mode decoded from `relu_pre`. |
| `PreClipReluMode` | `VARCHAR(30)` | Readable pre-clip/ReLU mode decoded from `clip_pre`. |
| `F32ChannelSplitEnable` | `BOOLEAN` | FP32 channel-split flag; currently false in this analyzer. |
| `PostClipReluMode` | `VARCHAR(30)` | Readable post-clip/ReLU mode decoded from `clip_post`. |
| `PostReluMode` | `VARCHAR(20)` | Readable post-ReLU mode decoded from `relu_post`. |
| `NZ2NDEnable` | `BOOLEAN` | NZ-to-ND layout conversion flag; currently false in this analyzer. |
| `NZ2DNEnable` | `BOOLEAN` | NZ-to-DN layout conversion flag; currently false in this analyzer. |
| `C0PaddingEnable` | `BOOLEAN` | C0 padding flag; currently NULL in this analyzer. |
| `DstMode` | `VARCHAR(50)` | Destination mode descriptor; currently NULL in this analyzer. |
| `DstUBMask` | `INTEGER` | Destination UB selection bitmask, with bit 0 for AIV0 and bit 1 for AIV1; currently written as 0 by this analyzer. |
| `ProcessedBytes` | `INTEGER` | Output byte count from semantic parameters; defaults to 0 if absent. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 7. SIMD VF Pipelines

Under the current convention, SIMD VF pipelines group instructions whose
`ExecInstrName` begins with `VF` on the `PUSHQ` pipeline. These records come from
`ExecutedInstructions`; resolve the pipeline through
`ExecutedInstructions.InstrTypeId` and `InstrTypes.InstrTypeName`.

Each matching record supplies its core/component context, instruction parameters,
and start/end ticks. The interval from `ExecInstrTickStart` to
`ExecInstrTickEnd` represents the recorded VF instruction on the pipeline.

**Related tables:** [ExecutedInstructions](#table-executedinstructions),
[InstrTypes](#table-instrtypes), [CoreTypes](#table-coretypes).

[Timeline generation](../../../npusim/prof/src/frontend/tracing/chrome_tracing_default.py).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 8. SIMD IPC

Enable the VF IPC analyzers with `--vec-ipc`. The ordinary single-chip
`npusim report` path supplies this backend flag. SIMD has scalar, execution,
and load/store IPC components, measured in instructions per cycle.

Call-level IPC, IPC attached to inner instructions, and sliding-window IPC are
different scopes. `--sliding-window-vec` controls the dynamic window, with a
default of eight instructions. `IPCAsmMetrics` combines available IPC records;
it can have rows even when the unrelated source-dependent `AsmMetrics` view is
empty. The common IPC view can also contain scalar and SIMT components.

`summary.aiv_vector_instructions` reports arithmetic means of call-level IPC
components. VF JSON similarly averages calls in each inferred function group;
these are not duration-weighted kernel IPC values. Its `instr_profile` describes
the longest call in a group, and `variance_ratio` is a max/min duration ratio,
not statistical variance.

**Related tables:** [VfIPC](#table-vfipc), [VfIPCInside](#table-vfipcinside), [VfIPCDynamic](#table-vfipcdynamic), [VfIPCDynamicView](#table-vfipcdynamicview), [IPCAsmMetrics](#table-ipcasmmetrics), [ExecutedInstructions](#table-executedinstructions), [KernelInfo](#table-kernelinfo), [InstrTypes](#table-instrtypes).

[Implementation](../../../npusim/prof/src/backend/analyzers/david/vf_ipc_analyzer.py).

<a id="table-vfipc"></a>

#### VfIPC

Database table.

IPC components attached to each SIMD VF call. The inner-instruction table associates contextual IPC
with that instruction; it does not represent extra instruction executions.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ScalarIPC` | `REAL` | Scalar instruction IPC component, in instructions per cycle. |
| `ExecIPC` | `REAL` | Vector execution instruction IPC component, in instructions per cycle. |
| `LdStIPC` | `REAL` | Load/store instruction IPC component, in instructions per cycle. |

<a id="table-vfipcinside"></a>

#### VfIPCInside

Database table.

IPC components attached to each instruction inside a SIMD VF. The inner-instruction table associates
contextual IPC with that instruction; it does not represent extra instruction executions.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ScalarIPC` | `REAL` | Scalar instruction IPC component, in instructions per cycle. |
| `ExecIPC` | `REAL` | Vector execution instruction IPC component, in instructions per cycle. |
| `LdStIPC` | `REAL` | Load/store instruction IPC component, in instructions per cycle. |

<a id="table-vfipcdynamic"></a>

#### VfIPCDynamic

Database table.

Windowed SIMD IPC components, associated with an inner instruction execution.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `WindowStartTick` | `INTEGER` | Start tick of the IPC analysis window. |
| `ScalarIPC` | `REAL` | Scalar instruction IPC component, in instructions per cycle. |
| `ExecIPC` | `REAL` | Vector execution instruction IPC component, in instructions per cycle. |
| `LdStIPC` | `REAL` | Load/store instruction IPC component, in instructions per cycle. |

<a id="table-vfipcdynamicview"></a>

#### VfIPCDynamicView

Database view exported as CSV.

Windowed SIMD IPC with core ID and component resolved from `ExecutedInstructions`. The view omits
the instruction ID from its output.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `WindowStartTick` | `INTEGER` | Start tick of the IPC analysis window. |
| `ScalarIPC` | `REAL` | Scalar instruction IPC component, in instructions per cycle. |
| `ExecIPC` | `REAL` | Vector execution instruction IPC component, in instructions per cycle. |
| `LdStIPC` | `REAL` | Load/store instruction IPC component, in instructions per cycle. |

<a id="table-ipcasmmetrics"></a>

#### IPCAsmMetrics

Database view exported as CSV.

Combined IPC view over scalar, SIMD call/inner, and SIMT call/inner records using `UNION ALL`.
Components not applicable to a contributing source are filled with 0.0; these zeros are part of the
view construction.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ScalarIPC` | `REAL` | Scalar instruction IPC component, in instructions per cycle. |
| `ExecIPC` | not declared | Vector execution instruction IPC component, in instructions per cycle. |
| `LdStIPC` | not declared | Load/store instruction IPC component, in instructions per cycle. |
| `BranchIPC` | not declared | SIMT branch instruction IPC component, in instructions per cycle. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 9. SIMD Vector Utilization

For supported vector instructions, `VectorUtilizations` uses the semantic
`processed_bytes` value in `ExecutedInstructions.ExtendParams`. The current
utilization is `ProcessedBytes / 256 * 100`, relative to the default 256-byte
vector length. `ProcessedElements` is currently left NULL.

This per-instruction byte-volume measure is distinct from execution IPC and
pipeline busy time. Missing semantic byte counts cause the instruction to be
omitted from this analysis.

**Related tables:** [VectorUtilizations](#table-vectorutilizations), [ExecutedInstructions](#table-executedinstructions).

[Implementation](../../../npusim/prof/src/backend/analyzers/vector_utilization_analyzer.py).

<a id="table-vectorutilizations"></a>

#### VectorUtilizations

Database table.

Processed vector volume for supported instructions. In the current analyzer, vector utilization is
based on semantic `processed_bytes`, and `ProcessedElements` is left NULL.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ProcessedBytes` | `INTEGER` | Number of bytes processed by the instruction according to the corresponding analysis. |
| `ProcessedElements` | `INTEGER` | Processed element count when available; currently NULL in this analyzer. |
| `VectorUtilization` | `REAL` | `ProcessedBytes / 256 * 100` in the current analyzer, expressed as a percentage of the default 256-byte vector length. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 10. SIMD Bank Conflicts (Scatter/Gather)

Data is available; visualization is not currently available.

Collected UB address records in `SgUbRwAcesses` are joined with dynamic
instruction names through `SharedPatterns`. The bank-conflict analyzer processes
supported gather/scatter and shared-memory instructions and writes
`UBBankConflicts`. These are per-instruction read/write conflict results.
Cross-instruction conflicts are a separate dataset described later.

**Related tables:** [SgUbRwAcesses](#table-sgubrwacesses), [SharedPatterns](#table-sharedpatterns), [UBBankConflicts](#table-ubbankconflicts), [ExecutedInstructions](#table-executedinstructions).

[Implementation](../../../npusim/prof/src/backend/analyzers/david/shared_bank_conflicts_analyzer.py).

<a id="table-sgubrwacesses"></a>

#### SgUbRwAcesses

Database table.

Collector-provided UB address records used by the shared-access pattern view. The spelling `Acesses`
is the actual exported table name.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `AccessedAddress` | `INTEGER` | Accessed memory address in bytes within the recorded memory scope. |

<a id="table-sharedpatterns"></a>

#### SharedPatterns

Database view exported as CSV.

UB address records joined with the mnemonic of their owning dynamic instruction.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `InstrName` | `VARCHAR(100)` | Recorded instruction mnemonic from `ExecutedInstructions.ExecInstrName`. |
| `AccessedAddress` | `INTEGER` | Accessed memory address in bytes within the recorded memory scope. |

<a id="table-ubbankconflicts"></a>

#### UBBankConflicts

Database table.

Per-instruction UB read/write bank-conflict results.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `UBBankConflictId` | `INTEGER` | Identifier of this bank-conflict result row. |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ReadConflicts` | `INTEGER` | Recorded or derived UB bank-conflict count for reads. |
| `WriteConflicts` | `INTEGER` | Recorded or derived UB bank-conflict count for writes. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 11. SIMD Stall Sampling

Data is available; visualization is not currently available.

Enable aggregation with `--simd-sampling`. `SIMDSamplingStats` and
`SIMDStallReasonTypes` are collected inputs; `SIMDStallsByAddr` aggregates their
reason/count pairs using PCs directly from `ExecutedInstructions`.

This path works without static source mappings. The source-line counterpart
`SIMDStallsByLine` remains empty in the current workflow. Legacy
`SamplingStats` and `CollectedSamples` are not inputs to this analysis.

**Related tables:** [SIMDStallReasonTypes](#table-simdstallreasontypes), [SIMDSamplingStats](#table-simdsamplingstats), [SIMDStallsByAddr](#table-simdstallsbyaddr), [ExecutedInstructions](#table-executedinstructions).

[Implementation](../../../npusim/prof/src/backend/analyzers/david/simd_sampling_analyzer.py).

<a id="table-simdstallreasontypes"></a>

#### SIMDStallReasonTypes

Database table.

Dictionary of recorded SIMD stall reason codes.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `StallReasonId` | `INTEGER` | Stall reason identifier used by `SIMDSamplingStats`. |
| `StallReasonName` | `VARCHAR(20)` | Readable stall reason name. |

<a id="table-simdsamplingstats"></a>

#### SIMDSamplingStats

Database table.

Recorded SIMD stall counters per dynamic instruction and reason; the sampling analyzer aggregates
these by static address and source line.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `StallReasonId` | `INTEGER` | Reason identifier; joins to `SIMDStallReasonTypes.StallReasonId`. |
| `StallCount` | `INTEGER` | Recorded count for this instruction and stall reason. |

<a id="table-simdstallsbyaddr"></a>

#### SIMDStallsByAddr

Database table.

JSON stall-count aggregates for each static instruction address.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `SourceInstrAddr` | `INTEGER` | Static instruction address in bytes from the recorded execution stream; available even when source/disassembly tables are empty. |
| `StallsJson` | `TEXT` | JSON object mapping SIMD stall reason names to aggregated recorded counts. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 17. MTE & Memory Utilization

Data is available; visualization is not currently available.

`MemoryRWAccesses` contains collected memory events, including optional access
sizes and strides. With `--memory-utilization`, two analyses produce derived data:

- `MemoryUtilizationStates` estimates memory usage over time from write-to-read
  lifetimes, using four bytes per tracked address.
- `MemoryHeatmapLayout` defines a spatial grid for each buffer instance, and
  `MemoryHeatmapCells` aggregates read/write address coverage in that grid.

The time-state analyzer and heatmap use different counting rules. The heatmap
expands supported ranges and strides and counts address coverage rather than
raw bytes or events. It does not describe peak live allocation.

The current memory stream can contain only the low 32 bits of an instruction ID.
These analyses mask IDs when joining memory events to
[ExecutedInstructions](#table-executedinstructions) to resolve instruction context.

**Related tables:** [MemoryRWAccesses](#table-memoryrwaccesses),
[MemoryUtilizationStates](#table-memoryutilizationstates),
[MemoryHeatmapLayout](#table-memoryheatmaplayout),
[MemoryHeatmapCells](#table-memoryheatmapcells).

[Memory-state analysis](../../../npusim/prof/src/backend/analyzers/david/memory_utilization_analyzer.py),
[heatmap analysis](../../../npusim/prof/src/backend/analyzers/david/memory_heatmap_analyzer.py).

<a id="table-memoryrwaccesses"></a>

#### MemoryRWAccesses

Database table.

Collected memory access records. A row can encode a range or strided access rather than a single
word. Older contract versions can omit `Size` and `Step`. In the current helper layout, instruction
IDs in this table contain only the low 32 bits, so a direct equality join to the full
`ExecutedInstructions.ExecInstrId` is not sufficient for all records.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `AccessedAddress` | `INTEGER` | Accessed memory address in bytes within the recorded memory scope. |
| `AccessMode` | `VARCHAR(1)` | Access direction, `R` for read or `W` for write. |
| `AccessTime` | `INTEGER` | Simulator tick of the memory access. |
| `MemoryType` | `INTEGER` | Recorded memory scope identifier: helper IDs 1 UB, 2 L0A, 3 L0B, 4 L0C, and 5 L1; do not interpret this as `CoreTypeId`. |
| `ExecInstrId` | `INTEGER` | Owning instruction identifier in the memory stream; the current heatmap analyzer resolves it by matching low 32-bit instruction IDs. Unmatched whole-buffer events are excluded from traffic heatmaps. |
| `CoreId` | `INTEGER` | Core identifier recorded by the memory stream; can be 0 throughout. The heatmap resolves the executing component from matching instructions. |
| `Size` | `INTEGER` | Size/count of the access payload in bytes. With `Step` greater than 1, the heatmap interprets this as a count of strided byte touches. Missing/nonpositive size is treated as one byte by that analyzer. |
| `Step` | `INTEGER` | Byte stride between touched addresses; missing/nonpositive values are treated as 1 by the heatmap analyzer. |

<a id="table-memoryutilizationstates"></a>

#### MemoryUtilizationStates

Database table.

Buffer usage state over time, keyed by `(CoreId, Tick, MemoryType)`. This describes usage state,
whereas heatmap cells aggregate spatial access coverage.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `Tick` | `INTEGER` | Simulator tick at which this event or state is recorded. |
| `UtilizedBytes` | `INTEGER` | Estimated utilized bytes at this tick. The current analyzer uses matched write-to-read lifetimes and four bytes per tracked address; it does not expand `Size`/`Step` ranges like the heatmap does. |
| `MemoryType` | `INTEGER` | Recorded memory scope identifier: helper IDs 1 UB, 2 L0A, 3 L0B, 4 L0C, and 5 L1; do not interpret this as `CoreTypeId`. |

<a id="table-memoryheatmaplayout"></a>

#### MemoryHeatmapLayout

Database table.

One spatial grid per buffer instance, keyed by `(CoreId, CoreTypeId, MemoryType)`. The cell table
references the same key.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Core ID used for this memory view; the current single-chip helper memory scope uses 0. |
| `CoreTypeId` | `INTEGER` | Component owning the represented buffer, resolved through `CoreTypes`; this can differ from the component issuing an access. |
| `MemoryType` | `INTEGER` | Recorded memory scope identifier: helper IDs 1 UB, 2 L0A, 3 L0B, 4 L0C, and 5 L1; do not interpret this as `CoreTypeId`. |
| `MemoryName` | `VARCHAR(20)` | Readable buffer name, such as UB, L1, L0A, L0B, or L0C; unknown scopes use `TYPE_<id>`. |
| `Width` | `INTEGER` | Grid width in cells. |
| `Height` | `INTEGER` | Grid height in cells. |
| `CellSize` | `INTEGER` | Address span covered by each grid cell, in bytes. |
| `BaseAddress` | `INTEGER` | First byte address represented by the grid. |
| `DeclaredSize` | `INTEGER` | Declared buffer capacity in bytes, when known. |
| `OutsideDeclared` | `BOOLEAN` | 1 when the grid follows accesses outside the declared buffer window, otherwise 0. |

<a id="table-memoryheatmapcells"></a>

#### MemoryHeatmapCells

Database table.

One row per touched cell. Join to `MemoryHeatmapLayout` by core ID, owner component, and memory
type. The full key additionally includes cell row and column.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Core ID of the matching layout row. |
| `CoreTypeId` | `INTEGER` | Buffer-owner component ID of the matching layout row. |
| `MemoryType` | `INTEGER` | Recorded memory scope identifier: helper IDs 1 UB, 2 L0A, 3 L0B, 4 L0C, and 5 L1; do not interpret this as `CoreTypeId`. |
| `CellRow` | `INTEGER` | Zero-based row index in the grid. |
| `CellCol` | `INTEGER` | Zero-based column index in the grid. |
| `ReadAddresses` | `INTEGER` | Read address-coverage count for this cell using the analyzer's word/stride rules; not a raw byte or event count. |
| `WriteAddresses` | `INTEGER` | Write address-coverage count for this cell using the same rules. |

A heatmap cell's first byte address is:

```text
BaseAddress + (CellRow * Width + CellCol) * CellSize
```

For full coverage-counting and buffer-ownership rules, see the
[memory heatmap format](../../../npusim/prof/docs/memory_heatmap_format.md).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 18. Cube Utilization

CUBE pipeline busy time is represented by the CUBE rows in `PipesUtilization`.

**Related tables:** [PipesUtilization](#table-pipesutilization).

[Pipeline utilization analysis](../../../npusim/prof/src/backend/analyzers/david/pipe_utilization_analyzer.py).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 20. Scalar/VF Bubble Analysis

The current code implements this path without an object file. Enable it with
`--bubble`; its analyzers use `ExecutedInstructions` and available
`ICacheEvents`. This describes the implementation and its input requirements,
not a new runtime verification.

The selected main pipeline is CUBE for AIC and VECTOR for vector components.
The analyzer finds gaps in that pipeline and uses scalar, memory, synchronization,
and other available activity to classify them. It does not produce a separate
measurement of every scalar stall. Gap causes and optimization suggestions are
inferences from the recorded execution.

Results are stored in `TraceBubbles` and `TraceBubbleSummary`. When report data
exists, the reporter writes `bubble_report_summary.json` and
`bubble_report_detailed.json`; enabled main traces also include bubble events.
`TotalDurationUs` is the first-to-last instruction span of the component, not
the sum of bubble durations. `SubtypeSummary` is text, not JSON.

**Related tables:** [TraceBubbles](#table-tracebubbles), [TraceBubbleSummary](#table-tracebubblesummary), [ExecutedInstructions](#table-executedinstructions), [ICacheEvents](#table-icacheevents).

[Implementation](../../../npusim/prof/src/backend/analyzers/david/trace_bubble_analyzer.py).

<a id="table-tracebubbles"></a>

#### TraceBubbles

Database table.

One inferred gap in the selected main pipeline per row. Gap explanations, optimization flags, and
iteration attribution are analysis results, rather than raw stall-cause measurements.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `MainPipeline` | `TEXT` | Pipeline selected as the main pipeline for bubble analysis. |
| `SubType` | `TEXT` | Detailed gap classification assigned by bubble analysis. |
| `Category` | `TEXT` | Broader gap category assigned by bubble analysis. |
| `TickStart` | `INTEGER` | Start of the recorded interval, in simulator ticks. |
| `TickEnd` | `INTEGER` | End of the recorded interval, in simulator ticks. |
| `GapTicks` | `INTEGER` | Gap duration in simulator ticks. |
| `GapUs` | `REAL` | Gap duration converted to microseconds. |
| `Reason` | `TEXT` | Explanation assigned to the gap; can be NULL when unavailable. |
| `Optimizable` | `INTEGER` | Analyzer flag indicating a potentially optimizable gap, encoded as 0 or 1. |
| `OptimizationHint` | `TEXT` | Suggested optimization for the gap, when available. |
| `WaitedPipeline` | `TEXT` | Pipeline that the gap is inferred to wait for, when identified. |
| `IterationIndex` | `INTEGER` | Associated iteration index, when inferred. |

<a id="table-tracebubblesummary"></a>

#### TraceBubbleSummary

Database table.

Gap aggregates per core/component and selected main pipeline. `TotalDurationUs` is the recorded
core/component span, not the sum of all gap durations.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `MainPipeline` | `TEXT` | Pipeline selected as the main pipeline for bubble analysis. |
| `TotalDurationUs` | `REAL` | First-to-last instruction span of the analyzed core/component, converted to microseconds; not the sum of gap durations. |
| `BubbleCount` | `INTEGER` | Number of detected gaps for this core/component and main pipeline. |
| `TopBottleneck` | `TEXT` | Gap category with the greatest summed gap duration, when gaps exist. |
| `SubtypeSummary` | `TEXT` | Comma-separated `subtype:count` entries sorted by descending count; this field is text, not JSON. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 15. Register Liveness

This feature is not available in the current workflow without an object file. The register-liveness analyzer is not registered; `LiveRegisters` is not populated.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 16. Call Stacks

This feature is not available in the current workflow without source/disassembly data. A separately enabled call-stack analyzer can create a synthetic root and zero-valued root metrics, but this does not provide a usable call tree.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 17. Cross-Instruction Bank Conflicts

Data is available; visualization is not currently available.

`UbBankConflictsCross` is a collected input containing conflicts between
instruction records. It is separate from the `UBBankConflicts` results computed
for individual supported instructions. The timeline can attach its conflict
counts to the owning instruction. The report backend does not synthesize this
input from an empty table.

**Related tables:** [UbBankConflictsCross](#table-ubbankconflictscross), [ExecutedInstructions](#table-executedinstructions), [UBBankConflicts](#table-ubbankconflicts).

[Implementation](../../../npusim/prof/src/frontend/tracing/chrome_tracing_default.py).

<a id="table-ubbankconflictscross"></a>

#### UbBankConflictsCross

Database table.

Collector-provided cross-instruction UB bank-conflict records.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `ExecInstrId` | `INTEGER` | Dynamic instruction identifier; joins to `ExecutedInstructions.ExecInstrId`. |
| `ConflictInstrs` | `VARCHAR(64)` | Collector-formatted text identifying conflicting instruction records; preserve the producer's ID representation. |
| `ConflictCount` | `INTEGER` | Recorded cross-instruction bank-conflict count. |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 18. Scalar Sampling

This feature is not currently available. Scalar IPC calculations and instruction-cache events are separate datasets and should not be presented as scalar sampling.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

## Performance Hints

Kernel-level rules can read execution and analysis tables directly. Ordinary
instruction/source rules rely on the unavailable `AsmMetrics` map in the current
workflow. A stored metric therefore does not imply an emitted hint. Hints are
analytical suggestions, not guarantees of an optimization benefit.

### Shared Hint Tables

`HintTypes` identifies the rule and records its execution status;
`HintMessages` holds the message; `KernelHints` attaches it to the kernel;
`KernelHintsView` joins the readable result. These tables are shared by the
available performance hints below.

A successful rule status does not mean that its condition triggered or that
a message was stored. Kernel hints remain possible when instruction/source
hint tables are empty. [AnalysisState](#table-analysisstate) separately records
the status of the analyses that produce input metrics for the rules.

<a id="table-hinttypes"></a>

#### HintTypes

Database table.

Hint rule dictionary and execution status.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `HintTypeId` | `INTEGER` | Hint rule identifier; joins to `HintTypes.HintTypeId`. |
| `HintTypeName` | `VARCHAR(70)` | Name of the diagnostic rule. |
| `HintPassed` | `BOOLEAN` | 1 when the rule completed successfully, 0 otherwise; does not mean no hint was produced. |

<a id="table-hintmessages"></a>

#### HintMessages

Database table.

Dictionary of human-readable diagnostic messages.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `HintMsgId` | `INTEGER` | Message identifier; joins to `HintMessages.HintMsgId`. |
| `HintMsgText` | `VARCHAR(500)` | Human-readable diagnostic or optimization suggestion. |

<a id="table-kernelhints"></a>

#### KernelHints

Database table.

Attaches a message and rule to the kernel as a whole.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `HintId` | `INTEGER` | Identifier of the hint attachment row within this table. |
| `HintTypeId` | `INTEGER` | Hint rule identifier; joins to `HintTypes.HintTypeId`. |
| `HintMsgId` | `INTEGER` | Message identifier; joins to `HintMessages.HintMsgId`. |

<a id="table-kernelhintsview"></a>

#### KernelHintsView

Database view exported as CSV.

Kernel hint messages with their rule ID; grouped by message ID by the current SQL.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `HintTypeId` | `INTEGER` | Hint rule identifier; joins to `HintTypes.HintTypeId`. |
| `HintMsgText` | `VARCHAR(500)` | Human-readable diagnostic or optimization suggestion. |

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 1.1. Small Grid

This kernel-level rule counts distinct physical core IDs in
`ExecutedInstructions` and compares the count with the configured architecture
maximum. In the current implementation, it emits a hint when at most half of
the available cores are used. It does not rely on static source mapping.

The result uses the shared hint tables described above. No separate `SmallGrid`
result table is created.

**Related tables:** [ExecutedInstructions](#table-executedinstructions),
[KernelInfo](#table-kernelinfo), [HintTypes](#table-hinttypes),
[HintMessages](#table-hintmessages), [KernelHints](#table-kernelhints),
[KernelHintsView](#table-kernelhintsview).

[Implementation](../../../npusim/prof/src/backend/hints/small_grid_hint.py).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 1.2. Launch Overhead

This hint is not currently available. No dedicated launch-overhead result dataset is documented.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 1.3. Tail Effect

Two kernel-level rules compare recorded execution spans:

- Inter-core tail effect groups `ExecutedInstructions` by core ID.
- Intra-core tail effect groups it by core ID and component type.

Each span is `MAX(end_tick) - MIN(start_tick)`. The rules compare the longest
and shortest contributing spans using `(longest - shortest) / longest` and their
configured trigger threshold. Spans include internal gaps. Insufficient distinct
contexts or a nonpositive relevant denominator cannot yield a meaningful comparison.

Messages use the shared kernel hint tables. No separate tail-effect table is
created. This calculation is independent of source/debug mappings.

**Related tables:** [ExecutedInstructions](#table-executedinstructions), [CoreTypes](#table-coretypes), [HintTypes](#table-hinttypes), [HintMessages](#table-hintmessages), [KernelHints](#table-kernelhints), [KernelHintsView](#table-kernelhintsview).

[Implementation](../../../npusim/prof/src/backend/hints/tail_effect_inter_core_hint.py).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 2.1.1. Inefficient Data Copy

This hint is not available in the current workflow. DMA parameter and byte-count data remain available under Instruction Execution Timeline, but their presence does not produce this instruction/source hint without the missing aggregate inputs.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 2.2.1. Inefficient GM Accesses

This hint is not available in the current workflow. Available memory access records should not be presented as an emitted GM-access optimization finding.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 2.2.2. UB Bank Conflicts

This hint is not available in the current workflow. Bank-conflict data and an emitted performance hint are separate results.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 2.3.1. SIMD UB Bank Conflicts

This hint is not available in the current workflow. The related conflict tables are described under SIMD Bank Conflicts (Scatter/Gather).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 3.1.1. Low SIMD Utilization

This hint is not available in the current workflow. VectorUtilizations can contain data, but the instruction/source rule has no AsmMetrics rows to inspect.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 3.1.2. Low SIMD IPC

This kernel-level rule reads `VfIPC.ExecIPC`. It takes the arithmetic mean of
available call-level values, rounds it to four decimal places, and emits a hint
when that mean is below the current threshold of 0.5 instructions per cycle.
No rows or no usable IPC values produce no hint.

Enable the source VF IPC analysis with `--vec-ipc`; registering the hint rule
does not itself create VF IPC data. The result uses the shared kernel hint
tables and works without `AsmMetrics`. There is no dedicated low-IPC table.

**Related tables:** [VfIPC](#table-vfipc), [HintTypes](#table-hinttypes), [HintMessages](#table-hintmessages), [KernelHints](#table-kernelhints), [KernelHintsView](#table-kernelhintsview).

[Implementation](../../../npusim/prof/src/backend/hints/low_vec_ipc_hint.py).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 3.1.3. VF PMU Based Hints

VF PMU hints use synthetic counters computed from collected VF PMU snapshots.
Enable synthetic analysis with `--simd-perf`; the collection must already contain
the required raw PMU counters. Registering a hint rule does not enable collection
or run that analysis automatically.

`VfPMUMetrics` names raw counters and `VfPMUValues` stores cumulative snapshots.
The subcore raw view takes the last snapshot, and the per-VF delta view subtracts
the preceding snapshot, using zero as the initial baseline. Do not sum cumulative
snapshots as independent work.

Synthetic definitions, values, and joined views are separate objects. Their
formulas determine units, scope, and normalization. Missing raw counters can be
evaluated as zero; a nonpositive optimal-slot denominator omits top-down metrics.
Hardware and instruction decompositions of the same parent are alternative
breakdowns, not contributions to add together. Some residuals can be negative.

Kernel-level PMU findings use the shared hint tables. Per-VF rules can first map
VF IDs to dynamic marker PCs. A PC-targeted finding still requires the instruction
hint map built from `AsmMetrics`, which is empty in this workflow. A failed PC
mapping can instead produce a kernel-level fallback for the relevant rules.
Thus PMU data availability does not guarantee every possible PMU hint.

**Related tables:** [VfPMUMetrics](#table-vfpmumetrics), [VfPMUValues](#table-vfpmuvalues), [VfPMUSummary](#table-vfpmusummary), [VfPMUViewPerSubcore](#table-vfpmuviewpersubcore), [VfPMUDeltasViewPerVf](#table-vfpmudeltasviewpervf), [VfPMUSynthTypes](#table-vfpmusynthtypes), [VfPMUSynthValuesPerSubcore](#table-vfpmusynthvaluespersubcore), [VfPMUSynthValuesPerVf](#table-vfpmusynthvaluespervf), [VfPMUSynthViewPerSubcore](#table-vfpmusynthviewpersubcore), [VfPMUSynthViewPerVf](#table-vfpmusynthviewpervf), [ExecutedInstructions](#table-executedinstructions), [HintTypes](#table-hinttypes), [HintMessages](#table-hintmessages), [KernelHints](#table-kernelhints), [KernelHintsView](#table-kernelhintsview).

[Implementation](../../../npusim/prof/src/backend/hints/vf_pmu_hint_utils.py).

<a id="table-vfpmumetrics"></a>

#### VfPMUMetrics

Database table.

Raw VF PMU metric-name dictionary.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `MetricId` | `INTEGER` | Raw PMU metric identifier; joins to `VfPMUMetrics.MetricId`. |
| `MetricName` | `VARCHAR(50)` | Raw PMU counter name from `VfPMUMetrics`. |

<a id="table-vfpmuvalues"></a>

#### VfPMUValues

Database table.

One cumulative raw metric snapshot per core/component, VF sequence ID, and metric ID. Do not sum
snapshots across VF IDs to calculate total activity.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `VfId` | `INTEGER` | VF sequence identifier in the PMU stream for this core/component; not the sorted ID in VF report JSON. |
| `MetricId` | `INTEGER` | Raw PMU metric identifier; joins to `VfPMUMetrics.MetricId`. |
| `MetricValue` | `INTEGER` | Recorded cumulative raw counter value; units depend on the counter name. |

<a id="table-vfpmusummary"></a>

#### VfPMUSummary

Database table.

Collector-provided tick totals for each VF PMU snapshot. The kernel/system distinction is defined by
the producing PMU stream.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `VfId` | `INTEGER` | VF sequence identifier in the PMU stream for this core/component; not the sorted ID in VF report JSON. |
| `VfKernelTicks` | `INTEGER` | Recorded VF kernel tick counter for this snapshot. |
| `VfSystemTicks` | `INTEGER` | Recorded VF system tick counter for this snapshot. |

<a id="table-vfpmuviewpersubcore"></a>

#### VfPMUViewPerSubcore

Database view exported as CSV.

Last cumulative snapshot per core/component, selected using the maximum VF ID for that
core/component. Metric names are joined from `VfPMUMetrics`.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `MetricId` | `INTEGER` | Raw PMU metric identifier; joins to `VfPMUMetrics.MetricId`. |
| `MetricName` | `VARCHAR(50)` | Raw PMU counter name from `VfPMUMetrics`. |
| `MetricValue` | `INTEGER` | Recorded cumulative raw counter value; units depend on the counter name. |

<a id="table-vfpmudeltasviewpervf"></a>

#### VfPMUDeltasViewPerVf

Database view exported as CSV.

Per-VF raw counter increments: current snapshot minus the preceding snapshot for the same
core/component and metric; the first snapshot subtracts zero.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `VfId` | `INTEGER` | VF sequence identifier in the PMU stream for this core/component; not the sorted ID in VF report JSON. |
| `MetricId` | `INTEGER` | Raw PMU metric identifier; joins to `VfPMUMetrics.MetricId`. |
| `MetricName` | `VARCHAR(50)` | Raw PMU counter name from `VfPMUMetrics`. |
| `MetricDelta` | not declared | Counter increment for this VF sequence entry, in the raw counter's units. |

<a id="table-vfpmusynthtypes"></a>

#### VfPMUSynthTypes

Database table.

Synthetic metric dictionary with parent hierarchy and persistence scope. A NULL parent is
meaningful, and IDs are dictionary keys rather than values to compare across archives.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `SynthId` | `INTEGER` | Synthetic metric identifier; joins to `VfPMUSynthTypes.SynthId`. |
| `SynthName` | `VARCHAR(64)` | Synthetic metric name, with the `syn_c_` prefix. |
| `SynthParentId` | `INTEGER` | Parent synthetic metric identifier; NULL for a root or intermediate without a parent. |
| `SynthLevel` | `INTEGER` | Hierarchy level: 0 for an intermediate counter, 1 and above for top-down hierarchy nodes. |
| `SynthScope` | `INTEGER` | Scope bitmask: 1 subcore, 2 VF, or 3 both. |

<a id="table-vfpmusynthvaluespersubcore"></a>

#### VfPMUSynthValuesPerSubcore

Database table.

Computed metric values keyed by `(CoreId, CoreTypeId, SynthId)`.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `SynthId` | `INTEGER` | Synthetic metric identifier; joins to `VfPMUSynthTypes.SynthId`. |
| `SynthValue` | `REAL` | Computed metric value; units and normalization follow the formula for `SynthName`. |

<a id="table-vfpmusynthvaluespervf"></a>

#### VfPMUSynthValuesPerVf

Database table.

Computed metric values keyed by `(CoreId, CoreTypeId, VfId, SynthId)`.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `VfId` | `INTEGER` | VF sequence identifier in the PMU stream for this core/component; not the sorted ID in VF report JSON. |
| `SynthId` | `INTEGER` | Synthetic metric identifier; joins to `VfPMUSynthTypes.SynthId`. |
| `SynthValue` | `REAL` | Computed metric value; units and normalization follow the formula for `SynthName`. |

<a id="table-vfpmusynthviewpersubcore"></a>

#### VfPMUSynthViewPerSubcore

Database view exported as CSV.

Subcore synthetic values joined to metric names, parent names, and hierarchy levels. Scope flags
remain in `VfPMUSynthTypes`.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `SynthId` | `INTEGER` | Synthetic metric identifier; joins to `VfPMUSynthTypes.SynthId`. |
| `SynthName` | `VARCHAR(64)` | Synthetic metric name, with the `syn_c_` prefix. |
| `SynthParentId` | `INTEGER` | Parent synthetic metric identifier; NULL for a root or intermediate without a parent. |
| `SynthParentName` | `VARCHAR(64)` | Parent synthetic metric name resolved through `VfPMUSynthTypes`; NULL when no parent is defined. |
| `SynthLevel` | `INTEGER` | Hierarchy level: 0 for an intermediate counter, 1 and above for top-down hierarchy nodes. |
| `SynthValue` | `REAL` | Computed metric value; units and normalization follow the formula for `SynthName`. |

<a id="table-vfpmusynthviewpervf"></a>

#### VfPMUSynthViewPerVf

Database view exported as CSV.

Per-VF synthetic values joined to metric names, parent names, and hierarchy levels. Scope flags
remain in `VfPMUSynthTypes`.

| Field | SQLite type | Meaning |
| --- | --- | --- |
| `CoreId` | `INTEGER` | Recorded core identifier; combine with `CoreTypeId` where that field is present. |
| `CoreTypeId` | `INTEGER` | Core component identifier; joins to `CoreTypes.CoreTypeId`. |
| `VfId` | `INTEGER` | VF sequence identifier in the PMU stream for this core/component; not the sorted ID in VF report JSON. |
| `SynthId` | `INTEGER` | Synthetic metric identifier; joins to `VfPMUSynthTypes.SynthId`. |
| `SynthName` | `VARCHAR(64)` | Synthetic metric name, with the `syn_c_` prefix. |
| `SynthParentId` | `INTEGER` | Parent synthetic metric identifier; NULL for a root or intermediate without a parent. |
| `SynthParentName` | `VARCHAR(64)` | Parent synthetic metric name resolved through `VfPMUSynthTypes`; NULL when no parent is defined. |
| `SynthLevel` | `INTEGER` | Hierarchy level: 0 for an intermediate counter, 1 and above for top-down hierarchy nodes. |
| `SynthValue` | `REAL` | Computed metric value; units and normalization follow the formula for `SynthName`. |

The rule families cover bottleneck classification, register pressure, fetch
stalls, dependencies, memory barriers, vector functional-unit conflicts, queue
pressure, execution-queue imbalance, UB bandwidth, gather/scatter stalls, and
per-VF outliers. Exact formulas and thresholds are maintained in the
[PMU metric definitions](../../../npusim/prof/src/backend/analyzers/vf_pmu/metrics.py)
and the [PMU hint helpers](../../../npusim/prof/src/backend/hints/vf_pmu_hint_utils.py).

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 3.1.4. Non-fused FP instructions

This hint is not currently available. No supported result dataset is documented for this rule.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 3.3.1. Low MMAD Utilization

This hint is not currently available as the listed feature. CUBE pipeline metrics and MmadParams do not by themselves constitute a Low MMAD Utilization finding.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->

### 3.4.1. Low Scalar IPC

This hint is not currently available. An existing scalar IPC value or windowed IPC table is not an emitted Low Scalar IPC hint.

#### UI Mapping and Screenshots

<!-- UI team: add one row per displayed element. Specify table/field names,
     joins or calculations, units, formatting, aggregation, and filters. -->

| UI screen or element | Source table(s) | Source field(s) | Display rules | Screenshot reference(s) |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

<!-- UI team: insert screenshots here using relative image links to figures/.
     Add captions that identify the UI elements covered by the mapping above. -->
