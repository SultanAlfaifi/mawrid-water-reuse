# Scientific Basis

> **Status:** `LITERATURE` rationale and `DESIGN` hypotheses. No MAWRID treatment results are documented. The [project brief](project-brief.md) fixes the first use case; the [evidence register](evidence-register.md) distinguishes references, targets, simulation, and measured results.

## 1. Fit-for-purpose treatment

MAWRID follows a fit-for-purpose principle: treatment should be designed for the source water, intended use, exposure pathway, and required risk reduction. Producing drinking-water quality is not automatically necessary for a non-potable application, but using fewer barriers is acceptable only when evidence demonstrates that the selected treatment train meets the applicable target safely.

The initial hypothesis is recovery of one separate, characterized facility ablution source for controlled drip irrigation of ornamental plants. It excludes mixed drains and irrigation of edible crops. Neither the suitability of a candidate source nor the intended-use water quality has been demonstrated.

## 2. Source water is variable

Ablution water is often described as low-strength greywater, but this does not mean clean or pathogen-free. Its composition can vary with user behaviour, soap use, floor-drain connections, cleaning practices, storage time, and accidental contamination.

Floor drains, cleaning discharges, and handwashing fixtures are possible contamination or scope-change cases, not accepted connections in the first version. Characterize and confirm the actual source before choosing treatment barriers.

The characterization phase therefore measures distributions rather than relying on a single sample. The initial panel should include:

- Turbidity and total suspended solids.
- pH, temperature, and conductivity.
- Chemical oxygen demand and, where practical, biochemical oxygen demand.
- Dissolved organic carbon or another selected organic indicator.
- `E. coli` and an appropriate indicator-organism panel.
- Ammonia and nutrients where relevant to the chosen end use.
- Surfactant or target dissolved constituent where analytical access permits.

## 3. Multi-barrier logic

No single stage is expected to manage every hazard.

| Barrier | Principal role | Evidence boundary |
|---|---|---|
| Source control | Exclude unsuitable wastewater | Requires fixture survey and cross-connection control |
| Screening | Remove coarse debris | Not a dissolved or microbial barrier |
| Granular filtration | Reduce particles and turbidity | Does not guarantee pathogen removal |
| Adsorption, if justified | Remove selected adsorbable constituents | Biochar and alternatives require constituent- and water-specific comparison |
| Disinfection | Reduce microbial risk | Requires challenge validation and process monitoring |
| Storage controls | Limit recontamination and regrowth | Residual protection and residence time must be managed |
| Fail-safe diversion | Prevent release outside validated conditions | Depends on sensor, valve, software, and plumbing integrity |

## 4. Why date-palm biochar?

Saudi Arabia has a substantial date-palm sector and associated agricultural residues. Converting a suitable fraction into biochar could create a local adsorption medium and circular-economy pathway.

The scientific proposition is conditional:

> Can a reproducibly manufactured date-palm biochar match the required adsorption performance, hydraulic behaviour, safety, service life, and lifecycle cost for the selected greywater constituent?

Biochar properties depend strongly on feedstock, pyrolysis temperature, residence time, activation method, particle size, washing, and water chemistry. Published performance for one material or contaminant cannot be transferred directly to MAWRID.

This is an optional material study within the water-recovery concept. If no relevant adsorption need is found, or date-palm biochar adds no benefit against the simpler train and commercial-carbon comparator, omit it. Local supply, environmental benefit, reproducibility, and lower cost remain hypotheses requiring documented preparation and lifecycle boundaries. Date-palm fibre evidence must not be described as a result for pyrolyzed biochar; see the scoped descriptions in [references](../references/README.md).

## 5. Adsorption and breakthrough

Adsorption media have finite capacity. A fixed-bed experiment tracks inlet concentration `Cin` and outlet concentration `Cout` over time or cumulative bed volumes.

```text
Normalized concentration = Cout / Cin
```

If adsorption testing proceeds, the protocol must predefine a constituent-specific breakthrough point and an exhaustion criterion. `Cout/Cin = 0.10` is an **ILLUSTRATIVE** definition, not a selected MAWRID criterion, universal safety limit, or achieved result. The absolute outlet concentration and analytical limits must also be reported.

Differential pressure cannot identify adsorption saturation. Likewise, a clear-looking effluent does not demonstrate remaining adsorption capacity.

## 6. Surrogate monitoring

Frequent laboratory measurement of every organic constituent may be impractical. Literature indicates that UV absorbance, including UVA254, can sometimes act as a surrogate for organic adsorption-bed condition. MAWRID will only use a surrogate after demonstrating a stable relationship with its selected target under representative source-water conditions.

The surrogate will not be presented as:

- A pathogen measurement.
- A detector for every organic compound.
- A substitute for periodic laboratory analysis.
- Evidence of regulatory compliance by itself.

## 7. Disinfection science

Water clarity is not microbial safety. A disinfection process must be validated using a defined organism or surrogate and representative worst-case water quality.

For chlorination, relevant variables include free disinfectant concentration, contact time, pH, temperature, mixing, chlorine demand, and storage. The system also needs to assess disinfection by-products where source-water chemistry indicates a concern.

For UV, relevant variables include validated dose, intensity, UV transmittance, lamp condition, and hydraulic short-circuiting. UV does not leave a protective residual.

## 8. From rules to prediction

The prototype begins with auditable rules:

```text
IF critical sensor invalid     → close reuse valve
IF turbidity outside envelope → divert or reprocess
IF disinfection condition fails → divert
IF differential pressure high → backwash or maintenance
IF breakthrough confirmed     → replace or regenerate media
```

Machine learning is a later research step. It requires multiple complete media-life runs, independent validation data, representative seasonal and site variation, uncertainty reporting, and performance superior to a transparent baseline model. Its recommendations cannot override the independent outlet controller or authorize irrigation.

## 9. Scientific claim boundaries

The following summary uses the [central evidence register](evidence-register.md); it does not add a measured result.

| Statement | Current status |
|---|---|
| Published studies support investigating separately collected ablution water for a defined non-potable use | **LITERATURE**, not a result for the proposed site source |
| Date-palm residues can be converted into adsorptive biochar | **LITERATURE** |
| MAWRID biochar treats real ablution greywater effectively | **NOT TESTED** |
| Online surrogate data can predict MAWRID breakthrough | **NOT TESTED** |
| The physical outlet protection prevents reuse during every declared critical fault | **TARGET**, physical tests not documented |
| MAWRID water meets a Saudi reuse requirement | **NOT TESTED** |
| MAWRID is cheaper than commercial systems | **NOT TESTED** |

Recovered water counts toward measured impact only when actually used for the defined irrigation demand. Potable-water offset additionally requires an equivalent baseline and all extra potable inputs; source volume or a simulated balance is not evidence of savings. See [impact and economics](impact-and-economics.md).
