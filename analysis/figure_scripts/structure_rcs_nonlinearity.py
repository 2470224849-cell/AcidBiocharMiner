from __future__ import annotations

import argparse
import csv
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2

from structure_incremental_explanatory_power import (
    STRUCTURES,
    fit_bootstrap_model,
    fit_mixed_model,
    prepare_analysis,
    standardize,
    structure_cases,
)
from structure_standardized_adjusted_effects import GREEN, GREEN_LIGHT, select_font


BASE_FORMULA = (
    "log_qe_z ~ pH_z + I(pH_z ** 2) + log_c0_z + I(log_c0_z ** 2) "
    "+ log_slr_z + temperature_z + C(nuclide)"
)
LINEAR_FORMULA = BASE_FORMULA + " + structure_raw_z"
SPLINE_FORMULA = LINEAR_FORMULA + " + rcs_nl1"
SENSITIVITY_FORMULA = LINEAR_FORMULA + " + rcs4_nl1 + rcs4_nl2"
KNOT_QUANTILES = np.asarray([0.10, 0.50, 0.90], dtype=float)
SENSITIVITY_KNOT_QUANTILES = np.asarray([0.05, 0.35, 0.65, 0.95], dtype=float)
DISPLAY_QUANTILES = np.asarray([0.025, 0.975], dtype=float)
TEXT = "#29333A"
AXIS = "#66727A"
TARGETS = {
    "SSA": {
        "title": "比表面积与校正后的核素吸附性能",
        "xlabel": "比表面积（m²·g⁻¹）",
        "stem": "specific_surface_area_rcs_adjusted_response",
        "line_color": "#F3AF44",
        "fill_color": "#FCF0D5",
    },
    "O_content": {
        "title": "O含量与校正后的核素吸附性能",
        "xlabel": "O含量（%）",
        "stem": "o_content_rcs_adjusted_response",
        "line_color": "#4683B4",
        "fill_color": "#CBDDEB",
    },
}


def restricted_cubic_basis(values: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Return the nonlinear Harrell RCS term for three fixed knots."""
    x = np.asarray(values, dtype=float)
    k1, k2, k3 = np.asarray(knots, dtype=float)
    if not (k1 < k2 < k3):
        raise ValueError(f"RCS knots must be strictly increasing: {knots}")
    scale = (k3 - k1) ** 2

    def positive_cube(knot: float) -> np.ndarray:
        return np.maximum(x - knot, 0.0) ** 3

    nonlinear = (
        positive_cube(k1)
        - positive_cube(k2) * (k3 - k1) / (k3 - k2)
        + positive_cube(k3) * (k2 - k1) / (k3 - k2)
    ) / scale
    return nonlinear[:, None]


def restricted_cubic_basis_four(values: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Return the two nonlinear Harrell RCS terms for four fixed knots."""
    x = np.asarray(values, dtype=float)
    k1, k2, k3, k4 = np.asarray(knots, dtype=float)
    if not (k1 < k2 < k3 < k4):
        raise ValueError(f"Four-knot RCS knots must be strictly increasing: {knots}")
    scale = (k4 - k1) ** 2

    def positive_cube(knot: float) -> np.ndarray:
        return np.maximum(x - knot, 0.0) ** 3

    def nonlinear_term(knot: float) -> np.ndarray:
        return (
            positive_cube(knot)
            - positive_cube(k3) * (k4 - knot) / (k4 - k3)
            + positive_cube(k4) * (k3 - knot) / (k4 - k3)
        ) / scale

    return np.column_stack([nonlinear_term(k1), nonlinear_term(k2)])


def prepare_cases(
    data: pd.DataFrame,
    structure: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, object]]:
    cases = structure_cases(data, structure)
    cases["log_qe_z"] = standardize(cases["log_qe"].rename("log_qe"))
    raw = cases[structure["source"]].to_numpy(dtype=float)
    raw_mean = float(np.mean(raw))
    raw_sd = float(np.std(raw, ddof=1))
    cases["structure_raw_z"] = (raw - raw_mean) / raw_sd
    knots_raw = np.quantile(raw, KNOT_QUANTILES)
    knots_z = (knots_raw - raw_mean) / raw_sd
    sensitivity_knots_raw = np.quantile(raw, SENSITIVITY_KNOT_QUANTILES)
    sensitivity_knots_z = (sensitivity_knots_raw - raw_mean) / raw_sd
    nonlinear = restricted_cubic_basis(cases["structure_raw_z"].to_numpy(float), knots_z)
    cases["rcs_nl1"] = nonlinear[:, 0]
    sensitivity_nonlinear = restricted_cubic_basis_four(
        cases["structure_raw_z"].to_numpy(float), sensitivity_knots_z
    )
    cases["rcs4_nl1"] = sensitivity_nonlinear[:, 0]
    cases["rcs4_nl2"] = sensitivity_nonlinear[:, 1]
    display_low, display_high = np.quantile(raw, DISPLAY_QUANTILES)
    reference_raw = float(np.median(raw))
    return cases, {
        "raw_mean": raw_mean,
        "raw_sd": raw_sd,
        "knots_raw": knots_raw,
        "knots_z": knots_z,
        "sensitivity_knots_raw": sensitivity_knots_raw,
        "sensitivity_knots_z": sensitivity_knots_z,
        "display_low": float(display_low),
        "display_high": float(display_high),
        "reference_raw": reference_raw,
    }


