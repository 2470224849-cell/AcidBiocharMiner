from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.font_manager import FontProperties


def select_font() -> FontProperties:
    for path in [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
    ]:
        if path.exists():
            return FontProperties(fname=str(path))
    return FontProperties(family="sans-serif")


ORDER = ["O_content", "SSA", "TPV", "pH_pzc", "APS"]
LABELS = {
    "O_content": "O含量",
    "SSA": "比表面积",
    "TPV": "总孔容",
    "pH_pzc": "零电荷点",
    "APS": "平均孔径",
}
BLUE = "#4683B4"
GREEN = "#67B3AD"
GREY = "#9AA1A8"
TEXT = "#29333A"
AXIS = "#66727A"
BLUE_GRID = "#DCE3E8"
GREEN_GRID = "#EAF5E2"


def load_combined(delta_path: Path, beta_path: Path) -> pd.DataFrame:
    delta = pd.read_csv(delta_path)
    beta = pd.read_csv(beta_path)
    delta_columns = [
        "key",
        "n",
        "delta_marginal_r2",
        "bootstrap_ci_low",
        "bootstrap_ci_high",
        "lrt_p",
        "bootstrap_attempts",
        "bootstrap_success",
    ]
    beta_columns = [
        "key",
        "n",
        "standardized_beta",
        "bootstrap_ci_low",
        "bootstrap_ci_high",
        "lrt_p",
        "bootstrap_attempts",
        "bootstrap_success",
    ]
    combined = delta[delta_columns].merge(
        beta[beta_columns],
        on="key",
        how="inner",
        validate="one_to_one",
        suffixes=("_delta", "_beta"),
    )
    if set(combined["key"]) != set(ORDER):
        raise ValueError("The two source datasets do not contain the same five structure factors.")
    if not np.array_equal(combined["n_delta"].to_numpy(), combined["n_beta"].to_numpy()):
        raise ValueError("Sample sizes differ between the two analyses.")
    combined["display"] = combined["key"].map(LABELS)
    combined["n"] = combined["n_delta"].astype(int)
    combined["delta_pct"] = 100.0 * combined["delta_marginal_r2"]
    combined["delta_ci_low_pct"] = 100.0 * combined["bootstrap_ci_low_delta"]
    combined["delta_ci_high_pct"] = 100.0 * combined["bootstrap_ci_high_delta"]
    combined = combined.set_index("key").loc[ORDER].reset_index()
    return combined


def errorbar_row(
    ax,
    y: float,
    value: float,
    low: float,
    high: float,
    color: str,
    filled: bool = True,
) -> None:
    ax.hlines(y, low, high, color=color, linewidth=1.45, zorder=2)
    ax.vlines([low, high], y - 0.075, y + 0.075, color=color, linewidth=1.05, zorder=2)
    ax.scatter(
        value,
        y,
        s=34,
        marker="o",
        facecolor=color if filled else "white",
        edgecolor=color,
        linewidth=1.15,
        zorder=3,
    )


