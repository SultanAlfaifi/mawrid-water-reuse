var e=`# Development Roadmap

MAWRID advances through evidence gates rather than calendar promises.

The current Rabigh proposal targets a bench prototype at the Energy and Water Academy in Rabigh, subject to documented permission and available resources. The team reports interest; there is no published interest letter or site agreement. The first commercial segment is Haramain facilities and large complexes, followed by universities, airports and other qualified sites. Each pilot still uses one characterized source and a defined irrigation demand. A public digital demonstration does not establish completed hardware, treatment performance, or permission to irrigate.

## Rabigh six-week execution proposal

The [Arabic Rabigh plan](rabigh-plan.md) records the named owners and test targets from the team's final deck. **SAR 9,500** is a planning budget for the first prototype, not an approved purchase or product price. The week allocation below is a proposed schedule, conditional on parts, site permission and laboratory availability.

| Window | Owner | Evidence to produce |
|---|---|---|
| Weeks 1–2 | Faisal Alhilali, with Abdulsalam Alotaibi | Assemble the loop, map drainage and calibrate sensors against references |
| Weeks 2–3 | Sultan Alfaifi and Faisal Alhilali | Connect controller, actual valve feedback, flow and local logs |
| Weeks 3–5 | Abdulsalam Alotaibi, supported by the team | Planned challenge and disconnection tests, seven-day run and three laboratory samples under a frozen protocol |
| Week 6 | Full team | Acceptance or failure report, water/cost reconciliation and a decision on further testing |

The subsequent customer trial is proposed for 60–90 days with agreed criteria. Neither schedule proves treatment safety or completes field validation. Product and maintenance prices remain unpublished pending scope decisions.

## Stage 0 — Definition

**Objective:** Freeze the first source, end use, risk boundary, and testable claims.

**Deliverables:**

- Fixture and source map.
- Intended-use statement and exclusions.
- Regulatory requirements register.
- Preliminary hazard analysis.
- Sampling and experimental protocol.
- Prior-art search strategy.

**Gate:** A qualified team agrees that the use case can be tested safely and legally.

## Stage 1 — Source characterization

**Objective:** Quantify variability in source-separated ablution water at the selected approved facility. Additional handwashing inputs require a separate source review before inclusion.

**Deliverables:**

- Time-resolved flow profile.
- Physical, chemical, and microbial dataset.
- Storage and source-anomaly observations.
- A justified decision on whether adsorption is needed; select one target constituent and method if it is.

**Gate:** The treatment challenge and analytical methods are sufficiently defined.

## Stage 2 — Bench media study

**Objective:** Validate the simpler treatment candidate first. If adsorption is justified, compare date-palm biochar preparation candidates, commercial activated carbon, and controls for the selected constituent.

**Deliverables:**

- Reproducible media preparation record.
- Leaching and fines assessment.
- Hydraulic performance.
- Breakthrough curves and capacity estimates.
- Preliminary lifecycle and cost inventory.

**Gate:** The simpler train can advance if it meets the defined source/use criteria without adsorption. If adsorption is needed, the selected medium must add useful performance without unacceptable leaching, cost, or hydraulic behaviour; biochar is omitted if it adds no justified value.

## Stage 3 — Integrated prototype

**Objective:** Operate the complete treatment and control train at bench scale.

**Deliverables:**

- Instrumented hardware prototype.
- Controller state machine and event logging.
- Water-balance reconciliation.
- Validated disinfection study.
- Fault-injection results.
- Maintenance procedures.

**Gate:** Every critical fail-safe test passes and the treatment candidate meets predeclared bench targets.

## Stage 4 — Monitored site pilot

**Objective:** Test representative operation at one approved facility for the selected irrigation use.

**Scale:** Not selected. Size the proposed pilot from measured source availability, irrigation demand, storage limits, and tested process conditions. \`M5\` or an illustrative 3D unit is not evidence of capacity or a commitment to \`5 m³/day\`.

**Deliverables:**

- Required site and regulatory approvals.
- Commissioning and cross-connection test records.
- Seasonal treatment and reliability data.
- Net water offset, energy, consumables, residuals, and cost.
- User and operator feedback.
- Incident and maintenance log.

**Gate:** The pilot demonstrates safe, stable, maintainable, and economically credible operation for the selected use.

## Stage 5 — Prediction and optimization

**Objective:** Determine whether condition data can forecast media breakthrough better than simple rules.

**Deliverables:**

- Multiple independent complete media-life datasets.
- Transparent baseline model.
- Prospective prediction evaluation with uncertainty.
- Optimized contact time, backwash, disinfection, and replacement logic.

**Gate:** The predictive approach improves operational decisions without weakening safety.

## Stage 6 — Product and certification pathway

**Objective:** Convert the validated pilot architecture into a repeatable product.

**Deliverables:**

- Design-for-manufacture package.
- Quality and media-batch controls.
- Applicable Saudi approvals and certification plan.
- Service, residuals, cybersecurity, and data-governance plans.
- Third-party performance testing.
- Commercial pilot and customer economics.

## Evidence maturity

| Claim | Now | Bench | Pilot | Product stage |
|---|---|---|---|---|
| Relevant Saudi water-efficiency problem | Literature-backed | — | Site quantified | Portfolio quantified |
| Date-palm biochar adsorption | Literature-backed, MAWRID untested | Measured | Field verified | Batch quality controlled |
| Safe water for selected use | Not demonstrated | Challenge tested | Site validated and approved | Third-party verified as required |
| Breakthrough prediction | Hypothesis | Retrospective exploration | Prospective evaluation | Monitored model lifecycle |
| Lower lifecycle cost | Hypothesis | Preliminary estimate | Site cost measured | Commercially benchmarked |
| Scalable impact | Concept | Engineering model | One-site evidence | Multi-site evidence |

## Near-term hackathon deliverables

- A bench-scale hydraulic prototype or an explicitly labeled digital simulation; record which is actually available.
- A dashboard using clearly marked simulated data until real sensors are connected.
- Software state-transition tests, with physical valve and destination-flow evidence only when hardware has been tested.
- Media-test protocol and sample data schema.
- Physical or rendered cartridge design.
- Three-minute system demonstration focused on source, barriers, decision, and safe diversion.
- Explicit next experiment and evidence gap.

The onsite template's six-week grid can be used as a proposed planning window: define the selected source and irrigation demand; assemble the bench loop and data record; test the controller and valve; perform available laboratory media comparisons; reconcile water and cost; then repeat unresolved tests and package the evidence. This is a target for a testable prototype, subject to component and laboratory availability. It is not a promise of field validation, certification, or a trained predictive model within six weeks.

Report maturity using the template's idea, design, prototype, experiment, and initial-results categories, supported by the delivered artifact. Any TRL estimate is a stated self-assessment; a target level must not be reported as achieved. Completion percentages require a declared task list and calculation method.
`;export{e as default};