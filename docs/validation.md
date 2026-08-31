# Experimental Validation

> **Purpose:** Generate reproducible evidence for treatment performance, media life, safe control, and pilot feasibility.

## 1. Experimental questions

1. How variable is the selected source water over users, peak periods, cleaning events, and storage times?
2. What does each treatment barrier contribute?
3. Does date-palm biochar outperform a no-biochar control and approach commercial activated-carbon performance for the selected target?
4. How many bed volumes are treated before defined breakthrough?
5. Can online measurements provide useful advance warning of that breakthrough?
6. Does disinfection achieve the selected microbial target under representative worst-case conditions?
7. Does the system divert water reliably during sensor, process, communication, and power faults?
8. What are net recovery, energy, consumables, residuals, and cost per cubic metre?

## 2. Phase A: source characterization

Collect time-stamped samples from the proposed pilot source across:

- Low, normal, and peak use.
- Different days and cleaning schedules.
- With and without soap-dominant handwashing inputs if these are included.
- Immediate testing and defined storage intervals.

Record fixture connections, weather where relevant, flow, temperature, sampling method, holding time, and analytical method.

## 3. Phase B: media screening

### Test matrix

| ID | Treatment | Purpose |
|---|---|---|
| A | Untreated source water | Influent baseline |
| B | Sand or multimedia only | Particulate-removal control |
| C | Raw date-palm biochar only | Adsorption and leaching screen |
| D | Sand + raw date-palm biochar | Combined untreated-media train |
| E | Sand + activated date-palm biochar | Candidate optimized train |
| F | Sand + commercial activated carbon | Industry benchmark |
| G | Full train + disinfection | End-to-end validation candidate |

At least one blank and a no-biochar control are required. Replicate counts and sample size will be declared before testing.

## 4. Phase C: fixed-bed breakthrough

For each adsorption medium:

1. Record packed-bed volume, media mass, bulk density, particle size, and empty-bed contact time.
2. Maintain a declared flow and measure actual flow continuously.
3. Sample paired influent and effluent at planned bed-volume intervals.
4. Plot `Cout/Cin` against bed volumes.
5. Declare breakthrough and exhaustion criteria before viewing final results.
6. Repeat complete exhaustion runs to quantify between-run variability.
7. Test representative changes in influent concentration and hydraulic loading.

Removal efficiency is reported as:

```text
Removal efficiency (%) = ((Cin − Cout) / Cin) × 100
```

When `Cin` is near the analytical detection limit, removal percentages may be misleading; raw concentrations and method limits must also be reported.

## 5. Phase D: disinfection validation

The disinfection study defines:

- Challenge organism or accepted surrogate.
- Influent concentration range.
- Worst-case turbidity, pH, temperature, and disinfectant demand.
- Dose or intensity and effective contact time.
- Sampling and neutralization procedure.
- Reference analytical method.
- Required log reduction and release conditions.
- Storage and regrowth observations.

Disinfection performance is never inferred from water clarity alone.

## 6. Phase E: monitoring model

Candidate inputs include:

- Inlet and outlet turbidity.
- Flow and cumulative treated volume.
- Bed volumes.
- Differential pressure.
- pH, temperature, and conductivity.
- Optional UV254 across the adsorption bed.
- Media batch and preparation conditions.
- Laboratory target-constituent measurements.

The first baseline is a transparent threshold or regression model. A more complex model must be evaluated prospectively on independent exhaustion runs and compared against the baseline.

### Provisional model targets

- Warning at least 10 bed volumes before defined breakthrough.
- Remaining-life error no greater than 20% after at least three independent complete exhaustion runs.
- Uncertainty or “insufficient confidence” state exposed to the controller.
- No release decision made by the prediction model alone.

## 7. Phase F: fault injection

Every fault test records event time, controller state, valve response, destination flow, alarm, operator action, and recovery.

| Fault | Expected response |
|---|---|
| High outlet turbidity | Reuse valve closes; water diverts |
| Disinfectant condition below limit | Reuse valve closes; water diverts |
| Critical sensor disconnected | Invalid-data state; reuse valve closes |
| Implausible or frozen sensor value | Plausibility failure; reuse valve closes |
| Controller communication loss | Local fail-safe state; reuse valve closes |
| Power interruption | De-energized valve moves to non-reuse position |
| Treated tank high level | Stop or divert without uncontrolled overflow |
| Raw tank low level | Pump stops to prevent dry running |

## 8. Measurements

| Category | Core measurements |
|---|---|
| Physical | Flow, temperature, turbidity, total suspended solids, pressure drop |
| Chemical | pH, conductivity, COD, selected dissolved-organic indicator, disinfectant condition |
| Microbial | `E. coli` and the selected validation panel |
| Operational | Bed volumes, downtime, backwash frequency, media use, calibration status |
| Resource | Inlet, reuse, reject, backwash, make-up water, energy, consumables |
| Cost | Equipment, installation, media, chemicals, laboratory work, labour, maintenance |

Laboratory methods should follow an accredited or otherwise recognized standard. Raw data, units, detection limits, calibration records, exclusions, and analysis scripts must be retained.

## 9. Results template

No placeholder value should be presented as a result. Each published result includes:

```text
Label: RESULT
Metric:
Source and test condition:
Sample size:
Method and detection limit:
Influent distribution:
Effluent distribution:
Estimate and uncertainty:
Raw-data path:
Protocol deviation, if any:
```

## 10. Pilot gate

Proceed from bench work to a site pilot only when:

- The selected treatment train meets all predeclared bench acceptance criteria.
- The disinfection barrier is validated for the chosen end use.
- Biochar leaching and residuals risks are characterized.
- Fail-safe fault tests pass.
- Plumbing and cross-connection controls are reviewed by qualified professionals.
- Required Saudi regulatory and site approvals are identified and obtained.
- A sampling, maintenance, incident, and shutdown plan is approved.
