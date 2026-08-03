surface_area = """
There are various types of surfacea area. For example, BET surface area and Langmuir surface area are widely used. If there is information about type of surface area, please write the surface area type.
"""

pore_volume = """

"""

crystal_size = """

"""

gas_adsorption = """
Hydrogen is H2.
"""

porosity = """
PLATON program is used for calculating porosity
"""


pore_diameter = """

"""


crystal_system = """
"""

space_group = """

"""


decomposition_temperature = """
TGA means decomposition temperature.
"""

heat_capacity = """

"""

thermal_expansion_coefficient = """

"""

thermal_conductivity_coefficient = """

"""

elastic_constant = """

"""

formation_energy = """

"""

adsorption_energy = """

"""

henry_coefficient = """

"""

selectivity = """

"""

catalytic_activity = """
If "%" and "conversion" words exist in the sentence, it must be about catalytic activity. If information about reaction time exist, you must write it. If the sentence includes more than one information, you must extract the information for each separately. For example, when the sentence is "the reaction afforded 20%, 40%, and 60% conversions after 1, 2, and 3 h, respectively, and 99% conversion could be obtained if the reaction was continued for 8 h.", 20% corresponds to 1 h, 40% corresponds to 2 h, 60% corresponds to 3h, and 99% corresponds to 8 h. TOF is a catalytic activity.
"""

density = """

"""
magnetic_moment = """

"""

magnetic_susceptibility = """
Do not extract expected or anticipated values.
"""

chemical_formula_weight = """

"""

topology = """
"""

peak_spectrum = """

"""

etc = """
In "etc" part, you must only include information that does not fit into another cateogry.
"""

lattice_parameters = """

"""

cell_volume = """
"""

material_color = """

"""

material_shape = """

"""

simulation_parameters = """

"""

proton_conductivity = """

"""

biochar_modification = """
Focus on acid-modified biochar preparation records. Keep field names exactly as required (e.g., pyrolysis_temp_C, acid_conc_mol_L, TPV_cm3_g, ash_percent, pH_pzc). Do not infer missing values.
Use one scalar value per sample-level field; do not keep multi-value lists/ranges in one cell. If only screening-series values are given, use the single selected subsequent-experiment value; otherwise leave empty.
"""

adsorption_experiment = """
Focus on adsorption experiment rows for biochar samples. Keep field names exactly as required (e.g., pH, T_K, Te_min, SLR_g_L, Qmax). Do not infer missing values.
"""
