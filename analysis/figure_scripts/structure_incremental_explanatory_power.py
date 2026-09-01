from __future__ import annotations

import argparse
import csv
import math
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as stats
import statsmodels.formula.api as smf
import xlrd
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D


STRUCTURES = [
    {
        "key": "SSA",
        "source": "比表面积（m²·g⁻¹）",
        "display": "比表面积",
        "transform": "log",
    },
    {
        "key": "APS",
        "source": "平均孔径（nm）",
        "display": "平均孔径",
        "transform": "log",
    },
    {
        "key": "TPV",
        "source": "总孔容（cm³·g⁻¹）",
        "display": "总孔容",
        "transform": "log",
    },
    {
        "key": "O_content",
        "source": "氧含量（%）",
        "display": "氧含量",
        "transform": "log",
    },
    {
        "key": "pH_pzc",
        "source": "零电荷点（pHpzc）",
        "display": "零电荷点",
        "transform": "raw",
    },
]

KEYS = ["filename", "sample_id"]
RESPONSE = "平衡吸附量（mg·g⁻¹）"
BASELINE_COLUMNS = ["pH", "初始浓度（mg·L⁻¹）", "固液比（g·L⁻¹）", "吸附温度（K）"]
BLUE = "#4683B4"
GREY = "#9AA1A8"
TEXT = "#29333A"
GRID = "#DCE3E8"


def read_sheet(book: xlrd.book.Book, name: str) -> pd.DataFrame:
    sheet = book.sheet_by_name(name)
    headers = [str(sheet.cell_value(0, column)).strip() for column in range(sheet.ncols)]
    rows = []
    for row in range(1, sheet.nrows):
        record = {}
        for column, header in enumerate(headers):
            if header and header not in record:
                record[header] = sheet.cell_value(row, column)
        rows.append(record)
    return pd.DataFrame(rows)


def standardize(values: pd.Series) -> pd.Series:
    mean = float(values.mean())
    sd = float(values.std(ddof=1))
    if not math.isfinite(sd) or sd <= 0:
        raise ValueError(f"Cannot standardize a constant variable: {values.name}")
    return (values - mean) / sd


