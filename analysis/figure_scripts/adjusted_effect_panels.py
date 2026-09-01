from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path

from acid_group_and_factor_contribution_heatmaps import (
    GROUP_DISPLAY,
    GROUP_ORDER,
    groupwise_standardize_concentration,
    load_rows,
    select_chinese_font,
    to_float,
)

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter


MODIFICATION_ORDER = [
    "热解前酸处理",
    "酸辅助炭化/活化",
    "热解后酸处理",
    "多步酸改性",
    "酸处理结合附加功能化/负载",
    "其他/不明确",
]

BIOMASS_ORDER = [
    "农作物残余物",
    "纤维/木质纤维素残余物",
    "壳/籽类残余物",
    "果皮/果实废弃物",
    "污泥/生物固体",
    "畜禽粪便",
    "水生/其他生物质",
]

RESPONSE_COLUMNS = {
    "SSA": "比表面积（m²/g）",
    "APS": "平均孔径（nm）",
    "TPV": "总孔容（cm³/g）",
    "pH_pzc": "零电荷点 pH（pH_pzc）",
}

GREEN_DARK = "#4C8F89"
GREEN_MAIN = "#67B3AD"
GREEN_LIGHT = "#EAF5E2"
TEXT_DARK = "#203A38"
GRID = "#D9E7E2"


def prepare_complete_cases(rows: list[dict[str, object]], response: str) -> list[dict[str, object]]:
    response_column = RESPONSE_COLUMNS[response]
    complete: list[dict[str, object]] = []
    for row in rows:
        values = {
            "y": to_float(row.get(response_column)),
            "acid_concentration": to_float(row.get("酸浓度_Cstar")),
            "acid_time": to_float(row.get("酸处理时间（h）")),
            "acid_temperature": to_float(row.get("酸处理温度（°C）")),
            "pyrolysis_temperature": to_float(row.get("热解温度（°C）")),
        }
        categories = {
            "acid_type": None if row.get("酸组别") in (None, "") else str(row.get("酸组别")).strip(),
            "modification_order": None if row.get("改性组别") in (None, "") else str(row.get("改性组别")).strip(),
            "biomass_category": None if row.get("生物质组别") in (None, "") else str(row.get("生物质组别")).strip(),
        }
        if any(value is None for value in values.values()) or any(value is None for value in categories.values()):
            continue
        complete.append({**values, **categories})
    return complete


def ordered_present(preferred: list[str], observed: list[str]) -> list[str]:
    present = set(observed)
    ordered = [value for value in preferred if value in present]
    ordered.extend(sorted(present.difference(ordered)))
    return ordered


def mean_sd(values: np.ndarray) -> tuple[float, float]:
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1)) if values.size > 1 else 1.0
    return mean, sd if sd > 0 else 1.0


def natural_spline_basis(x: np.ndarray, knots: np.ndarray) -> np.ndarray:
    if knots.size != 4 or np.any(np.diff(knots) <= 0):
        raise ValueError(f"Natural spline requires four increasing knots, got {knots}")
    last = knots[-1]
    penultimate = knots[-2]

    def d(knot: float) -> np.ndarray:
        return (np.maximum(x - knot, 0.0) ** 3 - np.maximum(x - last, 0.0) ** 3) / (last - knot)

    reference = d(penultimate)
    return np.column_stack([x, d(knots[0]) - reference, d(knots[1]) - reference])


def make_spec(cases: list[dict[str, object]]) -> dict[str, object]:
    numeric = {}
    for key in ["acid_concentration", "acid_time", "acid_temperature", "pyrolysis_temperature"]:
        numeric[key] = mean_sd(np.asarray([row[key] for row in cases], dtype=float))
    time_mean, time_sd = numeric["acid_time"]
    time_z = (np.asarray([row["acid_time"] for row in cases], dtype=float) - time_mean) / time_sd
    knots = np.quantile(time_z, [0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0])
    if np.any(np.diff(knots) <= 0):
        knots = np.linspace(float(np.min(time_z)), float(np.max(time_z)), 4)
    return {
        "numeric": numeric,
        "time_knots": knots,
        "acid_levels": ordered_present(GROUP_ORDER, [str(row["acid_type"]) for row in cases]),
        "modification_levels": ordered_present(
            MODIFICATION_ORDER, [str(row["modification_order"]) for row in cases]
        ),
        "biomass_levels": ordered_present(BIOMASS_ORDER, [str(row["biomass_category"]) for row in cases]),
    }


