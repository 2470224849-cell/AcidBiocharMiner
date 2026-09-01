# 结构因素统计与绘图脚本

本目录保存酸改性生物炭结构分析中使用的统计和绘图代码。脚本均通过命令行接收输入工作簿和输出目录，不包含原始数据或生成的图像。

## 主要脚本

- `factor_contribution_heatmap_green.py`：七类制备/改性因素的独立解释度热图（OLS、多元模型、删减因素块计算 ΔR²）。
- `adjusted_effect_panels.py`：校正后边际均值和酸处理时间偏效应曲线（对数响应、自然立方样条、HC3 置信区间）。
- `structure_incremental_explanatory_power.py`：结构变量加入基线模型后的 Δ边际 R²（线性混合效应模型、ML、文献/材料随机效应）。
- `structure_standardized_adjusted_effects.py`：结构因素标准化校正效应 β（线性混合效应模型、按文献聚类 bootstrap）。
- `structure_rcs_nonlinearity.py`：SSA 和 O 含量的限制性立方样条非线性检验及响应曲线。
- `structure_effects_combined_panel_g.py`：合并 Δ边际 R² 与标准化 β 的子图 g。

其他脚本用于酸组别、中位数热图、原料类别热图以及单独导出 c1–c5 图。

## 依赖与运行

需要 Python、NumPy、Pandas、SciPy、statsmodels、matplotlib、openpyxl 和 xlrd。各脚本可用 `python script.py --help` 查看参数。结构效应脚本之间通过同目录模块相互导入，因此运行时应保留本目录结构。

每种分析的模型定义和统计解释见 `methods/`。
