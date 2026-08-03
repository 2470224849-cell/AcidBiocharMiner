PROMPT_TYPE = """First, determine whether properties exist or not. Except for topology, crystal system, and space group, properties should include explicit numeric information (single value, range, or value with ±). If no numeric evidence exists, do not extract it. If there is no property in the paragraph, please return an empty list.
If properties exist, you must find all the properties in paragraphs. Names of properties must be one of following:
{explanation}

You must follow below rules:
- Avoid including the same property multiple times. If there are surface_area and BET surface_area in the paragraph at the same time, you must include "surface_area" once.
- You must include only the properties, excluding the names of materials.
- If a property you find lacks a value, please exclude it.
- Do not be confused between gas adsorption and selectivity. Gas adsorption is a property that has a unit and selectivity is unitless. Even though there is a word "selectivity", it is not always selectivity. If there is a value with unit, it is gas adsorption.
- In crystal system, there are triclinic, monoclinic, orthorhombic, tetragonal, trigonal, hexagonal, and cubic. If one of them exists in the paragraph, it means there is "crystal system" information.
- If "TGA" or "TG" exists in the paragraph, it includes "decomposition_temperature".
- When property does not exist in the list, write "etc".
- For acid-modified biochar studies, map preparation-field paragraphs to "biochar_modification" when they contain sample-level numeric preparation data (biomass source, pyrolysis/acid-treatment conditions, SSA/APS/PV, elemental composition, pH_pzc).
- For acid-modified biochar studies, map adsorption-test paragraphs to "adsorption_experiment" when they contain sample-level numeric test-condition data (pollutant_name, pH, T_K, Te_min, SLR_g_L) or explicit maximum adsorption capacity (Qmax).
- This task follows a two-table target: "biochar_modification" = Materials (sheet1), "adsorption_experiment" = Adsorption (sheet2).
- Recall-first policy: prioritize extracting candidate rows whenever paragraph has numeric signals tied to acid-modified biochar or aqueous adsorption/removal context, even if some fields are missing.
- Prefer paragraphs containing quantifiable details: acid treatment conditions, adsorbent properties (BET/pore/pH/elemental ratios), and adsorption test conditions (pH/T/time/dosage).
- If scope is ambiguous but paragraph still contains relevant numeric cues, keep candidate properties and leave uncertain columns as "".
- This text pathway should capture both main text and SI captions/notes with explicit values assignable to a sample row.
- Do not extract C0_mg_L or Qe_mg_g in this stage (they will be supplemented from graph digitization later). Extract Qmax only when it is explicitly reported.

If you are uncertain, please reply with "I do not know".

Begin!

Paragraph: MOF-A exhibits a surface area of 1500 m2/g and a pore volume of 0.9 cm3/g. Another notable MOF, MOF-C, possesses a surface_area of 4000 m2/g and a pore volume of 1.5 cm3/g.
List: ```JSON
["surface_area", "pore_volume"]
```

Paragraph: MOF-C shows exceptional hydrogen storage capacity, with an uptake of 7.5 wt% at 77 K and 1 bar.
List: ```JSON
["gas_adsorption"]
```

Paragraph: The MOF-D exhibits intriguing magnetic properties, displaying a high magnetic moment of 4.8 μB per Fe atom at room temperature.
List: ```JSON
["magnetic_moment"]
```

Paragraph: The MOF material MOF-H demonstrated exceptional guest molecule selectivity, exhibiting a high adsorption preference for CO2 over N2. Moreover, MOF-I achieved a high turnover frequency (TOF) of 1000 h-1.
List: ```JSON
["catalytic_activity"]
```

Paragraph: MOF-A displays a dielectric constant of approximately 4.5 at 1 kHz, making it suitable for applications in electronics and capacitive devices.
List: ```JSON
["etc"]
```

Paragraph: An intense emission occurs at 407nm with the excitation wavelength at 318nm.
List: ```JSON
["peak_spectrum"]
```

Paragraph: In the case of 2, during the entire decomposition process up to 550°C, the residual material observed at the end comprises approximately 22.3% of the original sample, possibly indicating a mixture of ZrO2 and ZrC (calculated 23.8%).
List: ```JSON
["decomposition_temperature"]
```

Paragraph: MOF-A exhibits (4,4)-connected 3D frameworks with a Schläfli symbol of 42638.
List: ```JSON
["topology"]
```

Paragraph: The Co(II) compound exhibits a χ_MT product of 3.87 cm^3 mol^−1 K at room temperature, which closely matches the expected value of 3.90 cm^3 mol^−1 K, affirming the suitability of the free-ion approximation to explain its magnetic behavior
List: ```JSON
["magnetic_susceptibility"]
```

Paragraph: Crystallographic data for Compound 2: C36H42N6O4, M = 622.75, monoclinic, P21/c, a = 10.812(4) Å, b = 15.261(6) Å, c = 13.973(5) Å, V = 2293.0(14) cm^3, Z = 4, Dc = 1.292 g cm^−3, μ (X-ray) = 1.012 mm^−1, T = 298(2) K, 14056 reflections collected, 3668 unique (Rint = 0.0573), R1 on F(wR2 on F2) = 0.0397 (0.0884) for 3447 observed (I > 2σ(I)) reflections.
List: ```JSON
["chemical_formula_weight", "crystal_system", "space_group", "lattice_parameters", "density"]
```

Paragraph: The calculated solvent-accessible void space within the framework measures 852.8 Å3, representing approximately 38.2% of the unit cell volume of 2230.6 Å3.
List: ```JSON
["porosity"]
```

Paragraph: In summary, we have successfully achieved a high-performance MOF-based proton-conducting material via the facile encapsulation of the imidazole guests within the pores of robust MOF-808 and demonstrated that Im@MOF-808 possesses high proton conductivity with the value of 3.45 × 10−2 S cm−1 (338 K and 99% RH).
List: ```JSON
["proton_conductivity"]
```

Paragraph: The acid-modified biochar sample BC-HNO3 was obtained from rice straw after pyrolysis at 500 C for 2 h (10 C/min), followed by HNO3 treatment (1.0 mol/L, 60 C, 3 h). The material showed SSA 412 m2/g, APS 3.8 nm, PV 0.42 cm3/g, O/C 0.25, and pHpzc 5.6.
List: ```JSON
["biochar_modification"]
```

Paragraph: For Cd(II) adsorption using BC-HNO3, C0 was 200 mg/L and equilibrium uptake Qe reached 186.4 mg/g at pH 7.0, 298 K, Te 120 min, and SLR 1.0 g/L.
List: ```JSON
["adsorption_experiment"]
```

Paragraph: {paragraph}
List:"""


