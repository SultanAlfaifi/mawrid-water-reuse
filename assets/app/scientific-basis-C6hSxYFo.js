var e=`# Scientific Basis\r
\r
> **Status:** \`LITERATURE\` rationale and \`DESIGN\` hypotheses. No MAWRID treatment results are documented. The [project brief](project-brief.md) fixes the first use case; the [evidence register](evidence-register.md) distinguishes references, targets, simulation, and measured results.\r
\r
## 1. Fit-for-purpose treatment\r
\r
MAWRID follows a fit-for-purpose principle: treatment should be designed for the source water, intended use, exposure pathway, and required risk reduction. Producing drinking-water quality is not automatically necessary for a non-potable application, but using fewer barriers is acceptable only when evidence demonstrates that the selected treatment train meets the applicable target safely.\r
\r
The initial hypothesis is recovery of one separate university ablution source for controlled drip irrigation of ornamental plants. It excludes mixed drains and irrigation of edible crops. Neither the suitability of a candidate source nor the intended-use water quality has been demonstrated.\r
\r
## 2. Source water is variable\r
\r
Ablution water is often described as low-strength greywater, but this does not mean clean or pathogen-free. Its composition can vary with user behaviour, soap use, floor-drain connections, cleaning practices, storage time, and accidental contamination.\r
\r
Floor drains, cleaning discharges, and handwashing fixtures are possible contamination or scope-change cases, not accepted connections in the first version. Characterize and confirm the actual source before choosing treatment barriers.\r
\r
The characterization phase therefore measures distributions rather than relying on a single sample. The initial panel should include:\r
\r
- Turbidity and total suspended solids.\r
- pH, temperature, and conductivity.\r
- Chemical oxygen demand and, where practical, biochemical oxygen demand.\r
- Dissolved organic carbon or another selected organic indicator.\r
- \`E. coli\` and an appropriate indicator-organism panel.\r
- Ammonia and nutrients where relevant to the chosen end use.\r
- Surfactant or target dissolved constituent where analytical access permits.\r
\r
## 3. Multi-barrier logic\r
\r
No single stage is expected to manage every hazard.\r
\r
| Barrier | Principal role | Evidence boundary |\r
|---|---|---|\r
| Source control | Exclude unsuitable wastewater | Requires fixture survey and cross-connection control |\r
| Screening | Remove coarse debris | Not a dissolved or microbial barrier |\r
| Granular filtration | Reduce particles and turbidity | Does not guarantee pathogen removal |\r
| Adsorption, if justified | Remove selected adsorbable constituents | Biochar and alternatives require constituent- and water-specific comparison |\r
| Disinfection | Reduce microbial risk | Requires challenge validation and process monitoring |\r
| Storage controls | Limit recontamination and regrowth | Residual protection and residence time must be managed |\r
| Fail-safe diversion | Prevent release outside validated conditions | Depends on sensor, valve, software, and plumbing integrity |\r
\r
## 4. Why date-palm biochar?\r
\r
Saudi Arabia has a substantial date-palm sector and associated agricultural residues. Converting a suitable fraction into biochar could create a local adsorption medium and circular-economy pathway.\r
\r
The scientific proposition is conditional:\r
\r
> Can a reproducibly manufactured date-palm biochar match the required adsorption performance, hydraulic behaviour, safety, service life, and lifecycle cost for the selected greywater constituent?\r
\r
Biochar properties depend strongly on feedstock, pyrolysis temperature, residence time, activation method, particle size, washing, and water chemistry. Published performance for one material or contaminant cannot be transferred directly to MAWRID.\r
\r
This is an optional material study within the water-recovery concept. If no relevant adsorption need is found, or date-palm biochar adds no benefit against the simpler train and commercial-carbon comparator, omit it. Local supply, environmental benefit, reproducibility, and lower cost remain hypotheses requiring documented preparation and lifecycle boundaries. Date-palm fibre evidence must not be described as a result for pyrolyzed biochar; see the scoped descriptions in [references](../references/README.md).\r
\r
## 5. Adsorption and breakthrough\r
\r
Adsorption media have finite capacity. A fixed-bed experiment tracks inlet concentration \`Cin\` and outlet concentration \`Cout\` over time or cumulative bed volumes.\r
\r
\`\`\`text\r
Normalized concentration = Cout / Cin\r
\`\`\`\r
\r
If adsorption testing proceeds, the protocol must predefine a constituent-specific breakthrough point and an exhaustion criterion. \`Cout/Cin = 0.10\` is an **ILLUSTRATIVE** definition, not a selected MAWRID criterion, universal safety limit, or achieved result. The absolute outlet concentration and analytical limits must also be reported.\r
\r
Differential pressure cannot identify adsorption saturation. Likewise, a clear-looking effluent does not demonstrate remaining adsorption capacity.\r
\r
## 6. Surrogate monitoring\r
\r
Frequent laboratory measurement of every organic constituent may be impractical. Literature indicates that UV absorbance, including UVA254, can sometimes act as a surrogate for organic adsorption-bed condition. MAWRID will only use a surrogate after demonstrating a stable relationship with its selected target under representative source-water conditions.\r
\r
The surrogate will not be presented as:\r
\r
- A pathogen measurement.\r
- A detector for every organic compound.\r
- A substitute for periodic laboratory analysis.\r
- Evidence of regulatory compliance by itself.\r
\r
## 7. Disinfection science\r
\r
Water clarity is not microbial safety. A disinfection process must be validated using a defined organism or surrogate and representative worst-case water quality.\r
\r
For chlorination, relevant variables include free disinfectant concentration, contact time, pH, temperature, mixing, chlorine demand, and storage. The system also needs to assess disinfection by-products where source-water chemistry indicates a concern.\r
\r
For UV, relevant variables include validated dose, intensity, UV transmittance, lamp condition, and hydraulic short-circuiting. UV does not leave a protective residual.\r
\r
## 8. From rules to prediction\r
\r
The prototype begins with auditable rules:\r
\r
\`\`\`text\r
IF critical sensor invalid     → close reuse valve\r
IF turbidity outside envelope → divert or reprocess\r
IF disinfection condition fails → divert\r
IF differential pressure high → backwash or maintenance\r
IF breakthrough confirmed     → replace or regenerate media\r
\`\`\`\r
\r
Machine learning is a later research step. It requires multiple complete media-life runs, independent validation data, representative seasonal and site variation, uncertainty reporting, and performance superior to a transparent baseline model. Its recommendations cannot override the independent outlet controller or authorize irrigation.\r
\r
## 9. Scientific claim boundaries\r
\r
The following summary uses the [central evidence register](evidence-register.md); it does not add a measured result.\r
\r
| Statement | Current status |\r
|---|---|\r
| Published studies support investigating separately collected ablution water for a defined non-potable use | **LITERATURE**, not a result for the proposed university source |\r
| Date-palm residues can be converted into adsorptive biochar | **LITERATURE** |\r
| MAWRID biochar treats real ablution greywater effectively | **NOT TESTED** |\r
| Online surrogate data can predict MAWRID breakthrough | **NOT TESTED** |\r
| The physical outlet protection prevents reuse during every declared critical fault | **TARGET**, physical tests not documented |\r
| MAWRID water meets a Saudi reuse requirement | **NOT TESTED** |\r
| MAWRID is cheaper than commercial systems | **NOT TESTED** |\r
\r
Recovered water counts toward measured impact only when actually used for the defined irrigation demand. Potable-water offset additionally requires an equivalent baseline and all extra potable inputs; source volume or a simulated balance is not evidence of savings. See [impact and economics](impact-and-economics.md).\r
`;export{e as default};