def spline_effect(
    result,
    structure_z: np.ndarray,
    nonlinear_basis: np.ndarray,
    reference_z: float,
    reference_nonlinear: np.ndarray,
) -> np.ndarray:
    parameters = result.fe_params
    effect = (
        float(parameters["structure_raw_z"]) * structure_z
        + float(parameters["rcs_nl1"]) * nonlinear_basis[:, 0]
    )
    reference_effect = (
        float(parameters["structure_raw_z"]) * reference_z
        + float(parameters["rcs_nl1"]) * float(reference_nonlinear[0])
    )
    return effect - reference_effect


def analyze_target(
    data: pd.DataFrame,
    structure: dict[str, str],
    grid_points: int,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
    cases, transform = prepare_cases(data, structure)
    linear, linear_optimizer = fit_mixed_model(LINEAR_FORMULA, cases)
    spline, spline_optimizer = fit_mixed_model(SPLINE_FORMULA, cases)
    sensitivity, sensitivity_optimizer = fit_mixed_model(SENSITIVITY_FORMULA, cases)
    nonlinear_df = len(spline.fe_params) - len(linear.fe_params)
    likelihood_ratio = max(0.0, 2.0 * (float(spline.llf) - float(linear.llf)))
    nonlinear_p = float(chi2.sf(likelihood_ratio, df=nonlinear_df))
    sensitivity_df = len(sensitivity.fe_params) - len(linear.fe_params)
    sensitivity_likelihood_ratio = max(
        0.0, 2.0 * (float(sensitivity.llf) - float(linear.llf))
    )
    sensitivity_p = float(chi2.sf(sensitivity_likelihood_ratio, df=sensitivity_df))

    grid = np.linspace(transform["display_low"], transform["display_high"], grid_points)
    grid_z = (grid - transform["raw_mean"]) / transform["raw_sd"]
    grid_nonlinear = restricted_cubic_basis(grid_z, transform["knots_z"])
    reference_z = (transform["reference_raw"] - transform["raw_mean"]) / transform["raw_sd"]
    reference_nonlinear = restricted_cubic_basis(
        np.asarray([reference_z]), transform["knots_z"]
    )[0]
    adjusted = spline_effect(
        spline,
        grid_z,
        grid_nonlinear,
        reference_z,
        reference_nonlinear,
    )
    curve = pd.DataFrame(
        {
            "key": structure["key"],
            "x": grid,
            "structure_raw_z": grid_z,
            "rcs_nl1": grid_nonlinear[:, 0],
            "adjusted_standardized_log_qe": adjusted,
        }
    )
    metadata = {
        "key": structure["key"],
        "source_column": structure["source"],
        "structure_scale": "raw_then_standardized",
        "rcs_knot_quantiles": "10%,50%,90%",
        "knot_1_raw": float(transform["knots_raw"][0]),
        "knot_2_raw": float(transform["knots_raw"][1]),
        "knot_3_raw": float(transform["knots_raw"][2]),
        "display_quantiles": "2.5%-97.5%",
        "reference_raw_median": float(transform["reference_raw"]),
        "n": len(cases),
        "unique_structure_n": int(cases[structure["source"]].nunique()),
        "literature_n": int(cases["literature_id"].nunique()),
        "material_n": int(cases["material_id"].nunique()),
        "nuclide_n": int(cases["nuclide"].nunique()),
        "linear_llf": float(linear.llf),
        "spline_llf": float(spline.llf),
        "linear_aic": float(linear.aic),
        "spline_aic": float(spline.aic),
        "linear_bic": float(linear.bic),
        "spline_bic": float(spline.bic),
        "nonlinear_likelihood_ratio": likelihood_ratio,
        "nonlinear_df": nonlinear_df,
        "nonlinear_p": nonlinear_p,
        "sensitivity_4knot_likelihood_ratio": sensitivity_likelihood_ratio,
        "sensitivity_4knot_df": sensitivity_df,
        "sensitivity_4knot_p": sensitivity_p,
        "sensitivity_4knot_aic": float(sensitivity.aic),
        "sensitivity_4knot_optimizer": sensitivity_optimizer,
        "linear_converged": bool(linear.converged),
        "spline_converged": bool(spline.converged),
        "linear_optimizer": linear_optimizer,
        "spline_optimizer": spline_optimizer,
    }
    prediction = {
        "grid_z": grid_z,
        "grid_nonlinear": grid_nonlinear,
        "reference_z": reference_z,
        "reference_nonlinear": reference_nonlinear,
        "fixed_mean": np.einsum(
            "ij,j->i",
            np.asarray(spline.model.exog, dtype=np.float64),
            np.asarray(spline.fe_params, dtype=np.float64),
        ),
        "literature_variance": float(spline.cov_re.iloc[0, 0]),
        "material_variance": float(spline.vcomp[0]),
        "residual_variance": float(spline.scale),
    }
    return metadata, curve, cases, prediction


def bootstrap_curves(
    key: str,
    cases: pd.DataFrame,
    prediction: dict[str, object],
    iterations: int,
    seed: int,
) -> tuple[str, list[list[float]], int]:
    rng = np.random.default_rng(seed)
    curves: list[list[float]] = []
    failures = 0
    for _ in range(iterations):
        try:
            literature_ids = cases["literature_id"].drop_duplicates().to_numpy()
            material_ids = cases["material_id"].drop_duplicates().to_numpy()
            literature_effects = dict(
                zip(
                    literature_ids,
                    rng.normal(
                        0.0,
                        math.sqrt(max(0.0, float(prediction["literature_variance"]))),
                        len(literature_ids),
                    ),
                )
            )
            material_effects = dict(
                zip(
                    material_ids,
                    rng.normal(
                        0.0,
                        math.sqrt(max(0.0, float(prediction["material_variance"]))),
                        len(material_ids),
                    ),
                )
            )
            sampled = cases.copy()
            sampled["log_qe_z"] = (
                np.asarray(prediction["fixed_mean"], dtype=float)
                + sampled["literature_id"].map(literature_effects).to_numpy(float)
                + sampled["material_id"].map(material_effects).to_numpy(float)
                + rng.normal(
                    0.0,
                    math.sqrt(max(0.0, float(prediction["residual_variance"]))),
                    len(sampled),
                )
            )
            result = fit_bootstrap_model(SPLINE_FORMULA, sampled)
            curve = spline_effect(
                result,
                np.asarray(prediction["grid_z"], dtype=float),
                np.asarray(prediction["grid_nonlinear"], dtype=float),
                float(prediction["reference_z"]),
                np.asarray(prediction["reference_nonlinear"], dtype=float),
            )
            if np.isfinite(curve).all():
                curves.append(curve.tolist())
            else:
                failures += 1
        except Exception:
            failures += 1
    return key, curves, failures


def p_text(value: float) -> str:
    if value < 0.001:
        return "P<0.001"
    return f"P={value:.3f}"


def draw_curve(
    metadata: dict[str, object],
    curve: pd.DataFrame,
    cases: pd.DataFrame,
    structure: dict[str, str],
    output_stem: Path,
) -> None:
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
    target = TARGETS[str(structure["key"])]
    line_color = str(target["line_color"])
    fill_color = str(target["fill_color"])
    x = curve["x"].to_numpy(float)
    y = curve["adjusted_standardized_log_qe"].to_numpy(float)
    low = curve["bootstrap_ci_low"].to_numpy(float)
    high = curve["bootstrap_ci_high"].to_numpy(float)
    raw = cases[structure["source"]].to_numpy(float)
    rug = raw[(raw >= x.min()) & (raw <= x.max())]

    fig, ax = plt.subplots(figsize=(120 / 25.4, 94 / 25.4), facecolor="white")
    ax.fill_between(x, low, high, color=fill_color, alpha=0.95, linewidth=0, zorder=1)
    ax.plot(x, y, color=line_color, linewidth=1.7, zorder=3)
    ax.axhline(0.0, color=AXIS, linewidth=0.8, linestyle=(0, (3, 3)), zorder=2)
    ax.plot(
        rug,
        np.full_like(rug, 0.025),
        linestyle="none",
        marker="|",
        markersize=4.0,
        markeredgewidth=0.65,
        color=line_color,
        alpha=0.28,
        transform=ax.get_xaxis_transform(),
        zorder=4,
        clip_on=True,
    )
    ax.text(
        0.018,
        0.965,
        f"非线性检验：{p_text(float(metadata['nonlinear_p']))}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=7.0,
        color=TEXT,
    )
    ax.text(
        0.985,
        0.965,
        f"n={int(metadata['n'])}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=7.0,
        color=TEXT,
    )
    ax.set_title(str(target["title"]), loc="left", fontproperties=font, fontsize=10.2, pad=14)
    ax.set_xlabel(str(target["xlabel"]), fontproperties=font, fontsize=8.5, labelpad=8)
    ax.set_ylabel(
        "校正后的核素吸附性能\n（相对中位结构水平，标准化 log Qe）",
        fontproperties=font,
        fontsize=8.0,
        labelpad=9,
    )
    ax.set_xlim(float(x.min()), float(x.max()))
    y_min = float(np.min(low))
    y_max = float(np.max(high))
    y_span = max(0.1, y_max - y_min)
    ax.set_ylim(y_min - y_span * 0.10, y_max + y_span * 0.14)
    ax.yaxis.grid(True, color=fill_color, linewidth=0.75, zorder=0)
    ax.xaxis.grid(False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color(AXIS)
    ax.tick_params(axis="both", labelsize=7.4, length=3, color=AXIS)
    fig.text(
        0.14,
        0.018,
        "限制性立方样条节点位于10%、50%、90%分位数；阴影为混合模型参数bootstrap点位95% CI；底部短线表示样本分布。",
        ha="left",
        va="bottom",
        fontproperties=font,
        fontsize=5.5,
        color=AXIS,
    )
    fig.subplots_adjust(left=0.22, right=0.97, top=0.84, bottom=0.22)
    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(output_stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_method(path: Path, metadata: list[dict[str, object]]) -> None:
    lines = "\n".join(
        f"- {'比表面积' if item['key'] == 'SSA' else 'O含量'}：n={item['n']}，独立取值={item['unique_structure_n']}，文献={item['literature_n']}；"
        f"非线性LRT χ²({item['nonlinear_df']})={item['nonlinear_likelihood_ratio']:.3f}，"
        f"P={item['nonlinear_p']:.6g}；AIC（线性/样条）={item['linear_aic']:.3f}/{item['spline_aic']:.3f}；"
        f"四节点敏感性P={item['sensitivity_4knot_p']:.6g}；"
        f"bootstrap成功={item['bootstrap_success']}/{item['bootstrap_attempts']}。"
        for item in metadata
    )
    text = f"""# 比表面积与O含量的限制性立方样条非线性检验

- 响应变量：平衡吸附量取自然对数后标准化。
- 结构变量：比表面积和O含量均保留原始尺度，再进行线性标准化；未对结构变量取对数。
- 样条：三节点限制性立方样条，预先固定于各结构变量的10%、50%、90%分位数；包含一个线性项和一个非线性项。该保守自由度设置用于降低O含量仅有11个独立取值时的过拟合风险。
- 非线性检验：使用最大似然拟合，比较仅含结构线性项的混合模型与加入一个非线性样条项的混合模型；似然比检验自由度为1。
- 控制变量：pH（线性与二次项）、初始浓度自然对数（线性与二次项）、固液比自然对数、吸附温度和核素类型。
- 随机效应：文献随机截距，以及嵌套于文献的材料随机截距。
- 曲线：显示结构变量第2.5%至97.5%分位数范围，并以结构变量中位数为零参考；曲线表示混合模型固定效应中的结构偏效应，不代表因果关系。
- 95% CI：根据完整样条混合模型估计的文献、材料和残差方差进行参数bootstrap，保留原始协变量及层级结构，每次重新拟合完整模型；图中为逐点2.5%和97.5%分位数。采用该方法是因为O含量仅有7个文献簇，直接整群重抽样会频繁丢失关键文献并产生不可识别的极端曲线。
- 敏感性分析：另以5%、35%、65%、95%分位数的四节点限制性立方样条重复非线性检验，用于判断显著性结论是否依赖主分析的三节点设置。
- 注意：O含量仅来自少量文献与有限独立取值，非线性检验及局部曲线形状需要谨慎解释，并建议在更多独立研究中验证。

## 模型结果
{lines}
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="RCS nonlinearity tests and adjusted response curves.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--grid-points", type=int, default=220)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Redraw all exports from cached curve and result files without refitting models.",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data = prepare_analysis(args.input)
    structures = [next(item for item in STRUCTURES if item["key"] == key) for key in TARGETS]
    if args.render_only:
        curve_data = pd.read_csv(args.output_dir / "structure_rcs_curves_source_data.csv")
        result_data = pd.read_csv(args.output_dir / "structure_rcs_nonlinearity_results.csv")
        for structure in structures:
            cases, _ = prepare_cases(data, structure)
            curve = curve_data.loc[curve_data["key"] == structure["key"]].copy()
            metadata = result_data.loc[result_data["key"] == structure["key"]].iloc[0].to_dict()
            draw_curve(
                metadata,
                curve,
                cases,
                structure,
                args.output_dir / str(TARGETS[structure["key"]]["stem"]),
            )
        return

    analyses: dict[str, tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]] = {}
    for structure in structures:
        analyses[structure["key"]] = analyze_target(data, structure, args.grid_points)

    workers = max(1, min(args.jobs, len(structures)))
    bootstrap_outputs: dict[str, tuple[list[list[float]], int]] = {}
    if workers == 1:
        for index, structure in enumerate(structures):
            metadata, curve, cases, prediction = analyses[structure["key"]]
            key, curves, failures = bootstrap_curves(
                structure["key"], cases, prediction, args.bootstrap, args.seed + index * 1009
            )
            bootstrap_outputs[key] = (curves, failures)
            print(f"bootstrap {key}: success={len(curves)}/{args.bootstrap}, failures={failures}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for index, structure in enumerate(structures):
                metadata, curve, cases, prediction = analyses[structure["key"]]
                future = executor.submit(
                    bootstrap_curves,
                    structure["key"],
                    cases,
                    prediction,
                    args.bootstrap,
                    args.seed + index * 1009,
                )
                futures[future] = structure["key"]
            for future in as_completed(futures):
                key, curves, failures = future.result()
                bootstrap_outputs[key] = (curves, failures)
                print(f"bootstrap {key}: success={len(curves)}/{args.bootstrap}, failures={failures}", flush=True)

    minimum_success = max(10, int(math.ceil(args.bootstrap * 0.70)))
    all_curve_rows: list[dict[str, object]] = []
    metadata_rows: list[dict[str, object]] = []
    for structure in structures:
        metadata, curve, cases, prediction = analyses[structure["key"]]
        curves, failures = bootstrap_outputs[structure["key"]]
        if len(curves) < minimum_success:
            raise RuntimeError(
                f"Too few successful bootstrap curves for {structure['key']}: {len(curves)}/{args.bootstrap}"
            )
        distribution = np.asarray(curves, dtype=float)
        curve["bootstrap_ci_low"] = np.percentile(distribution, 2.5, axis=0)
        curve["bootstrap_ci_high"] = np.percentile(distribution, 97.5, axis=0)
        metadata["bootstrap_attempts"] = args.bootstrap
        metadata["bootstrap_success"] = len(curves)
        metadata["bootstrap_failures"] = failures
        metadata["bootstrap_seed"] = args.seed
        metadata_rows.append(metadata)
        all_curve_rows.extend(curve.to_dict("records"))
        draw_curve(
            metadata,
            curve,
            cases,
            structure,
            args.output_dir / str(TARGETS[structure["key"]]["stem"]),
        )

    with (args.output_dir / "structure_rcs_curves_source_data.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_curve_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_curve_rows)
    with (args.output_dir / "structure_rcs_nonlinearity_results.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metadata_rows[0].keys()))
        writer.writeheader()
        writer.writerows(metadata_rows)
    write_method(args.output_dir / "structure_rcs_nonlinearity_method.md", metadata_rows)
    for item in metadata_rows:
        print(
            item["key"],
            f"n={item['n']}",
            f"unique={item['unique_structure_n']}",
            f"literature={item['literature_n']}",
            f"LRT={item['nonlinear_likelihood_ratio']:.3f}",
            f"df={item['nonlinear_df']}",
            f"P={item['nonlinear_p']:.6g}",
            f"AIC={item['linear_aic']:.3f}/{item['spline_aic']:.3f}",
            f"bootstrap={item['bootstrap_success']}/{item['bootstrap_attempts']}",
        )


if __name__ == "__main__":
    main()
