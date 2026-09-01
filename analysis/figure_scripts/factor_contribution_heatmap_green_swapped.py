from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from pathlib import Path

LOCAL_DEPS = Path(__file__).resolve().parent.parent / "python_deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from acid_group_and_factor_contribution_heatmaps import select_chinese_font


FACTORS = [
    "酸类型",
    "标准化酸浓度",
    "酸处理时间",
    "酸处理温度",
    "改性顺序",
    "热解温度",
    "原料类别",
]
RESPONSES = ["比表面积", "平均孔径", "总孔容", "氧含量", "零电荷点"]


def load_contributions(path: Path) -> tuple[np.ndarray, dict[str, int]]:
    factor_index = {name: i for i, name in enumerate(FACTORS)}
    response_index = {name: i for i, name in enumerate(RESPONSES)}
    values = np.full((len(RESPONSES), len(FACTORS)), np.nan, dtype=float)
    response_n: dict[str, int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            response = row["response"]
            factor = row["factor"]
            if response not in response_index or factor not in factor_index:
                continue
            values[response_index[response], factor_index[factor]] = float(row["relative_contribution_pct"])
            response_n[response] = int(float(row["complete_case_n"]))
    return values, response_n


def draw_heatmap(output_stem: Path, values: np.ndarray, response_n: dict[str, int]) -> None:
    font = select_chinese_font()
    cmap = LinearSegmentedColormap.from_list("green_teal", ["#EAF5E2", "#67B3AD"])
    cmap.set_bad("#F1F1EF")
    vmax = max(10.0, math.ceil(float(np.nanmax(values)) / 5.0) * 5.0)

    # Landscape canvas matches the transposed 5-response × 7-factor matrix.
    fig = plt.figure(figsize=(165 / 25.4, 118 / 25.4), facecolor="white")
    ax = fig.add_axes([0.25, 0.33, 0.71, 0.50])
    image = ax.imshow(
        np.ma.masked_invalid(values),
        cmap=cmap,
        vmin=0,
        vmax=vmax,
        aspect="equal",
        interpolation="nearest",
    )

    ax.set_xlim(-0.5, len(FACTORS) - 0.5)
    ax.set_ylim(len(RESPONSES) - 0.5, -0.5)
    ax.set_xticks(range(len(FACTORS)))
    ax.set_yticks(range(len(RESPONSES)))
    ax.set_xticklabels(
        FACTORS,
        fontproperties=font,
        fontsize=7.0,
        rotation=35,
        ha="left",
        va="bottom",
        rotation_mode="anchor",
    )
    ax.set_yticklabels(
        [f"{label}\n(n = {response_n.get(label, 0)})" for label in RESPONSES],
        fontproperties=font,
        fontsize=7.0,
        linespacing=1.05,
    )
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", top=False, bottom=False, labeltop=True, labelbottom=False, length=0, pad=10)
    ax.tick_params(axis="y", length=0, pad=7)
    ax.set_xlabel("")
    ax.set_title("制备和改性因素", fontproperties=font, fontsize=8, pad=42)

    ax.set_xticks(np.arange(-0.5, len(FACTORS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(RESPONSES), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", top=False, bottom=False, left=False, right=False)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for i in range(len(RESPONSES)):
        for j in range(len(FACTORS)):
            value = values[i, j]
            if not np.isfinite(value):
                ax.text(j, i, "—", ha="center", va="center", color="#777777", fontsize=7, fontproperties=font)
                continue
            display_value = "<0.1%" if 0 < value < 0.1 else f"{value:.1f}%"
            ax.text(
                j,
                i,
                display_value,
                ha="center",
                va="center",
                color="#183A37",
                fontsize=7.2,
                fontweight="semibold",
                fontproperties=font,
            )

    cbar_ax = fig.add_axes([0.29, 0.24, 0.63, 0.014])
    colorbar = fig.colorbar(image, cax=cbar_ax, orientation="horizontal")
    colorbar.set_ticks([0, vmax / 2, vmax])
    colorbar.set_ticklabels(["0", f"{vmax / 2:g}", f"{vmax:g}"])
    colorbar.ax.tick_params(length=0, pad=2, labelsize=6.7)
    colorbar.outline.set_visible(False)
    colorbar.set_label("相对贡献（%）", fontproperties=font, fontsize=6.7, labelpad=2)
    fig.text(
        0.60,
        0.035,
        "格内数字为独立 ΔR² 的相对贡献（%）；酸浓度已在同类酸内标准化。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=6.2,
        color="#50615D",
    )

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".tiff"), dpi=600, bbox_inches="tight", facecolor="white")
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw the factor-contribution heatmap with axes exchanged.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    values, response_n = load_contributions(args.input)
    draw_heatmap(args.output, values, response_n)
    print(f"output={args.output.with_suffix('.tiff')}")


if __name__ == "__main__":
    main()