def draw_figure(data: pd.DataFrame, output_stem: Path) -> None:
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
    y = np.arange(len(data), dtype=float)
    fig, (ax_delta, ax_beta) = plt.subplots(
        1,
        2,
        figsize=(150 / 25.4, 97 / 25.4),
        sharey=True,
        gridspec_kw={"width_ratios": [1.08, 1.0], "wspace": 0.055},
        facecolor="white",
    )

    delta_values = data["delta_pct"].to_numpy(float)
    delta_low = data["delta_ci_low_pct"].to_numpy(float)
    delta_high = data["delta_ci_high_pct"].to_numpy(float)
    delta_span = max(1.0, float(delta_high.max() - delta_low.min()))
    ax_delta.set_xlim(
        float(min(0.0, delta_low.min()) - 0.08 * delta_span),
        float(max(0.0, delta_high.max()) + 0.10 * delta_span),
    )
    for row, (_, item) in enumerate(data.iterrows()):
        significant = float(item["lrt_p_delta"]) < 0.05
        color = BLUE if significant else GREY
        errorbar_row(
            ax_delta,
            float(row),
            float(item["delta_pct"]),
            float(item["delta_ci_low_pct"]),
            float(item["delta_ci_high_pct"]),
            color,
            filled=significant,
        )
        ax_delta.text(
            float(item["delta_pct"]),
            float(row) - 0.20,
            f"ΔR²={float(item['delta_pct']):.2f}",
            ha="center",
            va="bottom",
            fontsize=6.1,
            color=TEXT,
        )
    ax_delta.axvline(0.0, color=AXIS, linewidth=0.85, linestyle=(0, (3, 3)), zorder=1)
    ax_delta.xaxis.grid(True, color=BLUE_GRID, linewidth=0.7, zorder=0)
    ax_delta.yaxis.grid(False)
    ax_delta.set_xlabel("Δ边际 R²（百分点）", fontproperties=font, fontsize=7.8, labelpad=8)

    beta_values = data["standardized_beta"].to_numpy(float)
    beta_low = data["bootstrap_ci_low_beta"].to_numpy(float)
    beta_high = data["bootstrap_ci_high_beta"].to_numpy(float)
    beta_span = max(0.1, float(beta_high.max() - beta_low.min()))
    ax_beta.set_xlim(
        float(min(0.0, beta_low.min()) - 0.09 * beta_span),
        float(max(0.0, beta_high.max()) + 0.11 * beta_span),
    )
    for row, (_, item) in enumerate(data.iterrows()):
        errorbar_row(
            ax_beta,
            float(row),
            float(item["standardized_beta"]),
            float(item["bootstrap_ci_low_beta"]),
            float(item["bootstrap_ci_high_beta"]),
            GREEN,
            filled=True,
        )
        ax_beta.text(
            1.018,
            float(row),
            f"n={int(item['n'])}",
            transform=ax_beta.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=6.8,
            color=TEXT,
            clip_on=False,
        )
    ax_beta.axvline(0.0, color=AXIS, linewidth=0.85, linestyle=(0, (3, 3)), zorder=1)
    ax_beta.xaxis.grid(True, color=GREEN_GRID, linewidth=0.7, zorder=0)
    ax_beta.yaxis.grid(False)
    ax_beta.set_xlabel("标准化校正效应 β（95% CI）", fontproperties=font, fontsize=7.8, labelpad=8)
    ax_beta.text(
        1.018,
        1.035,
        "n",
        transform=ax_beta.transAxes,
        ha="left",
        va="bottom",
        fontsize=6.8,
        color=TEXT,
        clip_on=False,
    )

    ax_delta.set_yticks(y, data["display"].tolist(), fontproperties=font, fontsize=7.8)
    ax_delta.set_ylim(len(data) - 0.42, -0.62)
    ax_beta.tick_params(axis="y", labelleft=False)
    for ax in (ax_delta, ax_beta):
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(AXIS)
        ax.spines["bottom"].set_linewidth(0.9)
        ax.tick_params(axis="x", labelsize=6.5, length=3, color=AXIS)
        ax.tick_params(axis="y", length=0, pad=2)

    legend_handles = [
        Line2D(
            [0], [0], marker="o", linestyle="none", markersize=5.4,
            markerfacecolor=BLUE, markeredgecolor=BLUE, label="P < 0.05",
        ),
        Line2D(
            [0], [0], marker="o", linestyle="none", markersize=5.4,
            markerfacecolor="white", markeredgecolor=GREY, markeredgewidth=1.1,
            label="P ≥ 0.05",
        ),
    ]
    ax_delta.legend(
        handles=legend_handles,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.025),
        frameon=False,
        ncol=2,
        handletextpad=0.45,
        columnspacing=1.2,
        fontsize=6.5,
        borderaxespad=0,
    )

    fig.text(0.018, 0.955, "(g)", ha="left", va="top", fontsize=10.2, fontweight="bold", color="black")
    fig.text(
        0.500,
        0.955,
        "结构因素的增量解释力与校正效应",
        ha="center",
        va="top",
        fontproperties=font,
        fontsize=9.8,
        color="black",
    )
    fig.text(
        0.105,
        0.035,
        "水平线为文献整群bootstrap 95% CI（1000次）；左图实心/空心：P<0.05/P≥0.05；n为有效记录数。",
        ha="left",
        va="bottom",
        fontproperties=font,
        fontsize=5.3,
        color=AXIS,
    )
    fig.subplots_adjust(left=0.17, right=0.91, top=0.80, bottom=0.22)
    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(output_stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_method(path: Path) -> None:
    path.write_text(
        """# 子图(g)：结构因素的增量解释力与标准化校正效应

- 左侧：在控制实验条件、核素类型及文献/材料层级差异后，加入单个结构因素带来的Δ边际R²（百分点）及按文献整群重抽样的bootstrap 95% CI。
- 右侧：相同控制框架下的标准化校正效应β及按文献整群重抽样的bootstrap 95% CI。
- 两侧按完全相同的结构因素顺序排列，共享纵轴；由于结构参数缺失程度不同，每行模型使用该参数自身的有效吸附记录。
- 最右侧n为有效吸附记录数，两侧模型的n一致。
- 左侧蓝色实心点表示似然比检验P<0.05，灰色空心点表示P≥0.05；P值未进行多重比较校正。
- 两类指标回答不同问题：Δ边际R²衡量新增解释力，标准化β描述校正关联的方向与标准化幅度，不应相互替代或解释为因果效应。
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine Δ marginal R2 and standardized beta into panel g.")
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--beta", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    combined = load_combined(args.delta, args.beta)
    combined.to_csv(args.output_dir / "structure_effects_combined_panel_g_source_data.csv", index=False, encoding="utf-8-sig")
    draw_figure(combined, args.output_dir / "structure_effects_combined_panel_g")
    write_method(args.output_dir / "structure_effects_combined_panel_g_method.md")
    print(combined[["display", "n", "delta_pct", "standardized_beta"]].to_string(index=False))


if __name__ == "__main__":
    main()
