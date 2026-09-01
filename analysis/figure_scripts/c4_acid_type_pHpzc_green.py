from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path

from acid_group_and_factor_contribution_heatmaps import (
    GROUP_DISPLAY,
    groupwise_standardize_concentration,
    load_rows,
    select_chinese_font,
)
from adjusted_effect_panels import (
    design_matrix,
    fit_ols_hc3,
    linear_estimate,
    make_spec,
    prepare_complete_cases,
)

import matplotlib.pyplot as plt
import numpy as np


ACID_ORDER = ["H3PO4", "HNO3", "H2SO4", "HCl", "其他酸"]
GREEN_MAIN = "#67B3AD"
GREEN_LIGHT = "#EAF5E2"
GREEN_DARK = "#4C8F89"
TEXT_DARK = "#27413E"


def adjusted_means(cases: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    spec = make_spec(cases)
    x, _ = design_matrix(cases, spec)
    y = np.asarray([row["y"] for row in cases], dtype=float)
    model = fit_ols_hc3(x, y)
    observed = Counter(str(row["acid_type"]) for row in cases)
    levels = [level for level in ACID_ORDER if level in set(spec["acid_levels"])]
    records = []
    for level in levels:
        scenario, _ = design_matrix(cases, spec, {"acid_type": level})
        estimate, lower, upper = linear_estimate(np.mean(scenario, axis=0), model)
        records.append(
            {
                "acid_type": level,
                "observed_n": observed[level],
                "adjusted_mean": estimate,
                "ci_low": lower,
                "ci_high": upper,
            }
        )
    return records, model


def draw_figure(path_stem: Path, records: list[dict[str, object]]) -> None:
    font = select_chinese_font()
    plt.rcParams["font.family"] = font.get_name()
    fig = plt.figure(figsize=(105 / 25.4, 92 / 25.4))
    ax = fig.add_axes([0.30, 0.22, 0.65, 0.68])
    y_positions = np.arange(len(records))[::-1]
    estimates = np.asarray([record["adjusted_mean"] for record in records])
    lower = np.asarray([record["ci_low"] for record in records])
    upper = np.asarray([record["ci_high"] for record in records])

    for y in y_positions[::2]:
        ax.axhspan(y - 0.46, y + 0.46, color=GREEN_LIGHT, alpha=0.35, linewidth=0, zorder=0)
    ax.errorbar(
        estimates,
        y_positions,
        xerr=np.vstack([estimates - lower, upper - estimates]),
        fmt="o",
        color=GREEN_DARK,
        ecolor=GREEN_MAIN,
        elinewidth=1.35,
        capsize=2.7,
        markersize=5.0,
        markerfacecolor=GREEN_MAIN,
        markeredgecolor=GREEN_DARK,
        markeredgewidth=0.8,
        zorder=3,
    )
    ax.set_yticks(y_positions)
    ax.set_yticklabels(
        [f"{GROUP_DISPLAY[record['acid_type']]}\n(n = {record['observed_n']})" for record in records],
        fontproperties=font,
        fontsize=7,
        linespacing=1.0,
    )
    ax.set_xlabel("校正后零电荷点pH边际均值", fontproperties=font, fontsize=7.3)
    ax.set_title("酸类型 → 零电荷点pH", fontproperties=font, fontsize=8.5, loc="left", pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#7A8583")
    ax.spines["bottom"].set_color("#7A8583")
    ax.tick_params(axis="both", length=3, width=0.7, colors=TEXT_DARK, labelsize=7)
    ax.grid(axis="x", color=GREEN_LIGHT, linewidth=0.9, alpha=0.95)
    ax.set_axisbelow(True)
    ax.grid(axis="y", visible=False)

    finite = np.concatenate([lower, upper])
    span = float(np.max(finite) - np.min(finite))
    padding = max(0.2, span * 0.08)
    ax.set_xlim(float(np.min(finite) - padding), float(np.max(finite) + padding))
    fig.text(
        0.58,
        0.065,
        "点为校正后边际均值，误差线为95%置信区间。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=6.2,
        color=TEXT_DARK,
    )

    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(path_stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_source(path: Path, records: list[dict[str, object]], response_n: int, model: dict[str, object]) -> None:
    fields = [
        "response",
        "response_n",
        "model_r2",
        "acid_type",
        "observed_n",
        "adjusted_mean",
        "ci_low",
        "ci_high",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "response": "pH_pzc",
                    "response_n": response_n,
                    "model_r2": model["r2"],
                    **record,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw adjusted acid-type marginal means for pH_pzc.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows, _ = load_rows(args.input)
    groupwise_standardize_concentration(rows)
    cases = prepare_complete_cases(rows, "pH_pzc")
    records, model = adjusted_means(cases)
    stem = args.output_dir / "c4_acid_type_pHpzc_green"
    draw_figure(stem, records)
    write_source(args.output_dir / "c4_acid_type_pHpzc_adjusted_marginal_means.csv", records, len(cases), model)
    method = f"""# c4 酸类型到 pH_pzc 的校正后边际均值

- 完整案例 n={len(cases)}；模型 R²={model['r2']:.3f}。
- pH_pzc 在原始 pH 尺度使用多因素 OLS 模型，不进行额外对数变换。
- 模型控制同类酸内标准化浓度 C*、酸处理时间（3自由度自然三次样条）、酸处理温度、改性顺序、热解温度和原料类别。
- 边际均值通过将酸类型依次设为 H3PO4、HNO3、H2SO4、HCl 和其他酸，再对其余协变量的完整案例分布取平均得到。
- 95%CI 使用 HC3 异方差稳健协方差矩阵。
- 配色：#67B3AD / #EAF5E2。
"""
    (args.output_dir / "c4_acid_type_pHpzc_method.md").write_text(method, encoding="utf-8")
    print(f"response_n={len(cases)}")
    print(f"model_r2={model['r2']}")
    print(f"records={records}")
    print(f"output_stem={stem}")


if __name__ == "__main__":
    main()
