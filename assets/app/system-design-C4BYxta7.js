var e=`# System Design\r
\r
> **Status:** \`DESIGN\` concept architecture. No physical treatment result, tested outlet protection, confirmed university partnership, or site approval is documented. Component sizing and operating limits require bench and site-specific validation.\r
\r
This document follows the [project brief](project-brief.md) and [evidence register](evidence-register.md). It specifies intended behaviour; the digital explorer does not demonstrate that the hardware exists or performs as described.\r
\r
## 1. Design objective\r
\r
The first concept recovers **one separately collected ablution-water source at one university facility** for a defined landscape-irrigation demand. The proposed initial use is a controlled zone of ornamental plants with drip irrigation, subject to site, exposure, and applicable-requirements review. Source quality and recoverable volume are hypotheses to measure, not established properties.\r
\r
The architecture prioritizes low treatment complexity, observable operation, maintainability, and failure toward non-reuse. Additional handwashing drains require separate characterization and a scope change in the project brief before inclusion.\r
\r
The design does not include toilet wastewater, kitchen wastewater, grease-bearing drains, industrial wastewater, or unidentified mixed drainage.\r
\r
## 2. Functional architecture\r
\r
\`\`\`text\r
One university ablution drain\r
        │\r
        ▼\r
Coarse screen ──────────────── screenings to controlled disposal\r
        │\r
        ▼\r
Raw-water equalization tank ── overflow to approved sewer\r
        │\r
        ▼\r
Feed pump + flow control\r
        │\r
        ▼\r
Sand / multimedia filter ───── backwash to approved sewer or treatment\r
        │\r
        ▼\r
Optional adsorption stage ──── selected only if characterization justifies it\r
        │\r
        ▼\r
Controlled disinfection + verified contact condition\r
        │\r
        ▼\r
Treated-water tank + age/condition checks\r
        │\r
        ▼\r
Independent outlet controller + decision manifold\r
        ├── PASS → defined irrigation zone, after pilot approval\r
        └── HOLD/FAIL → reprocess, contain, or approved sewer\r
\`\`\`\r
\r
The diagram is a candidate functional arrangement, not a construction drawing. Storage and the irrigation outlet must remain within the validated operating envelope; if stored-water age or a critical downstream condition is unknown, the independent outlet protection keeps reuse closed. Discharge destinations shown as approved are requirements to obtain, not existing approvals.\r
\r
## 3. Treatment barriers\r
\r
### 3.1 Source separation\r
\r
Source control is the first barrier. Dedicated drainage prevents high-load or hazardous streams from entering the system. The pilot must document every connected fixture and complete cross-connection checks before operation.\r
\r
### 3.2 Screening and equalization\r
\r
A removable screen protects pumps and filters from hair, fibres, sand, and coarse debris. The equalization tank buffers the intermittent hydraulic pattern of ablution periods and enables a controlled treatment flow.\r
\r
Design requirements include a cleanout, high-level overflow, low-level pump protection, level sensing, accessible sampling, and a residence-time limit to reduce stagnation.\r
\r
### 3.3 Sand or multimedia filtration\r
\r
This stage targets suspended solids and turbidity and supports downstream treatment. It protects an adsorption bed if one is justified. Media grading, filtration velocity, run length, backwash trigger, and backwash volume will be selected experimentally.\r
\r
### 3.4 Date-palm biochar adsorption\r
\r
Adsorption is included only if source characterization identifies a relevant dissolved constituent that simpler treatment does not adequately address. A candidate cartridge then investigates whether date-palm-derived biochar provides useful capacity for that **preselected constituent**. Candidate media will be characterized for:\r
\r
- Feedstock identity and preparation.\r
- Pyrolysis and activation conditions.\r
- Particle-size distribution and bulk density.\r
- Surface area and pore characteristics where laboratory access permits.\r
- Ash, pH effects, fines, metals, and organic leachates.\r
- Empty-bed contact time and hydraulic head loss.\r
- Capacity and bed volumes to a defined breakthrough criterion.\r
\r
The simpler train without adsorption and commercial activated carbon are comparators. If adsorption is unnecessary, or biochar adds no justified benefit after performance, leaching, hydraulics, maintenance, and cost are considered, the project advances with the simpler train or a supported alternative. Local origin alone is not evidence of better performance or lower lifecycle cost.\r
\r
### 3.5 Disinfection\r
\r
Disinfection is a distinct microbial barrier. The baseline concept uses controlled chlorination because a measurable residual can help protect treated-water storage and distribution. Validation must account for disinfectant demand, pH, temperature, contact time, microbial reduction, and potential by-products.\r
\r
UV may be evaluated if testing shows a clear need. It would require validated UV dose and transmittance monitoring and would not provide a distribution residual.\r
\r
### 3.6 Treated-water storage and delivery\r
\r
The treated-water tank is physically separate from drinking-water and raw-water systems. It requires non-potable identification, protected make-up water, backflow prevention, controlled storage time, hygienic access, overflow management, and a sampling point.\r
\r
## 4. Instrumentation\r
\r
| Instrument | Location | Control purpose |\r
|---|---|---|\r
| Level sensors | Raw and treated tanks | Pump interlocks, overflow prevention, demand management |\r
| Flow meter | Treatment inlet and reuse outlet | Loading, recovery, water balance, bed volumes |\r
| Pressure sensors | Before and after granular filters | Differential pressure and clogging detection |\r
| Turbidity | Before and after filtration | Particulate loading and filtration integrity |\r
| pH and temperature | Before disinfection | Process envelope and disinfectant control |\r
| Conductivity | Inlet and outlet | Source-change and salinity indicator |\r
| Free chlorine | After verified contact time | Chlorination process condition |\r
| UV254, optional | Across adsorption bed | Candidate organic breakthrough surrogate after correlation testing |\r
\r
Low-cost sensors require calibration, fouling checks, declared uncertainty, and reference measurements. No listed sensor can independently certify microbial safety.\r
\r
## 5. Operating states\r
\r
| State | Description | Reuse valve |\r
|---|---|---|\r
| \`STARTUP\` | Flush, initialize, and confirm sensor health | Closed |\r
| \`TREAT\` | Water moves through treatment; release not yet authorized | Closed |\r
| \`REUSE_READY\` | All validated release conditions are satisfied | Open on demand |\r
| \`REPROCESS\` | Recoverable water is returned for another pass | Closed |\r
| \`DIVERT\` | Water is sent to an approved sewer or containment route | Closed |\r
| \`BACKWASH\` | Granular filter cleaning sequence | Closed |\r
| \`MAINTENANCE\` | Manual service, calibration, or media replacement | Locked closed |\r
| \`FAULT\` | Critical data or process integrity is unavailable | Fail-closed |\r
\r
These states specify the proposed physical controller, not measured valve behaviour. \`REUSE_READY\` describes eligibility under validated process rules; it is not a certificate of water quality. Site authorization and laboratory verification remain separate requirements.\r
\r
The independent local controller must not infer release permission from the last valid reading after sensor loss or power interruption. The website, remote dashboard, and any future AI model cannot open the reuse outlet. Bench testing must verify the physical valve position and destination flow, including loss of power and communications.\r
\r
## 6. Condition-based media management\r
\r
Two distinct mechanisms are tracked:\r
\r
- **Clogging:** rising differential pressure or declining hydraulic capacity. Cleaning or backwash may restore performance.\r
- **Adsorption breakthrough:** increasing outlet concentration of the selected dissolved constituent relative to its inlet concentration. Media regeneration or replacement is required.\r
\r
Bed volumes provide a loading basis:\r
\r
\`\`\`text\r
Bed volumes treated = cumulative treated volume / packed media-bed volume\r
\`\`\`\r
\r
The first controller will use transparent rules based on measured thresholds and cumulative loading. Predictive models will only be evaluated after multiple independent exhaustion runs are available.\r
\r
## 7. Modular scale-up\r
\r
No treatment capacity or production size has been selected. A name such as \`M5\`, or the dimensions of the illustrative 3D unit, establishes neither \`5 m³/day\` nor any tested hydraulic capacity. Sizing follows measured source availability, irrigation demand, storage constraints, and validated loading/contact conditions. Parallel treatment trains or lead-lag adsorption are later design options, not current product configurations. Any scale-up must preserve the validated process envelope.\r
\r
## 8. Open design decisions\r
\r
- Confirm the proposed university source and controlled ornamental-irrigation zone, including demand and the approval path.\r
- Characterize representative influent variability.\r
- Decide whether adsorption is justified; if so, select the target constituent, analytical method, and comparable media.\r
- If biochar testing proceeds, determine its preparation and activation route.\r
- Validate hydraulic loading and contact time.\r
- Select disinfectant and contact configuration.\r
- Confirm current Saudi plumbing, building, water-reuse, and discharge requirements.\r
- Complete a hazard review before construction.\r
`;export{e as default};