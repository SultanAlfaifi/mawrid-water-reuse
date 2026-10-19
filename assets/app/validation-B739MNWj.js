var e=`# Experimental Validation

> **Purpose:** Generate reproducible evidence for treatment performance, media life, safe control, and pilot feasibility.

> **Status:** \`DESIGN\` / \`TARGET\` validation plan. This is not a completed experimental protocol or a results report. There are no documented MAWRID water-treatment results, confirmed university partner, laboratory commitment, or field-use approval. Scope and evidence labels follow the [project brief](project-brief.md) and [evidence register](evidence-register.md).

The intended source is separately collected ablution and washbasin water, characterized by connected fixtures and cleaning practices. The proposed use is a controlled ornamental-plant zone with drip irrigation, after source/use review and required approvals. No field irrigation is part of the initial bench study, and no particular university or site is confirmed.

The current base train uses **commercial activated carbon**. Date-palm-residue carbon is a future material study, compared under equivalent conditions before any replacement. This current scope supersedes the earlier requirement to include palm carbon in the base train. A failed material study does not authorize irrigation or weaken the independently validated treatment and protection requirements.

The station design basis is **1,000 L/hour and 15 m³/day at 15 operating hours**, with two 5 m³ tanks. These are unvalidated design values, not a bench-test size, measured supply or guaranteed output. No fixed 80% recovery or continuous RO reject is assumed. The earlier 100 L/day bench-cost example and 20 m³/day study are historical planning examples. Freeze actual test volumes, operating conditions and acceptance criteria independently before testing.

## 1. Experimental questions

### Rabigh prototype targets from the final deck

The [19 October Rabigh plan](rabigh-plan.md) names the Energy and Water Academy as a proposed test location and reports the team's interest claim. It does not establish a signed test agreement. Its SAR 9,500 / six-week plan is a resource estimate, not a results report. Record all the following as \`TARGET\` until measured:

| Planned check | Target and measurement boundary |
|---|---|
| Irrigation shutdown | No more than 10 seconds in all 20 defined challenge cases; time physical valve feedback and destination flow, not the browser animation |
| Critical sensor or power disconnection | Irrigation inhibited in all 10 planned disconnections; a stated 99% figure is not permission to tolerate unsafe release |
| Turbidity | Deck target: mean below 2 NTU and no sample above 5 NTU; freeze sampling and averaging before testing. These are team targets, not verified regulatory limits |
| Turbidity calibration | At least 18 of 20 reference comparisons within ±10%; specify range, near-zero treatment and uncertainty |
| Run, records and laboratory | Seven-day run, reconciled volumes/events and three samples passing a predeclared accredited-lab panel; three samples alone do not establish safety across all operating conditions |

Do not loosen the virtual simulator's current 2 NTU rule to the deck's 5 NTU sample ceiling. Current simulated power loss stops pumps and closes valves; it does not demonstrate a physical gravity-drain path. The proposed ESP32/Raspberry Pi 5/UPS hardware and fail-safe drainage must be tested separately. ORP alone does not establish free chlorine, disinfection contact conditions or microbial absence.

### Questions for the frozen protocol

1. How variable is the selected source water over users, peak periods, cleaning events, and storage times?
2. What does each treatment barrier contribute?
3. Does the commercial-carbon base train meet its target-specific requirements, and can a later date-palm-carbon candidate match or improve that performance without unacceptable leaching or operating burden?
4. How many bed volumes are treated before defined breakthrough?
5. Can online measurements provide useful advance warning of that breakthrough?
6. Does disinfection achieve the selected microbial target under representative worst-case conditions?
7. Does the system divert water reliably during sensor, process, communication, and power faults?
8. What are measured recovery, irrigation water actually used, source-specific offset against equivalent demand, energy, consumables, residuals, and cost per cubic metre?

### Before a test can produce a reported result

Freeze a protocol identifier/version, source and intended-use boundaries, target constituent and analytical method, sampling locations and timing, media recipe/batch, hydraulic loading/contact conditions, storage intervals, independent-run and replicate counts, quality controls, uncertainty method, exclusions, and pass/fail criteria. For microbial work, specify the challenge organism or accepted surrogate, method, detection limit, contact conditions, and use-specific target. Record which inputs remain unresolved; do not fill them with demonstration values.

Tests require appropriate facilities, trained staff, and permission for the activity. Evidence from a simulation, a laboratory material test, a controller bench test, and a monitored irrigation pilot is reported separately.

## 2. Phase A: source characterization

Collect time-stamped samples from the proposed pilot source across:

- Low, normal, and peak use.
- Different days and cleaning schedules.
- Ablution-source variation and documented cleaning/contamination events; unsuitable streams remain excluded.
- Immediate testing and defined storage intervals.

Record fixture connections, weather where relevant, flow, temperature, sampling method, holding time, and analytical method.

Measure irrigation demand and its existing supply source over comparable periods. Characterize each proposed washbasin connection and cleaning/contamination route separately; belonging to the declared source category does not establish equivalent water quality or approve every connection.

## 3. Phase B: media screening

### Test matrix

Characterization defines the adsorption need, target constituent and test conditions. The current base train uses commercial activated carbon. The following arms support a future palm-material comparison; they are not evidence that a material or full train has been tested. Select relevant arms and freeze their conditions before data collection.

| ID | Treatment | Purpose |
|---|---|---|
| A | Untreated source water | Influent baseline |
| B | Sand or multimedia only | No-carbon particulate-removal control |
| C | Raw date-palm biochar only | Future adsorption/leaching screen |
| D | Sand + raw date-palm biochar | Future untreated-material candidate |
| E | Sand + activated date-palm biochar | Future optimized-material candidate |
| F | Sand + commercial activated carbon | Base-medium benchmark |
| G | Full commercial-carbon train + disinfection | Current end-to-end validation candidate |
| H | Full qualified palm-carbon train + equivalent disinfection | Later replacement candidate, only after material qualification |

Include blanks and a no-biochar control in material screening. Declare sample size and independent replicates before testing. Apply equivalent disinfection and hydraulic conditions to relevant full-train comparisons. Passing one arm does not pass another; no material test alone authorizes irrigation. The experimental side column and design return branch are not active experiments in the digital twin.

## 4. Phase C: fixed-bed breakthrough

For each adsorption medium:

1. Record packed-bed volume, media mass, bulk density, particle size, and empty-bed contact time.
2. Maintain a declared flow and measure actual flow continuously.
3. Sample paired influent and effluent at planned bed-volume intervals.
4. Plot \`Cout/Cin\` against bed volumes.
5. Declare breakthrough and exhaustion criteria before viewing final results.
6. Repeat complete exhaustion runs to quantify between-run variability.
7. Test representative changes in influent concentration and hydraulic loading.

Removal efficiency is reported as:

\`\`\`text
Removal efficiency (%) = ((Cin − Cout) / Cin) × 100
\`\`\`

When \`Cin\` is near the analytical detection limit, removal percentages may be misleading; raw concentrations and method limits must also be reported.

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

Transparent operating and maintenance rules come first. The current public-data anomaly-detection research is described in the [model card](data-and-model-card.md); it is not a trained carbon-life model or field qualification. Predictive media-life analytics are a later study after relevant independent runs exist. A more complex model must be evaluated prospectively on held-out complete exhaustion runs and compared against the rule baseline. Prediction cannot open or override the independent outlet controller.

### Provisional later-study targets — not achieved results

- Warning at least 10 bed volumes before defined breakthrough.
- Remaining-life error no greater than 20% after at least three independent complete exhaustion runs.
- Uncertainty or “insufficient confidence” state shown with the recommendation; independent outlet protection remains authoritative.
- No release decision made by the prediction model alone.

These numbers are draft research targets, not a basis to declare model readiness. Before evaluation, define the warning event, bed-volume origin, remaining-life error formula/denominator, forecast timing, and uncertainty interval. At least three complete runs is a proposed starting minimum, not a claim of statistically sufficient validation. Report actual run counts, variability, uncertainty, and performance against the baseline.

## 7. Phase F: fault injection

Every fault test records event time, controller state, valve response, destination flow, alarm, operator action, and recovery.

Record commanded valve state, independently observed physical position, and measured destination flow as separate observations. A digital state transition or rendered valve animation demonstrates software behaviour only; it does not pass a physical fault test.

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
| Microbial | \`E. coli\` and the selected validation panel |
| Operational | Bed volumes, downtime, backwash frequency, media use, calibration status |
| Resource | Inlet, reuse, reject, backwash, make-up water, energy, consumables |
| Cost | Equipment, installation, media, chemicals, laboratory work, labour, maintenance |

Laboratory methods should follow an accredited or otherwise recognized standard. Raw data, units, detection limits, calibration records, exclusions, and analysis scripts must be retained.

Meter collection, all potable inputs, actual irrigation use, rejection, backwash, overflow, and storage change separately. Report laboratory recovery separately from field water offset. An offset calculation requires equivalent irrigation demand and the original supply source; losses already excluded by the delivered-use meter must not be subtracted twice. Apply the definitions in [impact and economics](impact-and-economics.md). No equipment label or rendered dimensions establish a treatment capacity.

## 9. Results template

No placeholder value should be presented as a result. Each published result includes:

\`\`\`text
Label: RESULT
Protocol identifier and version:
Metric:
Source and test condition:
Sample size:
Method and detection limit:
Influent distribution:
Effluent distribution:
Estimate and uncertainty:
Raw-data path:
Calibration and quality-control record:
Protocol deviation, if any:
\`\`\`

## 10. Pilot gate

Proceed from bench work to a site pilot only when:

- The selected treatment train meets all predeclared bench acceptance criteria.
- The disinfection barrier is validated for the chosen end use.
- The commercial-carbon base train meets predeclared treatment, hydraulics, service-life and maintenance criteria.
- Any later palm-carbon replacement passes its own material-performance, leaching, durability and lifecycle criteria under equivalent conditions; results remain separate from the base train.
- Fail-safe fault tests pass.
- Plumbing and cross-connection controls are reviewed by qualified professionals.
- Required Saudi regulatory and site approvals are identified and obtained.
- A sampling, maintenance, incident, and shutdown plan is approved.

All pilot gates are future requirements. A schedule or successful digital demonstration does not establish that any gate has passed.
`;export{e as default};