def prepare_analysis(input_path: Path) -> pd.DataFrame:
    book = xlrd.open_workbook(str(input_path))
    materials = read_sheet(book, "Sheet1")
    adsorption = read_sheet(book, "Sheet2")
    structure_columns = [item["source"] for item in STRUCTURES]
    merged = adsorption.merge(
        materials[KEYS + structure_columns],
        on=KEYS,
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    for column in [RESPONSE, *BASELINE_COLUMNS, *structure_columns]:
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged["nuclide"] = merged["放射性核素"].astype(str).str.strip()
    merged["literature_id"] = merged["filename"].astype(str).str.strip()
    merged["material_id"] = (
        merged["filename"].astype(str).str.strip()
        + "::"
        + merged["sample_id"].astype(str).str.strip()
    )
    return merged


def structure_cases(data: pd.DataFrame, structure: dict[str, str]) -> pd.DataFrame:
    required = [RESPONSE, *BASELINE_COLUMNS, structure["source"]]
    mask = data[required].notna().all(axis=1)
    mask &= data[RESPONSE].gt(0)
    mask &= data["初始浓度（mg·L⁻¹）"].gt(0)
    mask &= data["固液比（g·L⁻¹）"].gt(0)
    mask &= data[structure["source"]].gt(0)
    mask &= data["nuclide"].ne("") & data["literature_id"].ne("") & data["material_id"].ne("")
    cases = data.loc[mask].copy()

    cases["log_qe"] = np.log(cases[RESPONSE])
    cases["pH_z"] = standardize(cases["pH"])
    cases["log_c0_z"] = standardize(np.log(cases["初始浓度（mg·L⁻¹）"]).rename("log_c0"))
    cases["log_slr_z"] = standardize(np.log(cases["固液比（g·L⁻¹）"]).rename("log_slr"))
    cases["temperature_z"] = standardize(cases["吸附温度（K）"])
    structure_values = cases[structure["source"]]
    if structure["transform"] == "log":
        structure_values = np.log(structure_values)
    cases["structure_z"] = standardize(structure_values.rename("structure"))
    cases["nuclide"] = pd.Categorical(cases["nuclide"])
    return cases


BASELINE_FORMULA = (
    "log_qe ~ pH_z + I(pH_z ** 2) + log_c0_z + I(log_c0_z ** 2) "
    "+ log_slr_z + temperature_z + C(nuclide)"
)
EXTENDED_FORMULA = BASELINE_FORMULA + " + structure_z + I(structure_z ** 2)"


def fit_mixed_model(formula: str, data: pd.DataFrame):
    model = smf.mixedlm(
        formula,
        data=data,
        groups=data["literature_id"],
        re_formula="1",
        vc_formula={"material": "0 + C(material_id)"},
    )
    errors = []
    for method in ["lbfgs", "powell", "bfgs"]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = model.fit(reml=False, method=method, maxiter=2500, disp=False)
            finite_parts = [
                np.asarray(result.fe_params, dtype=float),
                np.asarray(result.cov_re, dtype=float),
                np.asarray(getattr(result, "vcomp", []), dtype=float),
                np.asarray([result.scale, result.llf], dtype=float),
            ]
            if result.converged and all(np.isfinite(part).all() for part in finite_parts):
                return result, method
            errors.append(f"{method}: non-converged or non-finite result")
        except Exception as exc:  # pragma: no cover - method fallback is data dependent
            errors.append(f"{method}: {exc}")
    raise RuntimeError("Mixed model failed: " + " | ".join(errors))


def marginal_r2(result) -> tuple[float, dict[str, float]]:
    exog = np.asarray(result.model.exog, dtype=np.float64)
    coefficients = np.asarray(result.fe_params, dtype=np.float64)
    if not np.isfinite(exog).all() or not np.isfinite(coefficients).all():
        raise ValueError("Non-finite fixed-effect design or coefficients")
    with np.errstate(over="raise", divide="raise", invalid="raise"):
        fixed_prediction = np.dot(exog, coefficients)
    if not np.isfinite(fixed_prediction).all():
        raise ValueError("Non-finite fixed-effect predictions")
    fixed_variance = float(np.var(fixed_prediction, ddof=1))
    random_variance = float(np.trace(np.asarray(result.cov_re, dtype=float)))
    if getattr(result, "vcomp", None) is not None:
        random_variance += float(np.sum(np.asarray(result.vcomp, dtype=float)))
    residual_variance = float(result.scale)
    denominator = fixed_variance + random_variance + residual_variance
    r2 = fixed_variance / denominator if denominator > 0 else math.nan
    return r2, {
        "fixed_variance": fixed_variance,
        "random_variance": random_variance,
        "residual_variance": residual_variance,
    }


def fit_bootstrap_model(formula: str, data: pd.DataFrame):
    model = smf.mixedlm(
        formula,
        data=data,
        groups=data["literature_id"],
        re_formula="1",
        vc_formula={"material": "0 + C(material_id)"},
    )
    for method in ["lbfgs", "powell"]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = model.fit(reml=False, method=method, maxiter=1200, disp=False)
            finite_parts = [
                np.asarray(result.fe_params, dtype=float),
                np.asarray(result.cov_re, dtype=float),
                np.asarray(getattr(result, "vcomp", []), dtype=float),
                np.asarray([result.scale, result.llf], dtype=float),
            ]
            if result.converged and all(np.isfinite(part).all() for part in finite_parts):
                return result
        except Exception:
            continue
    raise RuntimeError("Bootstrap mixed model did not converge")


def resample_literature_clusters(cases: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    literature_ids = cases["literature_id"].drop_duplicates().to_numpy()
    draws = rng.choice(literature_ids, size=len(literature_ids), replace=True)
    blocks = []
    for draw_index, literature_id in enumerate(draws):
        block = cases.loc[cases["literature_id"].eq(literature_id)].copy()
        prefix = f"bootstrap_{draw_index}::"
        block["literature_id"] = prefix + str(literature_id)
        block["material_id"] = prefix + block["material_id"].astype(str)
        blocks.append(block)
    sampled = pd.concat(blocks, ignore_index=True)
    sampled["nuclide"] = pd.Categorical(sampled["nuclide"].astype(str))
    return sampled


def bootstrap_structure(
    structure_key: str,
    cases: pd.DataFrame,
    iterations: int,
    seed: int,
) -> tuple[str, list[float], int]:
    rng = np.random.default_rng(seed)
    deltas: list[float] = []
    failures = 0
    for _ in range(iterations):
        try:
            sampled = resample_literature_clusters(cases, rng)
            baseline = fit_bootstrap_model(BASELINE_FORMULA, sampled)
            extended = fit_bootstrap_model(EXTENDED_FORMULA, sampled)
            baseline_r2, _ = marginal_r2(baseline)
            extended_r2, _ = marginal_r2(extended)
            delta = extended_r2 - baseline_r2
            if math.isfinite(delta):
                deltas.append(delta)
            else:
                failures += 1
        except Exception:
            failures += 1
    return structure_key, deltas, failures


def attach_bootstrap_intervals(
    data: pd.DataFrame,
    results: list[dict[str, object]],
    iterations: int,
    jobs: int,
    seed: int,
) -> None:
    cases_by_key = {
        structure["key"]: structure_cases(data, structure)
        for structure in STRUCTURES
    }
    distributions: dict[str, tuple[list[float], int]] = {}
    worker_count = max(1, min(jobs, len(STRUCTURES)))
    if worker_count == 1:
        for index, structure in enumerate(STRUCTURES):
            key, deltas, failures = bootstrap_structure(
                structure["key"],
                cases_by_key[structure["key"]],
                iterations,
                seed + index * 1009,
            )
            distributions[key] = (deltas, failures)
            print(f"bootstrap {key}: success={len(deltas)}/{iterations}, failures={failures}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    bootstrap_structure,
                    structure["key"],
                    cases_by_key[structure["key"]],
                    iterations,
                    seed + index * 1009,
                ): structure["key"]
                for index, structure in enumerate(STRUCTURES)
            }
            for future in as_completed(futures):
                key, deltas, failures = future.result()
                distributions[key] = (deltas, failures)
                print(f"bootstrap {key}: success={len(deltas)}/{iterations}, failures={failures}", flush=True)

    minimum_success = max(10, int(math.ceil(iterations * 0.70)))
    for item in results:
        deltas, failures = distributions[str(item["key"])]
        if len(deltas) < minimum_success:
            raise RuntimeError(
                f"Too few successful bootstrap replicates for {item['key']}: "
                f"{len(deltas)}/{iterations}"
            )
        item["bootstrap_attempts"] = iterations
        item["bootstrap_success"] = len(deltas)
        item["bootstrap_failures"] = failures
        item["bootstrap_ci_low"] = float(np.percentile(deltas, 2.5))
        item["bootstrap_ci_high"] = float(np.percentile(deltas, 97.5))
        item["bootstrap_seed"] = seed


def analyze_structure(data: pd.DataFrame, structure: dict[str, str]) -> dict[str, object]:
    cases = structure_cases(data, structure)
    baseline, baseline_method = fit_mixed_model(BASELINE_FORMULA, cases)
    extended, extended_method = fit_mixed_model(EXTENDED_FORMULA, cases)
    baseline_r2, baseline_variances = marginal_r2(baseline)
    extended_r2, extended_variances = marginal_r2(extended)
    delta = extended_r2 - baseline_r2
    partial = delta / (1.0 - baseline_r2) if baseline_r2 < 1 else math.nan
    lr = max(0.0, 2.0 * (extended.llf - baseline.llf))
    p_value = float(stats.chi2.sf(lr, df=2))
    return {
        "key": structure["key"],
        "display": structure["display"],
        "source_column": structure["source"],
        "structure_transform": structure["transform"],
        "n": len(cases),
        "literature_n": int(cases["literature_id"].nunique()),
        "material_n": int(cases["material_id"].nunique()),
        "nuclide_n": int(cases["nuclide"].nunique()),
        "baseline_marginal_r2": baseline_r2,
        "extended_marginal_r2": extended_r2,
        "delta_marginal_r2": delta,
        "partial_r2": partial,
        "likelihood_ratio": lr,
        "lrt_df": 2,
        "lrt_p": p_value,
        "baseline_llf": float(baseline.llf),
        "extended_llf": float(extended.llf),
        "baseline_aic": float(baseline.aic),
        "extended_aic": float(extended.aic),
        "baseline_converged": bool(baseline.converged),
        "extended_converged": bool(extended.converged),
        "baseline_optimizer": baseline_method,
        "extended_optimizer": extended_method,
        **{f"baseline_{key}": value for key, value in baseline_variances.items()},
        **{f"extended_{key}": value for key, value in extended_variances.items()},
    }


def select_font() -> FontProperties:
    for path in [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
    ]:
        if path.exists():
            return FontProperties(fname=str(path))
    return FontProperties(family="sans-serif")


def significance_text(p_value: float) -> str:
    if p_value < 0.001:
        return "P<0.001"
    return f"P={p_value:.3f}"


def draw_figure(results: list[dict[str, object]], output_stem: Path) -> None:
    font = select_font()
    mpl.rcParams.update(
        {
            "font.family": font.get_name(),
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
        }
    )
    result_by_key = {str(item["key"]): item for item in results}
    order = ["O_content", "SSA", "TPV", "pH_pzc", "APS"]
    labels_by_key = {
        "O_content": "O含量",
        "SSA": "SSA",
        "TPV": "TPV",
        "pH_pzc": r"$\mathrm{pH}_{\mathrm{pzc}}$",
        "APS": "APS",
    }
    ordered = [result_by_key[key] for key in order]
    labels = [labels_by_key[key] for key in order]
    delta_pct = np.asarray([100.0 * float(item["delta_marginal_r2"]) for item in ordered])
    ci_low_pct = np.asarray([100.0 * float(item["bootstrap_ci_low"]) for item in ordered])
    ci_high_pct = np.asarray([100.0 * float(item["bootstrap_ci_high"]) for item in ordered])
    y = np.arange(len(ordered))

    fig, ax = plt.subplots(figsize=(130 / 25.4, 94 / 25.4), facecolor="white")
    values_for_limits = np.concatenate([delta_pct, ci_low_pct, ci_high_pct, np.asarray([0.0])])
    data_span = max(1.0, float(values_for_limits.max() - values_for_limits.min()))
    lower = float(values_for_limits.min() - data_span * 0.10)
    upper = float(values_for_limits.max() + data_span * 0.20)

    for row, item, value, ci_low, ci_high in zip(y, ordered, delta_pct, ci_low_pct, ci_high_pct):
        significant = float(item["lrt_p"]) < 0.05
        color = BLUE if significant else GREY
        ax.hlines(row, ci_low, ci_high, color=color, linewidth=1.35, zorder=2)
        ax.vlines([ci_low, ci_high], row - 0.075, row + 0.075, color=color, linewidth=1.0, zorder=2)
        ax.scatter(
            value,
            row,
            s=38,
            marker="o",
            facecolor=color if significant else "white",
            edgecolor=color,
            linewidth=1.15,
            zorder=3,
        )
        ax.text(
            value,
            row - 0.19,
            f"ΔR²={value:.2f}",
            ha="center",
            va="bottom",
            fontsize=6.8,
            color=TEXT,
        )
        ax.text(
            1.025,
            row,
            f"n={int(item['n'])}",
            transform=ax.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=7.0,
            color=TEXT,
            clip_on=False,
        )

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontproperties=font, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_ylim(len(ordered) - 0.45, -0.45)
    ax.set_xlabel("Δ边际 R²（百分点）", fontproperties=font, fontsize=8.5, labelpad=8)
    ax.set_title("结构因素的增量解释力", loc="left", fontproperties=font, fontsize=10.5, pad=17)
    ax.xaxis.grid(True, color=GRID, linewidth=0.65, zorder=0)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#66727A")
    ax.tick_params(axis="y", length=0, pad=7)
    ax.tick_params(axis="x", labelsize=7.5, length=3, color="#66727A")
    ax.set_xlim(lower, upper)
    ax.axvline(0, color="#69757D", linewidth=0.9, linestyle=(0, (3, 3)), zorder=1)
    legend_handles = [
        Line2D(
            [0], [0], marker="o", linestyle="none", markersize=5.2,
            markerfacecolor=BLUE, markeredgecolor=BLUE, label="P < 0.05",
        ),
        Line2D(
            [0], [0], marker="o", linestyle="none", markersize=5.2,
            markerfacecolor="white", markeredgecolor=GREY, label="P ≥ 0.05",
        ),
    ]
    ax.legend(
        handles=legend_handles,
        loc="upper right",
        bbox_to_anchor=(1.0, 1.13),
        ncol=2,
        columnspacing=1.2,
        handletextpad=0.35,
        borderaxespad=0,
        frameon=False,
        fontsize=6.8,
    )

    fig.text(
        0.14,
        0.018,
        f"水平线为按文献整群重抽样的 bootstrap 95% CI（{int(ordered[0]['bootstrap_attempts'])}次）；"
        "P 值来自基线与扩展混合模型的似然比检验。",
        ha="left",
        va="bottom",
        fontproperties=font,
        fontsize=5.8,
        color="#66727A",
    )
    fig.subplots_adjust(left=0.20, right=0.89, top=0.81, bottom=0.22)
    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(output_stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_source(path: Path, results: list[dict[str, object]]) -> None:
    fields = list(results[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)


def write_method(path: Path, results: list[dict[str, object]], bootstrap_iterations: int) -> None:
    sample_lines = "\n".join(
        f"- {item['display']}：n={item['n']}，文献={item['literature_n']}，材料={item['material_n']}，"
        f"bootstrap 成功={item['bootstrap_success']}/{item['bootstrap_attempts']}。"
        for item in results
    )
    text = f"""# 结构因素的增量解释力

- 分析主体：Sheet2 的吸附记录；通过 filename 与 sample_id 从 Sheet1 匹配材料结构参数。
- 响应变量：平衡吸附量取自然对数。
- 每个结构变量使用其自身的完整案例，并在完全相同的样本内拟合基线模型和扩展模型。由于五个结构变量共同完整的记录仅来自单一材料，不采用共同完整案例排名。
- 基线固定效应：pH（线性与二次项）、初始浓度自然对数（线性与二次项）、固液比自然对数、吸附温度、核素类型。
- 随机效应：文献随机截距，以及嵌套于文献的材料随机截距。
- 扩展模型：在基线模型上加入经标准化的结构变量线性项和二次项；比表面积、平均孔径、总孔容和氧含量先取自然对数，零电荷点保留原尺度。
- 模型使用最大似然估计。边际 R² 定义为固定效应预测方差占固定效应、随机效应和残差总方差的比例。
- ΔR² = 扩展模型边际 R² − 基线模型边际 R²；partial R² = ΔR² / (1 − 基线模型边际 R²)。
- 95% CI 使用按文献整群重抽样的非参数 bootstrap（尝试 {bootstrap_iterations} 次）。每次抽样均重新拟合基线与扩展混合模型，并以Δ边际 R²分布的2.5%和97.5%分位数构建区间。
- 图右侧 n 为该结构参数分析中纳入的 Sheet2 吸附记录数，不是文献数；文献数与材料数在下方单独列出。
- 点表示原始数据拟合得到的Δ边际 R²，水平线表示 bootstrap 95% CI。
- 图内 P 值来自两个模型的似然比检验（2 个新增自由度），用于辅助判断，不进行多重比较校正。
- 由于不同结构参数缺失程度不同，各柱样本量不同，ΔR² 排序应视为探索性证据，而不是完全同质样本上的严格优劣检验。

## 有效样本
{sample_lines}
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot incremental explanatory power of biochar structure variables.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260819)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data = prepare_analysis(args.input)
    results = [analyze_structure(data, structure) for structure in STRUCTURES]
    attach_bootstrap_intervals(data, results, args.bootstrap, args.jobs, args.seed)
    stem = args.output_dir / "structure_incremental_explanatory_power_forest_bootstrap"
    draw_figure(results, stem)
    write_source(args.output_dir / "structure_incremental_explanatory_power_forest_source_data.csv", results)
    write_method(
        args.output_dir / "structure_incremental_explanatory_power_forest_method.md",
        results,
        args.bootstrap,
    )
    for item in sorted(results, key=lambda row: float(row["delta_marginal_r2"]), reverse=True):
        print(
            item["display"],
            f"n={item['n']}",
            f"baseline_R2={item['baseline_marginal_r2']:.6f}",
            f"extended_R2={item['extended_marginal_r2']:.6f}",
            f"delta_R2={item['delta_marginal_r2']:.6f}",
            f"partial_R2={item['partial_r2']:.6f}",
            f"P={item['lrt_p']:.6g}",
            f"CI=({item['bootstrap_ci_low']:.6f},{item['bootstrap_ci_high']:.6f})",
            f"bootstrap={item['bootstrap_success']}/{item['bootstrap_attempts']}",
            f"converged={item['baseline_converged']}/{item['extended_converged']}",
        )
    print(f"output_stem={stem}")


if __name__ == "__main__":
    main()
