# Model-selection evaluation

`model_macro_metrics.csv` preserves the aggregate values used in the current figure:

| Model | Precision | Recall | F1 |
|---|---:|---:|---:|
| DeepSeek-V4 | 0.940 | 0.910 | 0.920 |
| GPT-4o | 0.905 | 0.860 | 0.880 |
| GPT-5.4-mini | 0.775 | 0.885 | 0.825 |

These point estimates make DeepSeek-V4 the best of the three reported configurations under the stated aggregate metric. They do not, by themselves, establish that the choice is statistically stable or independently reproducible.

## Files still required

Before publication, add the following non-copyrighted benchmark artifacts:

1. `sampling_manifest.csv`: ten article identifiers, source population, eligibility status, sampling method, random seed, and any strata;
2. `annotation_guideline.md`: field definitions, missing-value rules, unit normalization, row identity, ambiguous-value handling, and adjudication procedure;
3. `gold_sheet1.csv` and `gold_sheet2.csv`: human annotations with article ID, sample ID, field, normalized value, raw value, and evidence location;
4. one prediction file per model generated from the same ten articles, frozen prompts, parser outputs, and post-processing policy;
5. `evaluate_field_matching.py`: the exact evaluator used for string normalization, numeric tolerance, empty fields, duplicate rows, row alignment, and macro averaging;
6. `benchmark_metadata.yaml`: provider, resolved model ID/version, run dates, temperature, parser version, prompt commit, retry policy, and failures;
7. per-paper and per-field scores plus bootstrap confidence intervals.

Do not upload publisher PDFs or long extracted passages. DOI/title identifiers, structured annotations, short evidence locators, and derived numeric tables are usually sufficient for evaluation reuse, subject to journal and data-license checks.

## Reporting caution

The current code directory contains aggregate scores and several generated metric JSON files, but no single preserved evaluator and gold-standard package that reconstructs the three plotted macro scores end to end. Until the seven items above are added, the manuscript should describe the model comparison as an internal benchmark and avoid claiming complete independent reproducibility.

Also distinguish the provider alias shown in the figure (`DeepSeek-V4`) from the configuration alias (`deepseek-v4-flash`). Record the provider-resolved model revision and access date so that the benchmark label is unambiguous.

