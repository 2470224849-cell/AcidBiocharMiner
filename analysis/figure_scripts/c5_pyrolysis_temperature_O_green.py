from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from acid_group_and_factor_contribution_heatmaps import (
    groupwise_standardize_concentration,
    load_rows,
    select_chinese_font,
)
import adjusted_effect_panels as adjusted

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


GREEN_MAIN = "#67B3AD"
GREEN_LIGHT = "#EAF5E2"
GREEN_DARK = "#4C8F89"
TEXT_DARK = "#27413E"
AXIS_GREY = "#7A8583"


def adjusted_curve(
    cases: list[dict[str, object]],
) -> tuple[list[dict[str, float]], dict[str, object], dict[str, object]]:
    spec, model, names = adjusted.fit_response(cases)
    temperatures = np.asarray([row["pyrolysis_temperature"] for row in cases], dtype=float)
    low, high = float(np.min(temperatures)), float(np.max(temperatures))
    grid = np.linspace(low, high, 180)

    records: list[dict[str, float]] = []
    for temperature in grid:
        scenario, _ = adjusted.design_matrix(
            cases,
            spec,
            {"pyrolysis_temperature": float(temperature)},
        )
        estimate_link, lower_link, upper_link = adjusted.linear_estimate(
            np.mean(scenario, axis=0), model
        )
        records.append(
            {
                "pyrolysis_temperature_c": float(temperature),
                "adjusted_geometric_mean": math.exp(estimate_link),
                "ci_low": math.exp(lower_link),
                "ci_high": math.exp(upper_link),
            }
        )

    temperature_index = names.index("pyrolysis_temperature")
    beta = float(model["beta"][temperature_index])
    se = math.sqrt(max(0.0, float(model["covariance"][temperature_index, temperature_index])))
    temperature_sd = float(spec["numeric"]["pyrolysis_temperature"][1])
    scale = 100.0 / temperature_sd
    change_100 = 100.0 * (math.exp(beta * scale) - 1.0)
    change_100_low = 100.0 * (math.exp((beta - 1.96 * se) * scale) - 1.0)
    change_100_high = 100.0 * (math.exp((beta + 1.96 * se) * scale) - 1.0)

    diagnostics = {
        "response_n": len(cases),
        "model_r2": float(model["r2"]),
        "residual_df": int(model["residual_df"]),
        "display_low_c": low,
        "display_high_c": high,
        "temperature_sd_c": temperature_sd,
        "percent_change_per_100c": change_100,
        "percent_change_per_100c_ci_low": change_100_low,
        "percent_change_per_100c_ci_high": change_100_high,
    }
    return records, diagnostics, model


