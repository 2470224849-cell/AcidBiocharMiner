# Frozen acid-biochar pipeline

## Scope and final product

The target population is acid-modified biochar together with the corresponding pristine biochar used in aqueous adsorption studies. The final product is a two-sheet workbook:

- `sheet1`: material preparation, acid modification, and characterization;
- `sheet2`: adsorption conditions and explicitly reported performance fields.

The pipeline is designed to preserve evidence and intermediate states rather than treating one LLM response as the final dataset.

## Stage 1: literature and supplementary-information collection

`check_supplementary_by_doi.py` reads DOI, title, and link columns from an Excel workbook, follows DOI landing pages, and searches for supplementary-information signals. `download_supplementary_from_check.py` ranks candidate attachment links using keywords and file extensions and limits the number of downloads per article.

Inputs: DOI workbook or local article folders.

Outputs: supplementary check workbook/CSV and downloaded attachments with a manifest.

Known limitation: publisher sites can block automated requests or render links dynamically. Downloaded files must be checked for relevance and redistribution rights.

## Stage 2: strict extractability screening

`screen_pdf_for_extraction.py` examines early-page text quantity, characters per page, unit and table signals, scan likelihood, biochar preparation context, acid reagent and treatment evidence, pollutants, characterization fields, adsorption conditions, and performance-model signals.

The `acid-biochar-strict` profile rejects or downgrades review papers, scan-like PDFs, pH-adjustment-only acid mentions, non-aqueous studies, non-target composites, and papers without sufficiently structured evidence.

`collect_screened_pdfs.py` copies or symlinks selected `PASS`/`MAYBE` files and writes a manifest.

## Stage 3: frozen batch extraction

`run_fixed_extract_batch.sh` calls `run_folder_main_si_extract.py` with the following fixed settings:

- Docling parser;
- strict Docling errors, with no pypdf fallback;
- `acid_pristine` sample filter;
- no extraction-stage backfill;
- no extraction-stage batch Excel merge;
- skip existing outputs for resumable batches.

The batch limit is cumulative, so a run can progress from 20 to 40 papers while retaining completed paper folders.

## Stage 4: main article and SI as one evidence unit

`run_folder_main_si_extract.py` recursively finds main PDFs, excludes supplementary-looking names, and calls `run_main_si_extract.py` once per article.

`run_main_si_extract.py` discovers associated PDF/DOCX SI files using both SI keywords and main-file root matching. Legacy `.doc` conversion uses macOS `textutil`. Each input file produces:

- `result.json`;
- `raw_target_rows.json`;
- `reader.json`;
- a processing log.

The article-level directory also contains merged raw rows and a main/SI summary.

## Stage 5: document parsing and JournalReader construction

`run_pdf_demo.py` uses Docling to export layout-aware Markdown/text and separates Markdown tables from prose. Text is divided into sentence-aware chunks. When strict Docling is disabled, pypdf can be used as a fallback.

`run_docx_demo.py` reads paragraphs and tables directly from WordprocessingML. Both paths create indexed `JournalReader` elements with element type, content, and normalized text.

For a Docling whole-document export, `max_pages` is approximated by proportional text truncation rather than exact page-boundary extraction. This limitation should be retained in method reporting.

## Stage 6: two-source candidate extraction

Candidate rows are collected from:

1. element-level LLM outputs for `biochar_modification` and `adsorption_experiment`;
2. direct Markdown-table parsing by `direct_sheet1_parser.py` and `direct_sheet2_parser.py`.

Unknown fields remain empty. The pipeline preserves raw row-level candidates so that later merging does not erase repeated adsorption conditions or table-specific values.

## Stage 7: acid/pristine sample filtering

`target_row_filter.py` classifies rows as `acid`, `pristine`, `other`, or `unknown` using `sample_id`, `acid_type`, `modification_sequence`, explicit inclusion/exclusion keywords, and same-paper context. Only acid and pristine rows are retained. Project-specific hard exclusions are implemented in this file and should be reviewed when the scientific scope changes.

## Stage 8: initial two-sheet export

`export_target_excel.py` normalizes units and scalar text, converts supported acid concentrations to mol/L, reconciles main/SI paper keys, conservatively fills missing sample IDs, merges complementary rows, reduces sheet 1 toward one row per sample, preserves distinct sheet 2 condition combinations, and absorbs or removes unresolved pseudo-sample rows.

Sheet 1 includes preparation, acid-treatment, surface/porosity, elemental, and pH-pzc fields. Sheet 2 includes sample, pollutant, pH, temperature, contact/equilibrium time, solid-liquid ratio, and explicitly reported `Qmax` where available.

## Stage 9: frozen post-processing

`run_fixed_postprocess.sh` applies four ordered stages:

1. `export_target_excel.py`;
2. `backfill_sheet1_from_reader_tables.py`;
3. `backfill_sheet1_from_method_text.py` without global acid-field propagation;
4. `backfill_sheet2_from_method_text.py --allow-global --room-temp-as-k`.

The table backfill uses explicit raw-row evidence. The method-text backfills use regular expressions and within-paper frequency/uniqueness rules rather than an additional LLM call. Sheet 2 propagation proceeds from filename + sample, to filename + pollutant, to filename, only when a field is unique or clearly dominant within the relevant group.

## Stage 10: outputs and audit trail

Important batch outputs are:

- `batch_merged_raw_target_rows.json`;
- `batch_main_plus_si_tables.xlsx`;
- `batch_main_plus_si_tables_step1_table.xlsx`;
- `batch_main_plus_si_tables_step2_table_method.xlsx`;
- `batch_main_plus_si_tables_step3_table_method_sheet2.xlsx`;
- `batch_main_plus_si_tables_FINAL.xlsx`.

Each stage writes logs and JSON details that record filled cells, source evidence, and counts. These artifacts are essential for auditing but may contain publisher-derived text and therefore are excluded from the public repository by default.