def design_matrix(
    cases: list[dict[str, object]],
    spec: dict[str, object],
    overrides: dict[str, object] | None = None,
) -> tuple[np.ndarray, list[str]]:
    overrides = overrides or {}
    n = len(cases)
    columns = [np.ones(n)]
    names = ["intercept"]

    acid_values = [str(overrides.get("acid_type", row["acid_type"])) for row in cases]
    acid_levels = list(spec["acid_levels"])
    for level in acid_levels[1:]:
        columns.append(np.asarray([1.0 if value == level else 0.0 for value in acid_values]))
        names.append(f"acid_type[{level}]")

    numeric = dict(spec["numeric"])
    concentration = np.asarray(
        [float(overrides.get("acid_concentration", row["acid_concentration"])) for row in cases]
    )
    columns.append((concentration - numeric["acid_concentration"][0]) / numeric["acid_concentration"][1])
    names.append("acid_concentration")

    acid_time = np.asarray([float(overrides.get("acid_time", row["acid_time"])) for row in cases])
    time_z = (acid_time - numeric["acid_time"][0]) / numeric["acid_time"][1]
    spline = natural_spline_basis(time_z, np.asarray(spec["time_knots"], dtype=float))
    for index in range(spline.shape[1]):
        columns.append(spline[:, index])
        names.append(f"acid_time_spline_{index + 1}")

    acid_temperature = np.asarray(
        [float(overrides.get("acid_temperature", row["acid_temperature"])) for row in cases]
    )
    columns.append(
        (acid_temperature - numeric["acid_temperature"][0]) / numeric["acid_temperature"][1]
    )
    names.append("acid_temperature")

    modification_values = [
        str(overrides.get("modification_order", row["modification_order"])) for row in cases
    ]
    modification_levels = list(spec["modification_levels"])
    for level in modification_levels[1:]:
        columns.append(np.asarray([1.0 if value == level else 0.0 for value in modification_values]))
        names.append(f"modification_order[{level}]")

    pyrolysis_temperature = np.asarray(
        [float(overrides.get("pyrolysis_temperature", row["pyrolysis_temperature"])) for row in cases]
    )
    columns.append(
        (pyrolysis_temperature - numeric["pyrolysis_temperature"][0])
        / numeric["pyrolysis_temperature"][1]
    )
    names.append("pyrolysis_temperature")

    biomass_values = [str(overrides.get("biomass_category", row["biomass_category"])) for row in cases]
    biomass_levels = list(spec["biomass_levels"])
    for level in biomass_levels[1:]:
        columns.append(np.asarray([1.0 if value == level else 0.0 for value in biomass_values]))
        names.append(f"biomass_category[{level}]")

    return np.column_stack(columns), names


def fit_ols_hc3(x: np.ndarray, y: np.ndarray) -> dict[str, object]:
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    residuals = y - x @ beta
    rank = int(np.linalg.matrix_rank(x))
    hat = np.sum((x @ xtx_inv) * x, axis=1)
    adjusted = residuals / np.maximum(1.0 - hat, 1e-6)
    meat = x.T @ ((adjusted**2)[:, None] * x)
    covariance = xtx_inv @ meat @ xtx_inv
    sse = float(residuals @ residuals)
    sst = float(((y - np.mean(y)) ** 2).sum())
    r2 = 1.0 - sse / sst if sst > 0 else 0.0
    return {
        "beta": beta,
        "covariance": covariance,
        "rank": rank,
        "residual_df": int(y.size - rank),
        "sse": sse,
        "sst": sst,
        "r2": r2,
    }


def linear_estimate(vector: np.ndarray, model: dict[str, object]) -> tuple[float, float, float]:
    beta = np.asarray(model["beta"])
    covariance = np.asarray(model["covariance"])
    estimate = float(vector @ beta)
    variance = max(0.0, float(vector @ covariance @ vector))
    se = math.sqrt(variance)
    return estimate, estimate - 1.96 * se, estimate + 1.96 * se


def marginal_means(
    cases: list[dict[str, object]],
    spec: dict[str, object],
    model: dict[str, object],
    target: str,
    levels: list[str],
) -> list[dict[str, object]]:
    observed_counts = Counter(str(row[target]) for row in cases)
    records = []
    for level in levels:
        x_scenario, _ = design_matrix(cases, spec, {target: level})
        estimate_link, lower_link, upper_link = linear_estimate(np.mean(x_scenario, axis=0), model)
        estimate, lower, upper = math.exp(estimate_link), math.exp(lower_link), math.exp(upper_link)
        records.append(
            {
                "level": level,
                "observed_n": observed_counts[level],
                "estimate": estimate,
                "ci_low": lower,
                "ci_high": upper,
            }
        )
    return records


