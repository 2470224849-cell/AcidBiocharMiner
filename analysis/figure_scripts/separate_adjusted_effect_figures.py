from __future__ import annotations

import argparse
import csv
from pathlib import Path

from acid_group_and_factor_contribution_heatmaps import (
    GROUP_DISPLAY,
    groupwise_standardize_concentration,
    load_rows,
    select_chinese_font,
)
from adjusted_effect_panels import (
    marginal_means,
    partial_curve,
    prepare_complete_cases,
    fit_response,
)

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter


PALETTES = {
    "orange": {"main": "#F3AF44", "light": "#FCF0D5", "dark": "#B97A1C", "text": "#4A3821"},
    "blue": {"main": "#4683B4", "light": "#CBDDEB", "dark": "#2E628B", "text": "#243A4B"},
}

MODIFICATION_LABELS = {
    "热解前酸处理": "热解前酸处理",
    "酸辅助炭化/活化": "酸辅助炭化/活化",
    "热解后酸处理": "热解后酸处理",
    "多步酸改性": "多步酸改性",
    "酸处理结合附加功能化/负载": "酸处理结合附加\n功能化/负载",
    "其他/不明确": "其他/不明确",
}


def style_axis(ax, palette: dict[str, str], grid_axis: str = "x") -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#7A8583")
    ax.spines["bottom"].set_color("#7A8583")
    ax.tick_params(axis="both", length=3, width=0.7, colors=palette["text"], labelsize=7)
    ax.grid(axis=grid_axis, color=palette["light"], linewidth=0.9, alpha=0.85)
    ax.set_axisbelow(True)


def save_figure(fig, stem: Path) -> None:
    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def draw_dot_figure(
    records: list[dict[str, object]],
    palette: dict[str, str],
    title: str,
    xlabel: str,
    labels: dict[str, str],
    figure_mm: tuple[float, float],
    left: float,
    stem: Path,
    font,
) -> None:
    fig = plt.figure(figsize=(figure_mm[0] / 25.4, figure_mm[1] / 25.4))
    ax = fig.add_axes([left, 0.22, 0.95 - left, 0.68])
    y_positions = np.arange(len(records))[::-1]
    estimates = np.asarray([record["estimate"] for record in records])
    lower = np.asarray([record["ci_low"] for record in records])
    upper = np.asarray([record["ci_high"] for record in records])

    for y in y_positions[::2]:
        ax.axhspan(y - 0.46, y + 0.46, color=palette["light"], alpha=0.24, linewidth=0, zorder=0)
    ax.errorbar(
        estimates,
        y_positions,
        xerr=np.vstack([estimates - lower, upper - estimates]),
        fmt="o",
        color=palette["dark"],
        ecolor=palette["main"],
        elinewidth=1.35,
        capsize=2.7,
        markersize=5.0,
        markerfacecolor=palette["main"],
        markeredgecolor=palette["dark"],
        markeredgewidth=0.8,
        zorder=3,
    )
    ax.set_yticks(y_positions)
    ax.set_yticklabels(
        [f"{labels.get(str(record['level']), str(record['level']))}\n(n = {record['observed_n']})" for record in records],
        fontproperties=font,
        fontsize=7,
        linespacing=1.0,
    )
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.set_xlabel(xlabel, fontproperties=font, fontsize=7.3)
    ax.set_title(title, fontproperties=font, fontsize=8.5, loc="left", pad=8)
    style_axis(ax, palette, "x")
    ax.grid(axis="y", visible=False)
    fig.text(
        0.58,
        0.065,
        "点为校正后边际几何均值，误差线为95%置信区间；横轴为对数刻度。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=6.2,
        color=palette["text"],
    )
    save_figure(fig, stem)


def draw_curve_figure(
    records: list[dict[str, float]],
    cases: list[dict[str, object]],
    palette: dict[str, str],
    stem: Path,
    font,
) -> None:
    fig = plt.figure(figsize=(130 / 25.4, 92 / 25.4))
    ax = fig.add_axes([0.16, 0.24, 0.80, 0.65])
    x = np.asarray([record["acid_time_h"] for record in records])
    estimate = np.asarray([record["estimate"] for record in records])
    lower = np.asarray([record["ci_low"] for record in records])
    upper = np.asarray([record["ci_high"] for record in records])
    ax.fill_between(x, lower, upper, color=palette["light"], linewidth=0, zorder=1)
    ax.plot(x, estimate, color=palette["main"], linewidth=2.0, zorder=2)
    ymin, ymax = ax.get_ylim()
    rug_y = ymin + 0.02 * (ymax - ymin)
    ax.plot(
        [float(row["acid_time"]) for row in cases],
        np.full(len(cases), rug_y),
        "|",
        color=palette["main"],
        markersize=4.0,
        markeredgewidth=0.7,
        alpha=0.50,
        clip_on=True,
    )
    ax.set_xlabel("酸处理时间（h）", fontproperties=font, fontsize=7.3)
    ax.set_ylabel("校正后总孔容（cm³ g⁻¹）", fontproperties=font, fontsize=7.3)
    ax.set_title("酸处理时间 → 总孔容", fontproperties=font, fontsize=8.5, loc="left", pad=8)
    style_axis(ax, palette, "both")
    fig.text(
        0.58,
        0.065,
        "实线为校正后边际几何均值，阴影为95%置信区间；短线表示样本时间分布。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=6.2,
        color=palette["text"],
    )
    save_figure(fig, stem)


