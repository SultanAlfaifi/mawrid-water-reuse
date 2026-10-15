var e=`# System Design

> **Status:** \`DESIGN\` concept architecture. No physical treatment result, tested outlet protection, confirmed university partnership, or site approval is documented. Component sizing and operating limits require bench and site-specific validation.

This document follows the [project brief](project-brief.md) and [evidence register](evidence-register.md). It specifies intended behaviour; the digital explorer does not demonstrate that the hardware exists or performs as described.

## 1. Design objective

The first concept recovers **one separately collected ablution-water source at one university facility** for a defined landscape-irrigation demand. The proposed initial use is a controlled zone of ornamental plants with drip irrigation, subject to site, exposure, and applicable-requirements review. Source quality and recoverable volume are hypotheses to measure, not established properties.

The architecture prioritizes low treatment complexity, observable operation, maintainability, and failure toward non-reuse. Additional handwashing drains require separate characterization and a scope change in the project brief before inclusion.

The design does not include toilet wastewater, kitchen wastewater, grease-bearing drains, industrial wastewater, or unidentified mixed drainage.

## 2. Functional architecture

\`\`\`text
One university ablution drain
        │
        ▼
Coarse screen ──────────────── screenings to controlled disposal
        │
        ▼
Raw-water equalization tank ── overflow to approved sewer
        │
        ▼
Feed pump + flow control
        │
        ▼
Sand / multimedia filter ───── backwash to approved sewer or treatment
        │
        ▼
Optional adsorption stage ──── selected only if characterization justifies it
        │
        ▼
Controlled disinfection + verified contact condition
        │
        ▼
Treated-water tank + age/condition checks
        │
        ▼
Independent outlet controller + decision manifold
        ├── PASS → defined irrigation zone, after pilot approval
        └── HOLD/FAIL → reprocess, contain, or approved sewer
\`\`\`

The diagram is a candidate functional arrangement, not a construction drawing. Storage and the irrigation outlet must remain within the validated operating envelope; if stored-water age or a critical downstream condition is unknown, the independent outlet protection keeps reuse closed. Discharge destinations shown as approved are requirements to obtain, not existing approvals.

## 3. Treatment barriers

### 3.1 Source separation

Source control is the first barrier. Dedicated drainage prevents high-load or hazardous streams from entering the system. The pilot must document every connected fixture and complete cross-connection checks before operation.

### 3.2 Screening and equalization

A removable screen protects pumps and filters from hair, fibres, sand, and coarse debris. The equalization tank buffers the intermittent hydraulic pattern of ablution periods and enables a controlled treatment flow.

Design requirements include a cleanout, high-level overflow, low-level pump protection, level sensing, accessible sampling, and a residence-time limit to reduce stagnation.

### 3.3 Sand or multimedia filtration

This stage targets suspended solids and turbidity and supports downstream treatment. It protects an adsorption bed if one is justified. Media grading, filtration velocity, run length, backwash trigger, and backwash volume will be selected experimentally.

### 3.4 Date-palm biochar adsorption

Adsorption is included only if source characterization identifies a relevant dissolved constituent that simpler treatment does not adequately address. A candidate cartridge then investigates whether date-palm-derived biochar provides useful capacity for that **preselected constituent**. Candidate media will be characterized for:

- Feedstock identity and preparation.
- Pyrolysis and activation conditions.
- Particle-size distribution and bulk density.
- Surface area and pore characteristics where laboratory access permits.
- Ash, pH effects, fines, metals, and organic leachates.
- Empty-bed contact time and hydraulic head loss.
- Capacity and bed volumes to a defined breakthrough criterion.

The simpler train without adsorption and commercial activated carbon are comparators. If adsorption is unnecessary, or biochar adds no justified benefit after performance, leaching, hydraulics, maintenance, and cost are considered, the project advances with the simpler train or a supported alternative. Local origin alone is not evidence of better performance or lower lifecycle cost.

### 3.5 Disinfection

Disinfection is a distinct microbial barrier. The baseline concept uses controlled chlorination because a measurable residual can help protect treated-water storage and distribution. Validation must account for disinfectant demand, pH, temperature, contact time, microbial reduction, and potential by-products.

UV may be evaluated if testing shows a clear need. It would require validated UV dose and transmittance monitoring and would not provide a distribution residual.

### 3.6 Treated-water storage and delivery

The treated-water tank is physically separate from drinking-water and raw-water systems. It requires non-potable identification, protected make-up water, backflow prevention, controlled storage time, hygienic access, overflow management, and a sampling point.

## 4. Instrumentation

| Instrument | Location | Control purpose |
|---|---|---|
| Level sensors | Raw and treated tanks | Pump interlocks, overflow prevention, demand management |
| Flow meter | Treatment inlet and reuse outlet | Loading, recovery, water balance, bed volumes |
| Pressure sensors | Before and after granular filters | Differential pressure and clogging detection |
| Turbidity | Before and after filtration | Particulate loading and filtration integrity |
| pH and temperature | Before disinfection | Process envelope and disinfectant control |
| Conductivity | Inlet and outlet | Source-change and salinity indicator |
| Free chlorine | After verified contact time | Chlorination process condition |
| UV254, optional | Across adsorption bed | Candidate organic breakthrough surrogate after correlation testing |

Low-cost sensors require calibration, fouling checks, declared uncertainty, and reference measurements. No listed sensor can independently certify microbial safety.

## 5. Operating states

| State | Description | Reuse valve |
|---|---|---|
| \`STARTUP\` | Flush, initialize, and confirm sensor health | Closed |
| \`TREAT\` | Water moves through treatment; release not yet authorized | Closed |
| \`REUSE_READY\` | All validated release conditions are satisfied | Open on demand |
| \`REPROCESS\` | Recoverable water is returned for another pass | Closed |
| \`DIVERT\` | Water is sent to an approved sewer or containment route | Closed |
| \`BACKWASH\` | Granular filter cleaning sequence | Closed |
| \`MAINTENANCE\` | Manual service, calibration, or media replacement | Locked closed |
| \`FAULT\` | Critical data or process integrity is unavailable | Fail-closed |

These states specify the proposed physical controller, not measured valve behaviour. \`REUSE_READY\` describes eligibility under validated process rules; it is not a certificate of water quality. Site authorization and laboratory verification remain separate requirements.

The independent local controller must not infer release permission from the last valid reading after sensor loss or power interruption. The website, remote dashboard, and any future AI model cannot open the reuse outlet. Bench testing must verify the physical valve position and destination flow, including loss of power and communications.

## 6. Condition-based media management

Two distinct mechanisms are tracked:

- **Clogging:** rising differential pressure or declining hydraulic capacity. Cleaning or backwash may restore performance.
- **Adsorption breakthrough:** increasing outlet concentration of the selected dissolved constituent relative to its inlet concentration. Media regeneration or replacement is required.

Bed volumes provide a loading basis:

\`\`\`text
Bed volumes treated = cumulative treated volume / packed media-bed volume
\`\`\`

The first controller will use transparent rules based on measured thresholds and cumulative loading. Predictive models will only be evaluated after multiple independent exhaustion runs are available.

## 7. Modular scale-up

No treatment capacity or production size has been selected. A name such as \`M5\`, or the dimensions of the illustrative 3D unit, establishes neither \`5 m³/day\` nor any tested hydraulic capacity. Sizing follows measured source availability, irrigation demand, storage constraints, and validated loading/contact conditions. Parallel treatment trains or lead-lag adsorption are later design options, not current product configurations. Any scale-up must preserve the validated process envelope.

## 8. Open design decisions

- Confirm the proposed university source and controlled ornamental-irrigation zone, including demand and the approval path.
- Characterize representative influent variability.
- Decide whether adsorption is justified; if so, select the target constituent, analytical method, and comparable media.
- If biochar testing proceeds, determine its preparation and activation route.
- Validate hydraulic loading and contact time.
- Select disinfectant and contact configuration.
- Confirm current Saudi plumbing, building, water-reuse, and discharge requirements.
- Complete a hazard review before construction.
`;export{e as default};