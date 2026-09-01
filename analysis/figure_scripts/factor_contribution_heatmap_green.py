from __future__ import annotations

import argparse
import math
from pathlib import Path

from acid_group_and_factor_contribution_heatmaps import (
    FACTORS,
    RESPONSES,
    contribution_analysis,
    groupwise_standardize_concentration,
    load_rows,
    select_chinese_font,
    write_contribution_csv,
    write_protocol,
)

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap


def draw_green_heatmap(
    output_stem: Path,
    contributions: np.ndarray,
    response_n: dict[str, int],
) -> None:
    font = select_chinese_font()
    cmap = LinearSegmentedColormap.from_list("green_teal", ["#EAF5E2", "#67B3AD"])
    cmap.set_bad("#F1F1EF")
    vmax = max(10.0, math.ceil(float(np.nanmax(contributions)) / 5.0) * 5.0)

    fig = plt.figure(figsize=(118 / 25.4, 165 / 25.4))
    ax = fig.add_axes([0.27, 0.22, 0.70, 0.62])
    image = ax.imshow(
        np.ma.masked_invalid(contributions),
        cmap=cmap,
        vmin=0,
        vmax=vmax,
        aspect="equal",
        interpolation="nearest",
    )

    ax.set_xlim(-0.5, len(RESPONSES) - 0.5)
    ax.set_ylim(len(FACTORS) - 0.5, -0.5)
    ax.set_xticks(range(len(RESPONSES)))
    ax.set_yticks(range(len(FACTORS)))
    ax.set_xticklabels(
        [
            f"{r'pH$_{pzc}$' if label == 'pH_pzc' else label}\n(n = {response_n.get(label, 0)})"
            for label, _ in RESPONSES
        ],
        fontproperties=font,
        fontsize=7.2,
        linespacing=1.05,
    )
    ax.set_yticklabels([label for label, _ in FACTORS], fontproperties=font, fontsize=7.2)
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", which="both", top=False, bottom=False, labeltop=True, labelbottom=False, length=0, pad=7)
    ax.tick_params(axis="y", length=0, pad=7)
    ax.set_ylabel("制备和改性因素", fontproperties=font, fontsize=8, labelpad=18)

    ax.set_xticks(np.arange(-0.5, len(RESPONSES), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(FACTORS), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", top=False, bottom=False, left=False, right=False)
    ax.tick_params(axis="x", which="both", top=False, bottom=False, labeltop=True, labelbottom=False, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for i in range(len(FACTORS)):
        for j in range(len(RESPONSES)):
            value = contributions[i, j]
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

    cbar_ax = fig.add_axes([0.3075, 0.125, 0.625, 0.013])
    colorbar = fig.colorbar(image, cax=cbar_ax, orientation="horizontal")
    colorbar.set_ticks([0, vmax / 2, vmax])
    colorbar.set_ticklabels(["0", f"{vmax / 2:g}", f"{vmax:g}"])
    colorbar.ax.tick_params(length=0, pad=2, labelsize=6.7)
    colorbar.outline.set_visible(False)
    colorbar.set_label("相对贡献（%）", fontproperties=font, fontsize=6.7, labelpad=2)
    fig.text(
        0.62,
        0.055,
        "格内数字为独立 ΔR² 的相对贡献（%）；酸浓度已在同类酸内标准化。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=6.2,
        color="#50615D",
    )

    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(output_stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw a standalone green factor-contribution heatmap.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows, _ = load_rows(args.input)
    groupwise_standardize_concentration(rows)
    contributions, records, response_n = contribution_analysis(rows)
    output_stem = args.output_dir / "factor_contribution_heatmap_green"
    draw_green_heatmap(output_stem, contributions, response_n)
    write_contribution_csv(args.output_dir / "factor_relative_contribution_source_data.csv", records)
    write_protocol(args.output_dir / "factor_contribution_method.md", response_n)

    print(f"response_n={response_n}")
    print(f"contributions_pct=\n{contributions}")
    print(f"output_stem={output_stem}")


if __name__ == "__main__":
    main()
