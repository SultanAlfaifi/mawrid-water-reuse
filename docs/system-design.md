# System Design

> **Status:** Concept architecture. Component sizing and release limits require bench and site-specific validation.

## 1. Design objective

MAWRID is designed to recover **source-separated, lightly contaminated ablution and selected handwashing greywater** and treat it for one approved non-potable use. The architecture prioritizes low treatment complexity, observable operation, maintainability, and safe failure.

The design does not include toilet wastewater, kitchen wastewater, grease-bearing drains, industrial wastewater, or unidentified mixed drainage.

## 2. Functional architecture

```text
Source-separated drain
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
Date-palm biochar cartridge
        │
        ▼
Controlled disinfection + verified contact condition
        │
        ▼
Quality decision manifold
        ├── PASS → treated-water tank → approved non-potable use
        └── HOLD/FAIL → reprocess, contain, or approved sewer
```

## 3. Treatment barriers

### 3.1 Source separation

Source control is the first barrier. Dedicated drainage prevents high-load or hazardous streams from entering the system. The pilot must document every connected fixture and complete cross-connection checks before operation.

### 3.2 Screening and equalization

A removable screen protects pumps and filters from hair, fibres, sand, and coarse debris. The equalization tank buffers the intermittent hydraulic pattern of ablution periods and enables a controlled treatment flow.

Design requirements include a cleanout, high-level overflow, low-level pump protection, level sensing, accessible sampling, and a residence-time limit to reduce stagnation.

### 3.3 Sand or multimedia filtration

This stage targets suspended solids and turbidity. It protects the adsorption bed and improves the consistency of downstream disinfection. Media grading, filtration velocity, run length, backwash trigger, and backwash volume will be selected experimentally.

### 3.4 Date-palm biochar adsorption

The cartridge investigates whether date-palm-derived biochar can provide useful adsorption capacity for a **preselected dissolved constituent**. Candidate media will be characterized for:

- Feedstock identity and preparation.
- Pyrolysis and activation conditions.
- Particle-size distribution and bulk density.
- Surface area and pore characteristics where laboratory access permits.
- Ash, pH effects, fines, metals, and organic leachates.
- Empty-bed contact time and hydraulic head loss.
- Capacity and bed volumes to a defined breakthrough criterion.

Commercial activated carbon is the benchmark. Local origin alone is not evidence of better performance or lower lifecycle cost.

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
| `STARTUP` | Flush, initialize, and confirm sensor health | Closed |
| `TREAT` | Water moves through treatment; release not yet authorized | Closed |
| `REUSE_READY` | All validated release conditions are satisfied | Open on demand |
| `REPROCESS` | Recoverable water is returned for another pass | Closed |
| `DIVERT` | Water is sent to an approved sewer or containment route | Closed |
| `BACKWASH` | Granular filter cleaning sequence | Closed |
| `MAINTENANCE` | Manual service, calibration, or media replacement | Locked closed |
| `FAULT` | Critical data or process integrity is unavailable | Fail-closed |

The controller must not infer safe release from the last valid reading after sensor loss or power interruption.

## 6. Condition-based media management

Two distinct mechanisms are tracked:

- **Clogging:** rising differential pressure or declining hydraulic capacity. Cleaning or backwash may restore performance.
- **Adsorption breakthrough:** increasing outlet concentration of the selected dissolved constituent relative to its inlet concentration. Media regeneration or replacement is required.

Bed volumes provide a loading basis:

```text
Bed volumes treated = cumulative treated volume / packed media-bed volume
```

The first controller will use transparent rules based on measured thresholds and cumulative loading. Predictive models will only be evaluated after multiple independent exhaustion runs are available.

## 7. Modular scale-up

Scale is defined by tested hydraulic capacity, not by marketing labels. Parallel treatment trains may increase flow; series lead-lag adsorption may increase protection and media utilization. Any scale-up must preserve contact time, loading, backwash performance, monitoring coverage, and the validated disinfection envelope.

## 8. Open design decisions

- Select the first approved end use.
- Characterize representative influent variability.
- Select the biochar target constituent and analytical method.
- Determine media preparation and activation route.
- Validate hydraulic loading and contact time.
- Select disinfectant and contact configuration.
- Confirm current Saudi plumbing, building, water-reuse, and discharge requirements.
- Complete a hazard review before construction.
