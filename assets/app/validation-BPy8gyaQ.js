var e=`# Experimental Validation\r
\r
> **Purpose:** Generate reproducible evidence for treatment performance, media life, safe control, and pilot feasibility.\r
\r
> **Status:** \`DESIGN\` / \`TARGET\` validation plan. This is not a completed experimental protocol or a results report. There are no documented MAWRID water-treatment results, confirmed university partner, laboratory commitment, or field-use approval. Scope and evidence labels follow the [project brief](project-brief.md) and [evidence register](evidence-register.md).\r
\r
The first source is one separately collected university ablution drain. The proposed use is a controlled ornamental-plant zone with drip irrigation, after source/use risk review and required approvals. No field irrigation is part of the initial bench study.\r
\r
## 1. Experimental questions\r
\r
1. How variable is the selected source water over users, peak periods, cleaning events, and storage times?\r
2. What does each treatment barrier contribute?\r
3. Is adsorption needed for a selected dissolved constituent? If so, does date-palm biochar add value against the simpler train and commercial activated carbon?\r
4. How many bed volumes are treated before defined breakthrough?\r
5. Can online measurements provide useful advance warning of that breakthrough?\r
6. Does disinfection achieve the selected microbial target under representative worst-case conditions?\r
7. Does the system divert water reliably during sensor, process, communication, and power faults?\r
8. What are measured recovery, irrigation water actually used, source-specific offset against equivalent demand, energy, consumables, residuals, and cost per cubic metre?\r
\r
### Before a test can produce a reported result\r
\r
Freeze a protocol identifier/version, source and intended-use boundaries, target constituent and analytical method, sampling locations and timing, media recipe/batch, hydraulic loading/contact conditions, storage intervals, independent-run and replicate counts, quality controls, uncertainty method, exclusions, and pass/fail criteria. For microbial work, specify the challenge organism or accepted surrogate, method, detection limit, contact conditions, and use-specific target. Record which inputs remain unresolved; do not fill them with demonstration values.\r
\r
Tests require appropriate facilities, trained staff, and permission for the activity. Evidence from a simulation, a laboratory material test, a controller bench test, and a monitored irrigation pilot is reported separately.\r
\r
## 2. Phase A: source characterization\r
\r
Collect time-stamped samples from the proposed pilot source across:\r
\r
- Low, normal, and peak use.\r
- Different days and cleaning schedules.\r
- Ablution-source variation and documented cleaning/contamination events; unsuitable streams remain excluded.\r
- Immediate testing and defined storage intervals.\r
\r
Record fixture connections, weather where relevant, flow, temperature, sampling method, holding time, and analytical method.\r
\r
Measure irrigation demand and its existing supply source over comparable periods. Additional handwashing connections require a separate source characterization, risk review, and update to the project brief before inclusion; they are outside the first-version test matrix.\r
\r
## 3. Phase B: media screening\r
\r
### Test matrix\r
\r
Characterization first determines whether an adsorption study is needed. If it is not, compare and validate the simpler treatment train without claiming a biochar benefit. The following matrix is a candidate material study, not a requirement to build every variant or evidence that any has been tested.\r
\r
| ID | Treatment | Purpose |\r
|---|---|---|\r
| A | Untreated source water | Influent baseline |\r
| B | Sand or multimedia only | Particulate-removal control |\r
| C | Raw date-palm biochar only | Adsorption and leaching screen |\r
| D | Sand + raw date-palm biochar | Combined untreated-media train |\r
| E | Sand + activated date-palm biochar | Candidate optimized train |\r
| F | Sand + commercial activated carbon | Industry benchmark |\r
| G | Full train + disinfection | End-to-end validation candidate |\r
\r
At least one blank and a no-biochar control are required. Replicate counts and sample size will be declared before testing.\r
\r
## 4. Phase C: fixed-bed breakthrough\r
\r
For each adsorption medium:\r
\r
1. Record packed-bed volume, media mass, bulk density, particle size, and empty-bed contact time.\r
2. Maintain a declared flow and measure actual flow continuously.\r
3. Sample paired influent and effluent at planned bed-volume intervals.\r
4. Plot \`Cout/Cin\` against bed volumes.\r
5. Declare breakthrough and exhaustion criteria before viewing final results.\r
6. Repeat complete exhaustion runs to quantify between-run variability.\r
7. Test representative changes in influent concentration and hydraulic loading.\r
\r
Removal efficiency is reported as:\r
\r
\`\`\`text\r
Removal efficiency (%) = ((Cin − Cout) / Cin) × 100\r
\`\`\`\r
\r
When \`Cin\` is near the analytical detection limit, removal percentages may be misleading; raw concentrations and method limits must also be reported.\r
\r
## 5. Phase D: disinfection validation\r
\r
The disinfection study defines:\r
\r
- Challenge organism or accepted surrogate.\r
- Influent concentration range.\r
- Worst-case turbidity, pH, temperature, and disinfectant demand.\r
- Dose or intensity and effective contact time.\r
- Sampling and neutralization procedure.\r
- Reference analytical method.\r
- Required log reduction and release conditions.\r
- Storage and regrowth observations.\r
\r
Disinfection performance is never inferred from water clarity alone.\r
\r
## 6. Phase E: monitoring model\r
\r
Candidate inputs include:\r
\r
- Inlet and outlet turbidity.\r
- Flow and cumulative treated volume.\r
- Bed volumes.\r
- Differential pressure.\r
- pH, temperature, and conductivity.\r
- Optional UV254 across the adsorption bed.\r
- Media batch and preparation conditions.\r
- Laboratory target-constituent measurements.\r
\r
Transparent operating and maintenance rules come first. Predictive analytics are a later study after relevant independent runs exist. A more complex model must be evaluated prospectively on held-out complete exhaustion runs and compared against the rule baseline. Prediction cannot open or override the independent outlet controller.\r
\r
### Provisional later-study targets — not achieved results\r
\r
- Warning at least 10 bed volumes before defined breakthrough.\r
- Remaining-life error no greater than 20% after at least three independent complete exhaustion runs.\r
- Uncertainty or “insufficient confidence” state shown with the recommendation; independent outlet protection remains authoritative.\r
- No release decision made by the prediction model alone.\r
\r
These numbers are draft research targets, not a basis to declare model readiness. Before evaluation, define the warning event, bed-volume origin, remaining-life error formula/denominator, forecast timing, and uncertainty interval. At least three complete runs is a proposed starting minimum, not a claim of statistically sufficient validation. Report actual run counts, variability, uncertainty, and performance against the baseline.\r
\r
## 7. Phase F: fault injection\r
\r
Every fault test records event time, controller state, valve response, destination flow, alarm, operator action, and recovery.\r
\r
Record commanded valve state, independently observed physical position, and measured destination flow as separate observations. A digital state transition or rendered valve animation demonstrates software behaviour only; it does not pass a physical fault test.\r
\r
| Fault | Expected response |\r
|---|---|\r
| High outlet turbidity | Reuse valve closes; water diverts |\r
| Disinfectant condition below limit | Reuse valve closes; water diverts |\r
| Critical sensor disconnected | Invalid-data state; reuse valve closes |\r
| Implausible or frozen sensor value | Plausibility failure; reuse valve closes |\r
| Controller communication loss | Local fail-safe state; reuse valve closes |\r
| Power interruption | De-energized valve moves to non-reuse position |\r
| Treated tank high level | Stop or divert without uncontrolled overflow |\r
| Raw tank low level | Pump stops to prevent dry running |\r
\r
## 8. Measurements\r
\r
| Category | Core measurements |\r
|---|---|\r
| Physical | Flow, temperature, turbidity, total suspended solids, pressure drop |\r
| Chemical | pH, conductivity, COD, selected dissolved-organic indicator, disinfectant condition |\r
| Microbial | \`E. coli\` and the selected validation panel |\r
| Operational | Bed volumes, downtime, backwash frequency, media use, calibration status |\r
| Resource | Inlet, reuse, reject, backwash, make-up water, energy, consumables |\r
| Cost | Equipment, installation, media, chemicals, laboratory work, labour, maintenance |\r
\r
Laboratory methods should follow an accredited or otherwise recognized standard. Raw data, units, detection limits, calibration records, exclusions, and analysis scripts must be retained.\r
\r
Meter collection, all potable inputs, actual irrigation use, rejection, backwash, overflow, and storage change separately. Report laboratory recovery separately from field water offset. An offset calculation requires equivalent irrigation demand and the original supply source; losses already excluded by the delivered-use meter must not be subtracted twice. Apply the definitions in [impact and economics](impact-and-economics.md). No equipment label or rendered dimensions establish a treatment capacity.\r
\r
## 9. Results template\r
\r
No placeholder value should be presented as a result. Each published result includes:\r
\r
\`\`\`text\r
Label: RESULT\r
Protocol identifier and version:\r
Metric:\r
Source and test condition:\r
Sample size:\r
Method and detection limit:\r
Influent distribution:\r
Effluent distribution:\r
Estimate and uncertainty:\r
Raw-data path:\r
Calibration and quality-control record:\r
Protocol deviation, if any:\r
\`\`\`\r
\r
## 10. Pilot gate\r
\r
Proceed from bench work to a site pilot only when:\r
\r
- The selected treatment train meets all predeclared bench acceptance criteria.\r
- The disinfection barrier is validated for the chosen end use.\r
- If biochar is included, its leaching and residuals risks are characterized.\r
- If adsorption is omitted, the validated simpler train still meets the defined source/use criteria; no biochar performance claim is made.\r
- Fail-safe fault tests pass.\r
- Plumbing and cross-connection controls are reviewed by qualified professionals.\r
- Required Saudi regulatory and site approvals are identified and obtained.\r
- A sampling, maintenance, incident, and shutdown plan is approved.\r
\r
All pilot gates are future requirements. A schedule or successful digital demonstration does not establish that any gate has passed.\r
`;export{e as default};