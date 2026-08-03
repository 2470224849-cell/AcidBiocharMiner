meta = """
"meta": {
    "name": "",
    "symbol": "",  # ex) 1a
    "chemical formula": "",
}
"""


surface_area = """
"surface area": [
    {
        "type": "",  # ex) BET, Langmuir
        "probe": "",
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""


pore_volume = """
"pore volume": [
    {
        "probe": "", ex) N2, H2
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""


crystal_size = """
"crystal size": [
    {
        "value": "",
        "unit": "",  # ex) mm
        "condition": "",
    }, ...
]
"""


gas_adsorption = """
"gas adsorption": [
    {
        "adsorbate": "",
        "adsorbed amount": "",
        "unit": "",
        "temperature": "",
        "pressure": "",
        "condition": "",
    }, ...
]
"""


porosity = """
"porosity": [
    {
        "probe": "",
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""


pore_diameter = """
"pore diameter": [
    {
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""


crystal_system = """
"crystal system": [
    {
        "value": "",  # ex) Triclinic
        "condition": "",
    }, ...
]
"""


space_group = """
"space group": [
    {
        "value": "",  # ex) P1
        "condition": "",
    }, ...
]
"""


chemical_formula_weight = """
"chemical formula weight": [
    {
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""

decomposition_temperature = """
"decomposition temperature": [
    {
        "value": "",
        "unit": "",
        "type": "",  # ex) lattice collapse, weight loss, departure of water molecules, etc.
        "condition": "",
    }, ...
]
"""

heat_capacity = """
"heat capacity": [
    {
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""


thermal_expansion_coefficient = """
"thermal expansion coefficient": [
    {
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""


thermal_conductivity_coefficient = """
"thermal conductivity_coefficient": [
    {
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""


elastic_constant = """
"elastic constant": [
    {
        "value": "",
        "unit": "",
        "condition": "",
        "type": "",  # ex) young's modulus, bulk modulus, shear_modulus, poissons ratio, etc
    }, ...
]
"""

formation_energy = """
"formation energy": [
    {
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""

adsorption_energy = """
"adsorption energy": [
    {
        "value": "",
        "unit": "",
        "condition": "",
        "gas type": "",
    }, ...
]
"""

henry_coefficient = """
"henry coefficient": [
    {
        "value": "",
        "unit": "",
        "condition": "",
        "gas type": "",
    }, ...
]
"""


selectivity = """
"selectivity": [
    {
        "value": "",
        "unit": "",
        "substrate": "",
        "catalyst": "",
        "pressure": "",
        "temperature": "",
        "solvent": "",
        "time": "",
        "condition": "",
    }, ...
]
"""

conversion = """
"conversion": [
    {
        "value": "",
        "unit": "",
        "substrate": "",
        "catalyst": "",
        "pressure":"",
        "temperature":"",
        "solvent": "",
        "time": "",
    }, ...
]
"""

reaction_yield = """
"yield": [
    {
        "value": "",
        "unit": "",
        "substrate": "",
        "catalyst": "",
        "pressure": "",
        "temperature": "",
        "solvent": "",
        "time": "",
    }, ...
]
"""


catalytic_activity = """
"catalytic activity": [
    {
        "value": "",
        "unit": "",
        "time": "",
        "condition": "",
    }, ...
]
"""


density = """
"density": [
    {
        "value": "",
        "unit": "",  # ex) g/cm^3
        "condition": "",
    }, ...
]
"""

magnetic_moment = """
"magnetic moment": [
    {
        "value":"",
        "unit":"",
        "temperature":"",
        "condition": "",
    }, ...
]
"""

magnetic_susceptibility = """
"magnetic susceptibility": [
    {
        "value": "",
        "unit": "",
        "temperature": "",
        "condition": "",
    }, ...
]
"""


peak_spectrum = """
"peak spectrum": [
    {
        "value": "",
        "unit": "",
        "type": "",  # ex) IR, NMR, UV, electronic, etc
        "condition": "",
    }, ...
]
"""

cell_volume = """
"cell volume": [
    {
        "value": "",
        "unit": "",  # ex) Å^3
        "condition": "",
    }, ...
]
"""


lattice_parameters = """
"lattice parameters": [
    {
        "value": {
            "a": "",
            "b": "",
            "c": "",
            "alpha": "",
            "beta": "",
            "gamma": "",
        "condition": "",
        }
    }, ...
]
"""

topology = """
"topology" : [
    {
        "value": "", # ex) pcu
        "condition": "",
    }, ...
]
"""


material_color = """
"material color": [
    {
        "value": "",
        "condition": "",
    }, ...
]
"""


material_shape = """
"material shape": [
    {
        "value": "",
        "condition": "",
    }, ...
]
"""

simulation_parameters = """
"simulation parameters": [
    {
        "symbol": "",  # ex) σ
        "value": "",
        "unit": "",
        "type": "",  # lennard-jones potential
    }, ...

]
"""

etc = """
"etc": [
    {
        "property name": "",
        "value": "",
        "unit": "",
        "condition": "",
    }, ...
]
"""

proton_conductivity = """
"proton_conductivity": [
    {
        "value": "",
        "unit": "",
        "temperature": "",
        "RH": "",
        "Ea": "",
        "guest": "",
    }, ...
]
"""

biochar_modification = """
"biochar modification": [
    {
        "filename": "",
        "sample_id": "",
        "biomass_source": "",
        "pyrolysis_temp_C": "",
        "hold_duration_h": "",
        "heating_rate_C_min": "",
        "acid_type": "",
        "acid_conc_mol_L": "",
        "acid_time_h": "",
        "acid_temp_C": "",
        "modification_sequence": "",
        "SSA_m2_g": "",
        "APS_nm": "",
        "TPV_cm3_g": "",
        "ash_percent": "",
        "C_percent": "",
        "O_percent": "",
        "N_percent": "",
        "H_percent": "",
        "pH_pzc": "",
    }, ...
]
"""

adsorption_experiment = """
"adsorption experiment": [
    {
        "filename": "",
        "sample_id": "",
        "pollutant_name": "",
        "pH": "",
        "T_K": "",
        "Te_min": "",
        "SLR_g_L": "",
        "Qmax": "",
    }, ...
]
"""