def partial_curve(
    cases: list[dict[str, object]],
    spec: dict[str, object],
    model: dict[str, object],
    x: np.ndarray,
    names: list[str],
) -> tuple[list[dict[str, float]], dict[str, float]]:
    records = []
    for value in x:
        x_scenario, _ = design_matrix(cases, spec, {"acid_time": float(value)})
        estimate_link, lower_link, upper_link = linear_estimate(np.mean(x_scenario, axis=0), model)
        estimate, lower, upper = math.exp(estimate_link), math.exp(lower_link), math.exp(upper_link)
        records.append({"acid_time_h": float(value), "estimate": estimate, "ci_low": lower, "ci_high": upper})

    predictions = np.asarray([record["estimate"] for record in records])
    ci_widths = np.asarray([record["ci_high"] - record["ci_low"] for record in records])
    signal_to_ci = float(np.ptp(predictions) / np.median(ci_widths)) if np.median(ci_widths) > 0 else math.inf

    time_indices = [index for index, name in enumerate(names) if name.startswith("acid_time_spline_")]
    keep = [index for index in range(len(names)) if index not in time_indices]
    x_full, _ = design_matrix(cases, spec)
    y = np.log(np.asarray([row["y"] for row in cases], dtype=float))
    reduced = fit_ols_hc3(x_full[:, keep], y)
    delta_r2 = max(0.0, (float(reduced["sse"]) - float(model["sse"])) / float(model["sst"]))
    diagnostics = {
        "curve_range": float(np.ptp(predictions)),
        "median_ci_width": float(np.median(ci_widths)),
        "signal_to_ci": signal_to_ci,
        "time_delta_r2": delta_r2,
    }
    return records, diagnostics


def fit_response(cases: list[dict[str, object]]) -> tuple[dict[str, object], dict[str, object], list[str]]:
    spec = make_spec(cases)
    x, names = design_matrix(cases, spec)
    y_raw = np.asarray([row["y"] for row in cases], dtype=float)
    if np.any(y_raw <= 0):
        raise ValueError("Log-scale adjusted effect models require positive responses")
    y = np.log(y_raw)
    model = fit_ols_hc3(x, y)
    return spec, model, names


