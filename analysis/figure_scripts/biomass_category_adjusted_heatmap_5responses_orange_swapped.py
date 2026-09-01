from __future__ import annotations

import argparse
import csv
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


BIOMASS_ORDER = [
    "木质纤维素",
    "农作物秸秆",
    "果蔬及食品废弃物",
    "污泥",
    "畜禽粪便",
    "其他",
]

RESPONSES = [
    ("APS", "平均孔径\n(nm)", ".2f"),
    ("O_content", "氧含量\n(%)", ".1f"),
    ("pH_pzc", "零电荷点", ".2f"),
    ("TPV", "总孔容\n(cm³ g⁻¹)", ".2f"),
    ("SSA", "比表面积\n(m² g⁻¹)", ".1f"),
]


def load_source(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    response_index = {key: i for i, (key, _, _) in enumerate(RESPONSES)}
    biomass_index = {name: i for i, name in enumerate(BIOMASS_ORDER)}
    values = np.full((len(RESPONSES), len(BIOMASS_ORDER)), np.nan, dtype=float)
    normalized = np.full_like(values, np.nan)
    sample_sizes = np.zeros_like(values, dtype=int)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            response = row["response"]
            biomass = row["biomass_category"]
            if response not in response_index or biomass not in biomass_index:
                continue
            i = response_index[response]
            j = biomass_index[biomass]
            values[i, j] = float(row["adjusted_mean"])
            normalized[i, j] = float(row["column_normalized_value"])
            sample_sizes[i, j] = int(float(row["observed_n"]))
    return values, normalized, sample_sizes


def draw_heatmap(output_stem: Path, values: np.ndarray, normalized: np.ndarray, sample_sizes: np.ndarray) -> None:
    font = select_chinese_font()
    cmap = LinearSegmentedColormap.from_list("adjusted_orange", ["#FCF0D5", "#F3AF44"])
    text_dark = "#4C3820"
    text_light = "#FFFFFF"

    fig = plt.figure(figsize=(180 / 25.4, 140 / 25.4), facecolor="white")
    ax = fig.add_axes([0.26, 0.34, 0.70, 0.50])
    image = ax.imshow(normalized, cmap=cmap, vmin=0.0, vmax=1.0, aspect="equal", interpolation="nearest")

    ax.set_xlim(-0.5, len(BIOMASS_ORDER) - 0.5)
    ax.set_ylim(len(RESPONSES) - 0.5, -0.5)
    ax.set_xticks(range(len(BIOMASS_ORDER)))
    ax.set_yticks(range(len(RESPONSES)))
    xlabels = [
        "木质纤维素",
        "农作物秸秆",
        "果蔬及食品\n废弃物",
        "污泥",
        "畜禽粪便",
        "其他",
    ]
    ax.set_xticklabels(
        xlabels,
        fontproperties=font,
        fontsize=7.2,
        rotation=35,
        ha="right",
        va="top",
        rotation_mode="anchor",
    )
    ax.set_yticklabels(
        [label for _, label, _ in RESPONSES],
        fontproperties=font,
        fontsize=7.2,
        linespacing=1.05,
    )
    ax.tick_params(axis="x", length=0, pad=10)
    ax.tick_params(axis="y", left=False, right=False, length=0, pad=9)
    ax.set_xlabel("原料类别", fontproperties=font, fontsize=8, labelpad=12)

    ax.set_xticks(np.arange(-0.5, len(BIOMASS_ORDER), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(RESPONSES), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.8)
    ax.tick_params(which="minor", bottom=False, left=False, top=False, right=False)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            text_color = text_light if normalized[i, j] >= 0.60 else text_dark
            value = values[i, j]
            if not np.isfinite(value):
                ax.text(j, i, "—", ha="center", va="center", color="#777777", fontsize=7, fontproperties=font)
                continue
            fmt = RESPONSES[i][2]
            ax.text(
                j,
                i - 0.09,
                format(value, fmt),
                ha="center",
                va="center",
                fontsize=7.6,
                fontweight="bold",
                color=text_color,
                fontproperties=font,
            )
            ax.text(
                j,
                i + 0.22,
                f"n={int(sample_sizes[i, j])}",
                ha="center",
                va="center",
                fontsize=5.2,
                color=text_color,
                fontproperties=font,
            )

    fig.text(
        0.61,
        0.875,
        "不同原料类别的校正后结构水平",
        ha="center",
        va="bottom",
        fontproperties=font,
        fontsize=9.2,
        color="#1F2F2D",
    )

    colorbar_ax = fig.add_axes([0.31, 0.16, 0.58, 0.018])
    colorbar = fig.colorbar(image, cax=colorbar_ax, orientation="horizontal")
    colorbar.set_ticks([0.0, 1.0])
    colorbar.set_ticklabels(["低", "高"])
    for label in colorbar.ax.get_xticklabels():
        label.set_fontproperties(font)
    colorbar.ax.tick_params(length=0, labelsize=6.2, colors=text_dark, pad=3)
    colorbar.outline.set_visible(False)
    colorbar.set_label("行内标准化相对水平", fontproperties=font, fontsize=6.2, color=text_dark, labelpad=-1)

    fig.text(
        0.56,
        0.055,
        "格内为校正后边际均值，n 为该响应的有效样本量；n<3 的结果需谨慎解释。",
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=5.7,
        color=text_dark,
    )

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".tiff"), dpi=600, bbox_inches="tight", facecolor="white")
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw the adjusted biomass heatmap with axes exchanged.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    values, normalized, sample_sizes = load_source(args.input)
    draw_heatmap(args.output, values, normalized, sample_sizes)
    print(f"output={args.output.with_suffix('.tiff')}")


if __name__ == "__main__":
    main()