def write_sources(
    output_dir: Path,
    c1_records: list[dict[str, object]],
    c2_records: list[dict[str, object]],
    c3_records: list[dict[str, float]],
    response_n: dict[str, int],
) -> None:
    marginal_path = output_dir / "separate_adjusted_marginal_means_source_data.csv"
    with marginal_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["panel", "response", "target", "response_n", "level", "observed_n", "estimate", "ci_low", "ci_high"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for panel, response, target, records in [
            ("c1", "TPV", "acid_type", c1_records),
            ("c2", "SSA", "modification_order", c2_records),
        ]:
            for record in records:
                writer.writerow(
                    {
                        "panel": panel,
                        "response": response,
                        "target": target,
                        "response_n": response_n[response],
                        **record,
                    }
                )

    curve_path = output_dir / "separate_TPV_time_partial_effect_source_data.csv"
    with curve_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["panel", "response", "response_n", "acid_time_h", "estimate", "ci_low", "ci_high"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in c3_records:
            writer.writerow({"panel": "c3", "response": "TPV", "response_n": response_n["TPV"], **record})


def write_method(path: Path, response_n: dict[str, int]) -> None:
    text = f"""# 三张独立校正效应图方法

- c1：酸类型对 TPV 的校正后边际几何均值及 95%CI，n={response_n['TPV']}。
- c2：改性顺序对 SSA 的校正后边际几何均值及 95%CI，n={response_n['SSA']}。
- c3：酸处理时间对 TPV 的自然三次样条偏效应曲线及 95%CI，n={response_n['TPV']}。
- 模型在自然对数响应尺度拟合，并控制酸类型、同类酸内标准化浓度、酸处理时间、酸处理温度、改性顺序、热解温度和原料类别。
- 95%CI 使用 HC3 异方差稳健协方差矩阵；结果反变换回原始单位。
- c1/c2 使用对数横轴，以完整显示稀疏类别的宽置信区间。
- 每张图均同时输出橘色版（#F3AF44 / #FCF0D5）和蓝色版（#4683B4 / #CBDDEB）。
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export c1, c2, and c3 as separate orange and blue figures.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows, _ = load_rows(args.input)
    groupwise_standardize_concentration(rows)
    cases = {response: prepare_complete_cases(rows, response) for response in ["SSA", "TPV"]}
    ssa_spec, ssa_model, _ = fit_response(cases["SSA"])
    tpv_spec, tpv_model, tpv_names = fit_response(cases["TPV"])

    c1_records = marginal_means(
        cases["TPV"], tpv_spec, tpv_model, "acid_type", list(tpv_spec["acid_levels"])
    )
    c2_records = marginal_means(
        cases["SSA"], ssa_spec, ssa_model, "modification_order", list(ssa_spec["modification_levels"])
    )
    time = np.asarray([row["acid_time"] for row in cases["TPV"]], dtype=float)
    grid = np.linspace(float(np.quantile(time, 0.05)), float(np.quantile(time, 0.95)), 120)
    c3_records, _ = partial_curve(cases["TPV"], tpv_spec, tpv_model, grid, tpv_names)

    font = select_chinese_font()
    plt.rcParams["font.family"] = font.get_name()
    for palette_name, palette in PALETTES.items():
        draw_dot_figure(
            c1_records,
            palette,
            "酸类型 → 总孔容",
            "校正后总孔容（cm³ g⁻¹，对数刻度）",
            GROUP_DISPLAY,
            (105, 92),
            0.30,
            args.output_dir / f"c1_acid_type_TPV_{palette_name}",
            font,
        )
        draw_dot_figure(
            c2_records,
            palette,
            "改性顺序 → 比表面积",
            "校正后比表面积（m² g⁻¹，对数刻度）",
            MODIFICATION_LABELS,
            (130, 102),
            0.38,
            args.output_dir / f"c2_modification_order_SSA_{palette_name}",
            font,
        )
        draw_curve_figure(
            c3_records,
            cases["TPV"],
            palette,
            args.output_dir / f"c3_acid_time_TPV_{palette_name}",
            font,
        )

    response_n = {response: len(response_cases) for response, response_cases in cases.items()}
    write_sources(args.output_dir, c1_records, c2_records, c3_records, response_n)
    write_method(args.output_dir / "separate_adjusted_effect_figures_method.md", response_n)
    print(f"response_n={response_n}")
    print(f"c1={c1_records}")
    print(f"c2={c2_records}")
    print(f"outputs={args.output_dir}")


if __name__ == "__main__":
    main()