def draw_figure(
    path_stem: Path,
    records: list[dict[str, float]],
    cases: list[dict[str, object]],
    diagnostics: dict[str, object],
) -> None:
    font = select_chinese_font()
    mpl.rcParams.update(
        {
            "font.family": font.get_name(),
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "axes.linewidth": 0.8,
            "axes.unicode_minus": False,
        }
    )

    fig = plt.figure(figsize=(105 / 25.4, 92 / 25.4), facecolor="white")
    ax = fig.add_axes([0.19, 0.23, 0.76, 0.66])

    x = np.asarray([record["pyrolysis_temperature_c"] for record in records])
    estimate = np.asarray([record["adjusted_geometric_mean"] for record in records])
    lower = np.asarray([record["ci_low"] for record in records])
    upper = np.asarray([record["ci_high"] for record in records])

    ax.fill_between(x, lower, upper, color=GREEN_LIGHT, linewidth=0, alpha=1.0, zorder=1)
    ax.plot(x, estimate, color=GREEN_DARK, linewidth=2.0, zorder=3)

    y_low = max(0.0, float(np.min(lower)) - 0.06 * float(np.ptp(upper)))
    y_high = float(np.max(upper)) + 0.06 * float(np.ptp(upper))
    ax.set_ylim(y_low, y_high)
    rug_y = y_low + 0.018 * (y_high - y_low)
    observed_t = np.asarray([row["pyrolysis_temperature"] for row in cases], dtype=float)
    ax.plot(
        observed_t,
        np.full(observed_t.size, rug_y),
        "|",
        color=GREEN_MAIN,
        markersize=4.0,
        markeredgewidth=0.65,
        alpha=0.48,
        clip_on=True,
        zorder=4,
    )

    ax.set_xlim(float(x.min()), float(x.max()))
    ax.set_xticks(np.arange(200, 801, 100))
    ax.set_xlabel("热解温度（°C）", fontproperties=font, fontsize=7.5, labelpad=5)
    ax.set_ylabel("校正后 O 含量（%）", fontproperties=font, fontsize=7.5, labelpad=5)
    ax.set_title("热解温度 → O含量", fontproperties=font, fontsize=8.7, loc="left", pad=8)
    ax.text(
        0.98,
        0.96,
        f"n = {diagnostics['response_n']}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=6.6,
        color=TEXT_DARK,
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(AXIS_GREY)
    ax.spines["bottom"].set_color(AXIS_GREY)
    ax.tick_params(axis="both", length=3, width=0.7, colors=TEXT_DARK, labelsize=7)
    ax.grid(axis="both", color=GREEN_LIGHT, linewidth=0.8, alpha=0.95)
    ax.set_axisbelow(True)

    fig.text(
        0.57,
        0.065,
        "实线为模型校正响应，阴影为95%置信区间，短线表示实际样本分布。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=6.1,
        color=TEXT_DARK,
    )

    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(path_stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_source(
    path: Path,
    records: list[dict[str, float]],
    diagnostics: dict[str, object],
) -> None:
    fields = [
        "response",
        "response_n",
        "model_r2",
        "pyrolysis_temperature_c",
        "adjusted_geometric_mean",
        "ci_low",
        "ci_high",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "response": "O_content_pct",
                    "response_n": diagnostics["response_n"],
                    "model_r2": diagnostics["model_r2"],
                    **record,
                }
            )


def write_method(path: Path, diagnostics: dict[str, object]) -> None:
    method = f"""# c5 热解温度到 O 含量的校正后效应

- 完整案例 n={diagnostics['response_n']}；模型 R²={diagnostics['model_r2']:.3f}，残差自由度={diagnostics['residual_df']}。
- O 含量在自然对数尺度使用多因素 OLS 模型，预测值及 95%CI 反变换回原始百分比尺度，因此曲线表示校正后的几何均值。
- 模型同时控制酸类型、同类酸内标准化浓度 C*、酸处理时间（3 自由度自然三次样条）、酸处理温度、改性顺序和原料类别；热解温度作为线性连续项。
- 响应曲线通过将所有完整案例的热解温度依次设为实际观测范围 {diagnostics['display_low_c']:.0f}–{diagnostics['display_high_c']:.0f}°C 内的连续网格值，再对其他协变量分布的预测设计向量取平均得到。
- 95%CI 使用 HC3 异方差稳健协方差矩阵。
- 每升高 100°C，模型估计 O 含量变化 {diagnostics['percent_change_per_100c']:.1f}%（95%CI {diagnostics['percent_change_per_100c_ci_low']:.1f}% 至 {diagnostics['percent_change_per_100c_ci_high']:.1f}%）。
- 结果为观察性条件关联，不代表因果效应。
- 配色：#67B3AD / #EAF5E2。
"""
    path.write_text(method, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw the adjusted pyrolysis-temperature effect on O content.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows, _ = load_rows(args.input)
    groupwise_standardize_concentration(rows)
    adjusted.RESPONSE_COLUMNS["O_content"] = "O（%）"
    cases = adjusted.prepare_complete_cases(rows, "O_content")
    records, diagnostics, _ = adjusted_curve(cases)

    stem = args.output_dir / "c5_pyrolysis_temperature_O_green"
    draw_figure(stem, records, cases, diagnostics)
    write_source(args.output_dir / "c5_pyrolysis_temperature_O_adjusted_curve.csv", records, diagnostics)
    write_method(args.output_dir / "c5_pyrolysis_temperature_O_method.md", diagnostics)

    print(f"response_n={diagnostics['response_n']}")
    print(f"model_r2={diagnostics['model_r2']}")
    print(f"percent_change_per_100c={diagnostics['percent_change_per_100c']}")
    print(
        "percent_change_per_100c_95ci="
        f"({diagnostics['percent_change_per_100c_ci_low']}, "
        f"{diagnostics['percent_change_per_100c_ci_high']})"
    )
    print(f"display_range=({diagnostics['display_low_c']}, {diagnostics['display_high_c']})")
    print(f"output_stem={stem}")


if __name__ == "__main__":
    main()