PROMPT_EXT = """Extract the information about {prop} mentioned in the paragraph. Follow the structured data in JSON format:
{structured_data}

You must follow below rules:
- You must write all the information about {prop} in the paragraph.
- Do not forge information that is not in the paragraph.
- Do not write the information in the examples.
- When property is "etc", do not extract {prop}.
- Make a list that shows properties of each material. The list consists of several dictionaries of all materials. Each dictionary must include "meta":{{"name":"", "symbol":"", "chemical formula":""}}. ex) [{{"meta":{{"name":"", "symbol":"", "chemical formula":""}}, {structured_data}]
- When material is expressed as a number, you must fill in "symbol" of "meta". ex) Paragraph: The corresponding BET surface area is 100 m2/g for 1. JSON: [{{"meta":{{"name":"", "symbol":"1", "chemical formula":""}}, "surface area": {{"type": "BET", "probe": "", "value": "100", "unit": "m2/g"}}}}]
- "condition" means not only pressure, temperature, but specific details of property like crystal form.
- If {prop} includes "biochar_modification" or "adsorption_experiment", keep field names exactly as defined in the schema (do not rename keys), and leave unknown values as "".
- For "biochar_modification", output row dictionaries using these exact columns only: filename, sample_id, biomass_source, pyrolysis_temp_C, hold_duration_h, heating_rate_C_min, acid_type, acid_conc_mol_L, acid_time_h, acid_temp_C, modification_sequence, SSA_m2_g, APS_nm, TPV_cm3_g, ash_percent, C_percent, O_percent, N_percent, H_percent, pH_pzc.
- For "adsorption_experiment", output row dictionaries using these exact columns only: filename, sample_id, pollutant_name, pH, T_K, Te_min, SLR_g_L, Qmax.
- Never output C0_mg_L or Qe_mg_g in this stage; do output Qmax when explicitly reported.
- Do not output model-specific columns (e.g., Qe_mg_g_DeepSeek, Qe_mg_g_Qwen) and do not output key suffix variants such as adsorption_experiment_1.
- Do not invent missing values from context; if a column is not explicitly given, keep it as "".
- Keep one row per sample-condition record. If multiple samples/conditions are reported, output multiple rows.
- Sample-level scalar fields must be single-valued. Never put multi-value lists/ranges in one cell (e.g., "400, 500, 600" or "130, 180"). If multiple values are mentioned for screening only, pick the single value explicitly selected for subsequent experiments for that sample; otherwise keep the field as "".
- When a modified sample (e.g., HMB/NaMB/FeMB) is prepared from a base sample (e.g., MB), inherit the base sample's single final preparation value only when the paper explicitly states that final value was used in subsequent preparation/experiments.
- Scope policy: prioritize acid-modified biochar + aqueous adsorption/removal rows (pollutant not restricted), but keep recall high; if paragraph has relevant numeric evidence, extract candidate rows and keep uncertain fields as "".
- Do not fabricate values. If statement is conceptual without numeric evidence, skip that statement.
- For mixed/composite studies, still extract rows when acid-modified-biochar sample-level values are explicitly stated.

{information} 

If you are uncertain, please reply with "I do not know".

Begin!

{example}

Paragraph: {paragraph}
JSON:
"""

FT_TYPE = (
    "You must decide whether properties exist or not. "
    "Except for topology, crystal system, and space group, property must have a float value. "
    "If there is no property in the paragraph, please return an empty list. "
    "You must find all the properties in the paragraphs. "
    "Use recall-first scope for acid-modified biochar adsorption/removal in water with unrestricted pollutants; keep candidate properties when numeric cues exist. "
    "Names of properties must be one of following:\n"
    "['adsorption_energy', 'adsorption_experiment', 'biochar_modification', 'catalytic_activity', 'chemical_formula_weight', 'crystal_size', 'crystal_system', 'decomposition_temperature', 'density', 'elastic_constant', 'formation_energy', 'gas_adsorption', 'heat_capacity', 'henry_coefficient', 'lattice_parameters', 'magnetic_moment', 'magnetic_susceptibility', 'material_color', 'material_shape', 'simulation_parameters', 'pore_diameter', 'pore_volume', 'porosity', 'selectivity', 'space_group', 'peak_spectrum', 'surface_area', 'thermal_conductivity_coefficient', 'thermal_expansion_coefficient', 'topology', 'etc', 'proton_conductivity']"
)

FT_HUMAN = "{paragraph}"
