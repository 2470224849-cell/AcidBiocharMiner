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
from matplotlib.font_manager import FontProperties
from scipy.stats import chi2

from structure_incremental_explanatory_power import (
    STRUCTURES,
    TEXT,
    fit_bootstrap_model,
    fit_mixed_model,
    prepare_analysis,
    resample_literature_clusters,
    standardize,
    structure_cases,
)


GREEN = "#67B3AD"
GREEN_LIGHT = "#EAF5E2"


BASE_FORMULA = (
    "log_qe_z ~ pH_z + I(pH_z ** 2) + log_c0_z + I(log_c0_z ** 2) "
    "+ log_slr_z + temperature_z + C(nuclide)"
)
FULL_FORMULA = BASE_FORMULA + " + structure_z"
ORDER = ["O_content", "SSA", "TPV", "APS", "pH_pzc"]
LABELS = {
    "O_content": "O含量",
    "SSA": "SSA",
    "TPV": "TPV",
    "APS": "APS",
    "pH_pzc": r"$\mathrm{pH}_{\mathrm{pzc}}$",
}


def select_font() -> FontProperties:
    for path in [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
    ]:
        if path.exists():
            return FontProperties(fname=str(path))
    return FontProperties(family="sans-serif")


def prepared_cases(data: pd.DataFrame, structure: dict[str, str]) -> pd.DataFrame:
    cases = structure_cases(data, structure)
    cases["log_qe_z"] = standardize(cases["log_qe"].rename("log_qe"))
    return cases


def analyze_structure(data: pd.DataFrame, structure: dict[str, str]) -> dict[str, object]:
    cases = prepared_cases(data, structure)
    baseline, baseline_method = fit_mixed_model(BASE_FORMULA, cases)
    full, full_method = fit_mixed_model(FULL_FORMULA, cases)
    beta = float(full.fe_params["structure_z"])
    likelihood_ratio = max(0.0, 2.0 * (full.llf - baseline.llf))
    p_value = float(chi2.sf(likelihood_ratio, df=1))
    return {
        "key": structure["key"],
        "display": LABELS[structure["key"]],
        "source_column": structure["source"],
        "structure_transform": structure["transform"],
        "n": len(cases),
        "literature_n": int(cases["literature_id"].nunique()),
        "material_n": int(cases["material_id"].nunique()),
        "nuclide_n": int(cases["nuclide"].nunique()),
        "standardized_beta": beta,
        "likelihood_ratio": likelihood_ratio,
        "lrt_df": 1,
        "lrt_p": p_value,
        "baseline_llf": float(baseline.llf),
        "full_llf": float(full.llf),
        "baseline_converged": bool(baseline.converged),
        "full_converged": bool(full.converged),
        "baseline_optimizer": baseline_method,
        "full_optimizer": full_method,
    }


def bootstrap_beta(
    structure_key: str,
    cases: pd.DataFrame,
    iterations: int,
    seed: int,
) -> tuple[str, list[float], int]:
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    failures = 0
    for _ in range(iterations):
        try:
            sampled = resample_literature_clusters(cases, rng)
            result = fit_bootstrap_model(FULL_FORMULA, sampled)
            beta = float(result.fe_params["structure_z"])
            if math.isfinite(beta):
                estimates.append(beta)
            else:
                failures += 1
        except Exception:
            failures += 1
    return structure_key, estimates, failures


