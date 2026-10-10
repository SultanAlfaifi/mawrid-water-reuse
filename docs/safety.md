# Safety and Risk Controls

> **Status:** Preliminary `DESIGN` requirements, not tested safety performance or site authorization. Scope follows the [project brief](project-brief.md); outstanding evidence is recorded in the [evidence register](evidence-register.md).

## 1. Safety objective

MAWRID must prevent human or environmental exposure whenever treatment performance cannot be demonstrated. Safety is established through source control, multiple barriers, validated operating limits, hygienic plumbing, laboratory verification, and a fail-safe release decision.

The first proposed application is one separately collected university ablution source serving a controlled zone of ornamental plants with drip irrigation. Exposure routes include maintenance contact, public access, accidental drinking, spray/aerosols, soil, and drainage. The site review must address these before any field irrigation. Drinking, reuse for ablution, edible crops, and mixed wastewater are outside this version.

## 2. Release philosophy

```text
Reuse permission =
  required site/use authorization in force
  AND valid critical sensors
  AND valid calibration state
  AND treatment flow within validated range
  AND filtration integrity within validated range
  AND disinfection condition satisfied
  AND treated storage available and within validated age/condition limits
  AND no active critical fault
```

If any term is false or unknown, reuse permission is false.

This is a proposed operating rule, not proof that water is safe. Use-specific laboratory verification and a reviewed commissioning plan remain required. The independent local controller owns outlet protection; the website, remote dashboard, and future AI recommendations cannot authorize or open the outlet. Verify the actual valve position and destination flow under critical faults, communications loss, and loss of power before relying on the design.

## 3. Preliminary hazard register

| Hazard | Potential consequence | Preventive barrier | Detection | Corrective action |
|---|---|---|---|---|
| Toilet, kitchen, or chemical stream connected | Treatment overload or hazardous exposure | Dedicated plumbing and fixture survey | Source checks, conductivity/pH anomaly, inspection | Isolate source, divert, investigate |
| High suspended-solids load | Filter failure and poor disinfection | Screening and equalization | Turbidity and pressure trend | Stop release, clean/backwash |
| Pathogen survival | User or maintenance-worker exposure | Validated disinfection | Process-condition monitoring plus microbiology | Divert, disinfect, investigate |
| Adsorption breakthrough | Target dissolved constituent reaches outlet | Defined media capacity and replacement logic | Paired analysis and validated surrogate | Divert or bypass reuse; replace media |
| Biochar leaching or fines | Water-quality deterioration | Media characterization, washing, retention screen | Turbidity, pH, laboratory analysis | Reject batch, flush, replace |
| Stagnation and regrowth | Microbial deterioration in storage | Residence-time control and hygienic tank design | Level/age tracking, residual and microbiology | Divert, clean, disinfect |
| Cross-connection with potable water | Public-health exposure | Air gap/backflow protection and labeled pipework | Commissioning and periodic cross-connection tests | Immediate shutdown and incident response |
| Sensor drift or fouling | False release decision | Calibration and cleaning program | Plausibility checks and reference measurements | Mark invalid, close reuse valve |
| Valve or power failure | Unsuitable water reaches reuse network | Normally closed or fail-to-divert design | Position feedback and flow verification | Isolate mechanically and repair |
| Exhausted biochar mishandling | Worker or environmental exposure | Characterization and handling procedure | Waste classification records | Regenerate or dispose through approved route |
| Backwash discharged incorrectly | Pollution or plumbing incident | Approved drain/containment connection | Flow and inspection | Stop cycle and contain |
| Public access, aerosol exposure, or unsuitable irrigation use | Human exposure outside the evaluated use | Controlled ornamental zone, drip configuration, labeling and access management | Site inspection and use review | Stop irrigation, isolate the area, investigate |
| Salinity, target chemicals, or disinfectant incompatible with plants/soil | Plant injury or soil/drainage impact | Source/use-specific chemical review and limits | Laboratory analysis and site observations | Stop or divert; review treatment and use |

This register is preliminary. A multidisciplinary site hazard assessment must update likelihood, severity, ownership, and verification for the selected installation.

## 4. Critical control concepts

### Source acceptance

- Only the mapped university ablution source may connect in the first version.
- Handwashing fixtures or any other added source require separate characterization, risk review, and a scope update before connection.
- Floor drains and cleaning-chemical discharges require explicit review.
- Abnormal source-water indicators trigger diversion and investigation.

### Disinfection

- The validated process condition must be met during every release period.
- A disinfectant dose setting is not proof that the required residual or dose reached the water.
- Microbiological testing verifies performance at a declared frequency.

### Sensor integrity

- Critical sensors carry calibration due dates and acceptable ranges.
- Missing, stale, implausible, or conflicting values are invalid, not normal.
- Maintenance mode physically or logically locks the reuse valve closed.

### Hydraulic integrity

- Potable make-up uses approved backflow protection or an air gap.
- Reuse pipework and outlets are permanently identified as non-potable.
- Critical fault testing verifies commanded valve state, independently observed physical position, and measured destination flow; a software flag alone is insufficient evidence.
- Tank overflows and drains terminate at approved destinations.

## 5. Water not released for reuse

Water is held, reprocessed, contained, or sent to an approved sewer when:

- Startup flushing is incomplete.
- A critical parameter is outside its validated operating envelope.
- Required disinfection conditions are not demonstrated.
- A critical sensor or actuator has failed.
- Data are stale or internally inconsistent.
- Calibration has expired.
- Cross-connection status is uncertain.
- The system is in backwash, maintenance, or fault state.
- The treated water has exceeded its validated storage time.

## 6. Laboratory verification

Operational sensors are supplemented by paired influent and effluent analyses. The panel and frequency depend on the end use and risk assessment. Microbial results, selected dissolved constituents, solids, organics, salinity, and disinfection by-products may be required.

An accredited laboratory or recognized method should be used for decisions affecting public health or regulatory compliance.

No sensor reading, `REUSE_READY` display, clear-looking water, or simulated laboratory comparison certifies the intended use. Adsorption/biochar is optional and requires a selected constituent, leaching assessment, and defined acceptance criteria when included; it is not a disinfection barrier.

## 7. Residuals and end of life

Treatment transfers some contamination into screenings, backwash water, tank sediment, and spent media. It does not make these residuals disappear.

- Screenings are handled hygienically and disposed through an approved route.
- Backwash and cleaning water return to an approved sewer or treatment route.
- Spent biochar is characterized before regeneration, reuse, or disposal.
- Spent biochar is not applied to soil by default.
- Chemical regeneration, if tested, includes management of the concentrated regenerant stream.

## 8. Regulatory pathway

Saudi Water Law encourages greywater reuse subject to ministry rules. Installation still requires confirmation of current requirements for source water, intended use, water quality, plumbing, building code, environmental discharge, worker safety, and public health.

International documents such as WHO guidance, EPA risk-based frameworks, ISO standards, and NSF/ANSI 350 are useful design benchmarks. They do not themselves authorize a Saudi installation or certify MAWRID.

## 9. Incident response

No partner, required permission, or approved pilot is currently documented. Before a physical pilot, its plan must define:

- Automatic isolation and alarm behaviour.
- Manual emergency stop and lockout.
- Sampling after a critical event.
- Tank and pipework cleaning/disinfection.
- Notification responsibilities.
- Root-cause analysis and authorization to restart.
- Retention of sensor, valve, maintenance, and laboratory records.
