var e=`# Development Roadmap\r
\r
MAWRID advances through evidence gates rather than calendar promises.\r
\r
The first proposed use case is one university facility: source-separated ablution drainage feeding treatment for irrigation of a defined green area. A public digital demonstration illustrates this architecture and its control rules. It does not establish a site agreement, completed hardware, treatment performance, or permission to irrigate.\r
\r
## Stage 0 — Definition\r
\r
**Objective:** Freeze the first source, end use, risk boundary, and testable claims.\r
\r
**Deliverables:**\r
\r
- Fixture and source map.\r
- Intended-use statement and exclusions.\r
- Regulatory requirements register.\r
- Preliminary hazard analysis.\r
- Sampling and experimental protocol.\r
- Prior-art search strategy.\r
\r
**Gate:** A qualified team agrees that the use case can be tested safely and legally.\r
\r
## Stage 1 — Source characterization\r
\r
**Objective:** Quantify variability in source-separated ablution water at the selected university facility. Additional handwashing inputs require a separate source review before inclusion.\r
\r
**Deliverables:**\r
\r
- Time-resolved flow profile.\r
- Physical, chemical, and microbial dataset.\r
- Storage and source-anomaly observations.\r
- A justified decision on whether adsorption is needed; select one target constituent and method if it is.\r
\r
**Gate:** The treatment challenge and analytical methods are sufficiently defined.\r
\r
## Stage 2 — Bench media study\r
\r
**Objective:** Validate the simpler treatment candidate first. If adsorption is justified, compare date-palm biochar preparation candidates, commercial activated carbon, and controls for the selected constituent.\r
\r
**Deliverables:**\r
\r
- Reproducible media preparation record.\r
- Leaching and fines assessment.\r
- Hydraulic performance.\r
- Breakthrough curves and capacity estimates.\r
- Preliminary lifecycle and cost inventory.\r
\r
**Gate:** The simpler train can advance if it meets the defined source/use criteria without adsorption. If adsorption is needed, the selected medium must add useful performance without unacceptable leaching, cost, or hydraulic behaviour; biochar is omitted if it adds no justified value.\r
\r
## Stage 3 — Integrated prototype\r
\r
**Objective:** Operate the complete treatment and control train at bench scale.\r
\r
**Deliverables:**\r
\r
- Instrumented hardware prototype.\r
- Controller state machine and event logging.\r
- Water-balance reconciliation.\r
- Validated disinfection study.\r
- Fault-injection results.\r
- Maintenance procedures.\r
\r
**Gate:** Every critical fail-safe test passes and the treatment candidate meets predeclared bench targets.\r
\r
## Stage 4 — Monitored site pilot\r
\r
**Objective:** Test representative operation at one approved university facility for the selected irrigation use.\r
\r
**Scale:** Not selected. Size the proposed pilot from measured source availability, irrigation demand, storage limits, and tested process conditions. \`M5\` or an illustrative 3D unit is not evidence of capacity or a commitment to \`5 m³/day\`.\r
\r
**Deliverables:**\r
\r
- Required site and regulatory approvals.\r
- Commissioning and cross-connection test records.\r
- Seasonal treatment and reliability data.\r
- Net water offset, energy, consumables, residuals, and cost.\r
- User and operator feedback.\r
- Incident and maintenance log.\r
\r
**Gate:** The pilot demonstrates safe, stable, maintainable, and economically credible operation for the selected use.\r
\r
## Stage 5 — Prediction and optimization\r
\r
**Objective:** Determine whether condition data can forecast media breakthrough better than simple rules.\r
\r
**Deliverables:**\r
\r
- Multiple independent complete media-life datasets.\r
- Transparent baseline model.\r
- Prospective prediction evaluation with uncertainty.\r
- Optimized contact time, backwash, disinfection, and replacement logic.\r
\r
**Gate:** The predictive approach improves operational decisions without weakening safety.\r
\r
## Stage 6 — Product and certification pathway\r
\r
**Objective:** Convert the validated pilot architecture into a repeatable product.\r
\r
**Deliverables:**\r
\r
- Design-for-manufacture package.\r
- Quality and media-batch controls.\r
- Applicable Saudi approvals and certification plan.\r
- Service, residuals, cybersecurity, and data-governance plans.\r
- Third-party performance testing.\r
- Commercial pilot and customer economics.\r
\r
## Evidence maturity\r
\r
| Claim | Now | Bench | Pilot | Product stage |\r
|---|---|---|---|---|\r
| Relevant Saudi water-efficiency problem | Literature-backed | — | Site quantified | Portfolio quantified |\r
| Date-palm biochar adsorption | Literature-backed, MAWRID untested | Measured | Field verified | Batch quality controlled |\r
| Safe water for selected use | Not demonstrated | Challenge tested | Site validated and approved | Third-party verified as required |\r
| Breakthrough prediction | Hypothesis | Retrospective exploration | Prospective evaluation | Monitored model lifecycle |\r
| Lower lifecycle cost | Hypothesis | Preliminary estimate | Site cost measured | Commercially benchmarked |\r
| Scalable impact | Concept | Engineering model | One-site evidence | Multi-site evidence |\r
\r
## Near-term hackathon deliverables\r
\r
- A bench-scale hydraulic prototype or an explicitly labeled digital simulation; record which is actually available.\r
- A dashboard using clearly marked simulated data until real sensors are connected.\r
- Software state-transition tests, with physical valve and destination-flow evidence only when hardware has been tested.\r
- Media-test protocol and sample data schema.\r
- Physical or rendered cartridge design.\r
- Three-minute system demonstration focused on source, barriers, decision, and safe diversion.\r
- Explicit next experiment and evidence gap.\r
\r
The onsite template's six-week grid can be used as a proposed planning window: define the university source and irrigation demand; assemble the bench loop and data record; test the controller and valve; perform available laboratory media comparisons; reconcile water and cost; then repeat unresolved tests and package the evidence. This is a target for a testable prototype, subject to component and laboratory availability. It is not a promise of field validation, certification, or a trained predictive model within six weeks.\r
\r
Report maturity using the template's idea, design, prototype, experiment, and initial-results categories, supported by the delivered artifact. Any TRL estimate is a stated self-assessment; a target level must not be reported as achieved. Completion percentages require a declared task list and calculation method.\r
`;export{e as default};