def attach_bootstrap_intervals(
    data: pd.DataFrame,
    results: list[dict[str, object]],
    iterations: int,
    jobs: int,
    seed: int,
) -> None:
    cases_by_key = {
        structure["key"]: prepared_cases(data, structure)
        for structure in STRUCTURES
    }
    distributions: dict[str, tuple[list[float], int]] = {}
    workers = max(1, min(jobs, len(STRUCTURES)))
    if workers == 1:
        for index, structure in enumerate(STRUCTURES):
            key, values, failures = bootstrap_beta(
                structure["key"], cases_by_key[structure["key"]], iterations, seed + index * 1009
            )
            distributions[key] = (values, failures)
            print(f"bootstrap {key}: success={len(values)}/{iterations}, failures={failures}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    bootstrap_beta,
                    structure["key"],
                    cases_by_key[structure["key"]],
                    iterations,
                    seed + index * 1009,
                ): structure["key"]
                for index, structure in enumerate(STRUCTURES)
            }
            for future in as_completed(futures):
                key, values, failures = future.result()
                distributions[key] = (values, failures)
                print(f"bootstrap {key}: success={len(values)}/{iterations}, failures={failures}", flush=True)

    minimum_success = max(10, int(math.ceil(iterations * 0.70)))
    for item in results:
        values, failures = distributions[str(item["key"])]
        if len(values) < minimum_success:
            raise RuntimeError(f"Too few successful bootstrap replicates for {item['key']}: {len(values)}/{iterations}")
        item["bootstrap_attempts"] = iterations
        item["bootstrap_success"] = len(values)
        item["bootstrap_failures"] = failures
        item["bootstrap_ci_low"] = float(np.percentile(values, 2.5))
        item["bootstrap_ci_high"] = float(np.percentile(values, 97.5))
        item["bootstrap_seed"] = seed


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
    by_key = {str(item["key"]): item for item in results}
    ordered = [by_key[key] for key in ORDER]
    beta = np.asarray([float(item["standardized_beta"]) for item in ordered])
    low = np.asarray([float(item["bootstrap_ci_low"]) for item in ordered])
    high = np.asarray([float(item["bootstrap_ci_high"]) for item in ordered])
    y = np.arange(len(ordered))
    max_abs = max(0.1, float(np.max(np.abs(np.concatenate([low, high, beta])))))
    x_limit = max_abs * 1.18

    fig, ax = plt.subplots(figsize=(118 / 25.4, 91 / 25.4), facecolor="white")
    for row, item, point, ci_low, ci_high in zip(y, ordered, beta, low, high):
        ax.hlines(row, ci_low, ci_high, color=GREEN, linewidth=1.4, zorder=2)
        ax.vlines([ci_low, ci_high], row - 0.075, row + 0.075, color=GREEN, linewidth=1.0, zorder=2)
        ax.scatter(
            point,
            row,
            s=38,
            facecolor=GREEN,
            edgecolor=GREEN,
            linewidth=1.15,
            zorder=3,
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
    ax.set_yticklabels([LABELS[key] for key in ORDER], fontproperties=font, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_ylim(len(ordered) - 0.45, -0.45)
    ax.set_xlim(-x_limit, x_limit)
    ax.set_xlabel("标准化校正效应 β（95% CI）", fontproperties=font, fontsize=8.5, labelpad=8)
    ax.set_title("结构因素对核素吸附性能的校正效应", loc="left", fontproperties=font, fontsize=10.2, pad=17)
    ax.axvline(0, color="#69757D", linewidth=0.9, linestyle=(0, (3, 3)), zorder=1)
    ax.xaxis.grid(True, color=GREEN_LIGHT, linewidth=0.75, zorder=0)
    ax.yaxis.grid(False)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#66727A")
    ax.tick_params(axis="y", length=0, pad=7)
    ax.tick_params(axis="x", labelsize=7.5, length=3, color="#66727A")
    fig.text(
        0.15,
        0.018,
        f"点为标准化β，水平线为按文献整群重抽样的 bootstrap 95% CI（{int(ordered[0]['bootstrap_attempts'])}次）。",
        ha="left",
        va="bottom",
        fontproperties=font,
        fontsize=5.8,
        color="#66727A",
    )
    fig.subplots_adjust(left=0.22, right=0.89, top=0.80, bottom=0.23)
    for suffix, dpi in [(".svg", None), (".pdf", None), (".png", 400), (".tiff", 600)]:
        fig.savefig(output_stem.with_suffix(suffix), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_source(path: Path, results: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)


def write_method(path: Path, results: list[dict[str, object]], iterations: int) -> None:
    sample_lines = "\n".join(
        f"- {item['key']}：n={item['n']}，文献={item['literature_n']}，材料={item['material_n']}，"
        f"bootstrap成功={item['bootstrap_success']}/{item['bootstrap_attempts']}。"
        for item in results
    )
    text = f"""# 结构因素的标准化校正效应

- 分析主体：Sheet2的吸附记录；通过文件名与样品编号匹配材料结构参数。
- 五个结构参数严重非共同缺失，因此每个参数在自身有效样本中单独拟合，不使用仅有10条记录的五参数共同完整案例。
- 响应变量：平衡吸附量取自然对数后标准化。
- 结构参数：比表面积、平均孔径、总孔容和O含量先取自然对数再标准化；零电荷点保留原尺度后标准化。
- β的含义：结构指标增加1个标准差时，校正后对数吸附性能平均改变的标准差数。
- 固定效应：结构参数、pH（线性与二次项）、初始浓度自然对数（线性与二次项）、固液比自然对数、吸附温度和核素类型。
- 随机效应：文献随机截距，以及嵌套于文献的材料随机截距。
- 95% CI：按文献整群重抽样的非参数bootstrap（尝试{iterations}次），每次重新拟合完整混合模型，取β分布的2.5%和97.5%分位数。
- P值：含结构参数与不含结构参数的混合模型似然比检验（1个自由度），未进行多重比较校正。

## 有效样本
{sample_lines}
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot standardized adjusted effects of structure variables.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260819)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data = prepare_analysis(args.input)
    results = [analyze_structure(data, structure) for structure in STRUCTURES]
    attach_bootstrap_intervals(data, results, args.bootstrap, args.jobs, args.seed)
    stem = args.output_dir / "structure_standardized_adjusted_effects"
    draw_figure(results, stem)
    write_source(args.output_dir / "structure_standardized_adjusted_effects_source_data.csv", results)
    write_method(args.output_dir / "structure_standardized_adjusted_effects_method.md", results, args.bootstrap)
    for item in [next(row for row in results if row["key"] == key) for key in ORDER]:
        print(
            item["key"],
            f"n={item['n']}",
            f"beta={item['standardized_beta']:.6f}",
            f"CI=({item['bootstrap_ci_low']:.6f},{item['bootstrap_ci_high']:.6f})",
            f"P={item['lrt_p']:.6g}",
            f"bootstrap={item['bootstrap_success']}/{item['bootstrap_attempts']}",
        )
    print(f"output_stem={stem}")


if __name__ == "__main__":
    main()