def clean_axis(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#71837E")
    ax.spines["bottom"].set_color("#71837E")
    ax.tick_params(axis="both", length=3, width=0.7, colors=TEXT_DARK, labelsize=6.8)
    ax.grid(axis="x", color=GRID, linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)


def plot_marginal_panel(ax, records: list[dict[str, object]], panel: str, title: str, xlabel: str, labels: dict[str, str]) -> None:
    y_positions = np.arange(len(records))[::-1]
    estimates = np.asarray([record["estimate"] for record in records])
    lower = np.asarray([record["ci_low"] for record in records])
    upper = np.asarray([record["ci_high"] for record in records])
    ax.errorbar(
        estimates,
        y_positions,
        xerr=np.vstack([estimates - lower, upper - estimates]),
        fmt="o",
        color=GREEN_DARK,
        ecolor=GREEN_MAIN,
        elinewidth=1.2,
        capsize=2.5,
        markersize=4.5,
        markerfacecolor=GREEN_MAIN,
        markeredgecolor=GREEN_DARK,
        zorder=3,
    )
    ax.set_yticks(y_positions)
    ax.set_yticklabels(
        [f"{labels.get(str(record['level']), str(record['level']))}\n(n = {record['observed_n']})" for record in records],
        fontsize=6.4,
        linespacing=1.0,
    )
    ax.set_xlabel(xlabel, fontsize=7)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.set_title(title, fontsize=8, loc="left", pad=7)
    clean_axis(ax)
    ax.grid(axis="y", visible=False)


def plot_curve_panel(
    ax,
    records: list[dict[str, float]],
    cases: list[dict[str, object]],
    panel: str,
    title: str,
    ylabel: str,
) -> None:
    x = np.asarray([record["acid_time_h"] for record in records])
    estimate = np.asarray([record["estimate"] for record in records])
    lower = np.asarray([record["ci_low"] for record in records])
    upper = np.asarray([record["ci_high"] for record in records])
    ax.fill_between(x, lower, upper, color=GREEN_LIGHT, linewidth=0, zorder=1)
    ax.plot(x, estimate, color=GREEN_DARK, linewidth=1.8, zorder=2)
    ymin, ymax = ax.get_ylim()
    rug_y = ymin + 0.018 * (ymax - ymin)
    ax.plot(
        [float(row["acid_time"]) for row in cases],
        np.full(len(cases), rug_y),
        "|",
        color=GREEN_MAIN,
        markersize=3.5,
        markeredgewidth=0.6,
        alpha=0.45,
        clip_on=True,
    )
    ax.set_xlabel("酸处理时间（h）", fontsize=7)
    ax.set_ylabel(ylabel, fontsize=7)
    ax.set_title(title, fontsize=8, loc="left", pad=7)
    clean_axis(ax)
    ax.grid(axis="both", color=GRID, linewidth=0.6, alpha=0.8)


def write_marginal_csv(path: Path, panels: dict[str, dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["panel", "response", "target", "response_n", "level", "observed_n", "estimate", "ci_low", "ci_high"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for panel, payload in panels.items():
            for record in payload["records"]:
                writer.writerow(
                    {
                        "panel": panel,
                        "response": payload["response"],
                        "target": payload["target"],
                        "response_n": payload["response_n"],
                        **record,
                    }
                )


def write_curve_csv(path: Path, panels: dict[str, dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "panel",
            "response",
            "response_n",
            "retained",
            "time_delta_r2",
            "signal_to_ci",
            "acid_time_h",
            "estimate",
            "ci_low",
            "ci_high",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for panel, payload in panels.items():
            diagnostics = payload["diagnostics"]
            for record in payload["records"]:
                writer.writerow(
                    {
                        "panel": panel,
                        "response": payload["response"],
                        "response_n": payload["response_n"],
                        "retained": payload["retained"],
                        "time_delta_r2": diagnostics["time_delta_r2"],
                        "signal_to_ci": diagnostics["signal_to_ci"],
                        **record,
                    }
                )


def write_method(path: Path, model_summaries: dict[str, dict[str, object]], retain_c4: bool) -> None:
    lines = [
        "# 校正后边际均值与偏效应曲线方法",
        "",
        "- 每个响应使用与多因素贡献热图相同的完整案例数据和因素集合。",
        "- 模型同时控制酸类型、同类酸内标准化浓度 C*、酸处理时间、酸处理温度、改性顺序、热解温度和原料类别。",
        "- 正值响应在自然对数尺度建模，预测值及95%CI反变换回原始单位，因此图中边际均值为校正后的几何均值。",
        "- 酸处理时间用 3 自由度自然三次样条表示，以允许平台或非线性响应。",
        "- c1/c2 为标准化边际均值：将目标分类因素依次设为各水平，对完整案例的其他协变量分布进行平均。",
        "- c3/c4 为平均偏效应曲线：将所有案例的酸处理时间依次设为 5%–95%观测范围内的网格值，再对预测值取平均。",
        "- 95% CI 使用 OLS 的 HC3 异方差稳健协方差矩阵计算。",
        "- 所有结果均为观察性关联，不代表因果效应。",
        f"- c4 最终{'保留' if retain_c4 else '删除'}；预设保留规则为时间块 ΔR² ≥ 0.02 且曲线幅度/中位95%CI宽度 ≥ 1.00。",
        "",
        "## 模型摘要",
    ]
    for response, summary in model_summaries.items():
        lines.append(
            f"- {response}: n={summary['n']}, R²={summary['r2']:.3f}, residual df={summary['residual_df']}."
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw adjusted marginal means and acid-time partial-effect panels.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows, _ = load_rows(args.input)
    groupwise_standardize_concentration(rows)
    cases = {response: prepare_complete_cases(rows, response) for response in ["SSA", "APS", "TPV"]}
    fitted = {response: fit_response(response_cases) for response, response_cases in cases.items()}

    tpv_spec, tpv_model, tpv_names = fitted["TPV"]
    ssa_spec, ssa_model, _ = fitted["SSA"]
    aps_spec, aps_model, aps_names = fitted["APS"]

    acid_levels = list(tpv_spec["acid_levels"])
    modification_levels = list(ssa_spec["modification_levels"])
    c1_records = marginal_means(cases["TPV"], tpv_spec, tpv_model, "acid_type", acid_levels)
    c2_records = marginal_means(
        cases["SSA"], ssa_spec, ssa_model, "modification_order", modification_levels
    )

    tpv_time = np.asarray([row["acid_time"] for row in cases["TPV"]], dtype=float)
    aps_time = np.asarray([row["acid_time"] for row in cases["APS"]], dtype=float)
    c3_grid = np.linspace(float(np.quantile(tpv_time, 0.05)), float(np.quantile(tpv_time, 0.95)), 120)
    c4_grid = np.linspace(float(np.quantile(aps_time, 0.05)), float(np.quantile(aps_time, 0.95)), 120)
    c3_records, c3_diagnostics = partial_curve(cases["TPV"], tpv_spec, tpv_model, c3_grid, tpv_names)
    c4_records, c4_diagnostics = partial_curve(cases["APS"], aps_spec, aps_model, c4_grid, aps_names)
    retain_c4 = c4_diagnostics["time_delta_r2"] >= 0.02 and c4_diagnostics["signal_to_ci"] >= 1.00

    font = select_chinese_font()
    plt.rcParams["font.family"] = font.get_name()
    if retain_c4:
        fig = plt.figure(figsize=(183 / 25.4, 145 / 25.4))
        grid = fig.add_gridspec(
            2,
            2,
            width_ratios=[0.88, 1.12],
            height_ratios=[1.08, 0.92],
            left=0.17,
            right=0.97,
            top=0.93,
            bottom=0.12,
            wspace=0.70,
            hspace=0.55,
        )
        axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1]), fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1])]
    else:
        fig = plt.figure(figsize=(183 / 25.4, 145 / 25.4))
        grid = fig.add_gridspec(
            2,
            2,
            width_ratios=[0.88, 1.12],
            height_ratios=[1.05, 0.95],
            left=0.17,
            right=0.97,
            top=0.93,
            bottom=0.12,
            wspace=0.70,
            hspace=0.58,
        )
        axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1]), fig.add_subplot(grid[1, :])]

    acid_labels = {**GROUP_DISPLAY}
    modification_labels = {
        "热解前酸处理": "热解前酸处理",
        "酸辅助炭化/活化": "酸辅助炭化/活化",
        "热解后酸处理": "热解后酸处理",
        "多步酸改性": "多步酸改性",
        "酸处理结合附加功能化/负载": "酸处理结合附加\n功能化/负载",
        "其他/不明确": "其他/不明确",
    }
    plot_marginal_panel(
        axes[0], c1_records, "c1", "酸类型 → 总孔容", "校正后总孔容（cm³ g⁻¹，对数刻度）", acid_labels
    )
    plot_marginal_panel(
        axes[1], c2_records, "c2", "改性顺序 → 比表面积", "校正后比表面积（m² g⁻¹，对数刻度）", modification_labels
    )
    plot_curve_panel(
        axes[2], c3_records, cases["TPV"], "c3", "酸处理时间 → 总孔容", "校正后总孔容（cm³ g⁻¹）"
    )
    if retain_c4:
        plot_curve_panel(
            axes[3], c4_records, cases["APS"], "c4", "酸处理时间 → 平均孔径", "校正后平均孔径（nm）"
        )

    fig.text(
        0.57,
        0.035,
        "点和实线为校正后边际几何均值；误差线和阴影为95%置信区间；短线表示样本时间分布。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=6.3,
        color="#50615D",
    )

    stem_name = "adjusted_effect_panels_c1_c4" if retain_c4 else "adjusted_effect_panels_c1_c3"
    stem = args.output_dir / stem_name
    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    marginal_panels = {
        "c1": {"response": "TPV", "target": "acid_type", "response_n": len(cases["TPV"]), "records": c1_records},
        "c2": {
            "response": "SSA",
            "target": "modification_order",
            "response_n": len(cases["SSA"]),
            "records": c2_records,
        },
    }
    curve_panels = {
        "c3": {
            "response": "TPV",
            "response_n": len(cases["TPV"]),
            "records": c3_records,
            "diagnostics": c3_diagnostics,
            "retained": True,
        },
        "c4": {
            "response": "APS",
            "response_n": len(cases["APS"]),
            "records": c4_records,
            "diagnostics": c4_diagnostics,
            "retained": retain_c4,
        },
    }
    write_marginal_csv(args.output_dir / "adjusted_marginal_means_source_data.csv", marginal_panels)
    write_curve_csv(args.output_dir / "acid_time_partial_effect_source_data.csv", curve_panels)
    model_summaries = {
        response: {
            "n": len(cases[response]),
            "r2": fitted[response][1]["r2"],
            "residual_df": fitted[response][1]["residual_df"],
        }
        for response in ["SSA", "APS", "TPV"]
    }
    write_method(args.output_dir / "adjusted_effect_model_method.md", model_summaries, retain_c4)

    print(f"model_summaries={model_summaries}")
    print(f"c1={c1_records}")
    print(f"c2={c2_records}")
    print(f"c3_diagnostics={c3_diagnostics}")
    print(f"c4_diagnostics={c4_diagnostics}")
    print(f"retain_c4={retain_c4}")
    print(f"output_stem={stem}")


if __name__ == "__main__":
    main()
