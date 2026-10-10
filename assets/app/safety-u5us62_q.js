var e=`# Safety and Risk Controls\r
\r
> **Status:** Preliminary \`DESIGN\` requirements, not tested safety performance or site authorization. Scope follows the [project brief](project-brief.md); outstanding evidence is recorded in the [evidence register](evidence-register.md).\r
\r
## 1. Safety objective\r
\r
MAWRID must prevent human or environmental exposure whenever treatment performance cannot be demonstrated. Safety is established through source control, multiple barriers, validated operating limits, hygienic plumbing, laboratory verification, and a fail-safe release decision.\r
\r
The first proposed application is one separately collected university ablution source serving a controlled zone of ornamental plants with drip irrigation. Exposure routes include maintenance contact, public access, accidental drinking, spray/aerosols, soil, and drainage. The site review must address these before any field irrigation. Drinking, reuse for ablution, edible crops, and mixed wastewater are outside this version.\r
\r
## 2. Release philosophy\r
\r
\`\`\`text\r
Reuse permission =\r
  required site/use authorization in force\r
  AND valid critical sensors\r
  AND valid calibration state\r
  AND treatment flow within validated range\r
  AND filtration integrity within validated range\r
  AND disinfection condition satisfied\r
  AND treated storage available and within validated age/condition limits\r
  AND no active critical fault\r
\`\`\`\r
\r
If any term is false or unknown, reuse permission is false.\r
\r
This is a proposed operating rule, not proof that water is safe. Use-specific laboratory verification and a reviewed commissioning plan remain required. The independent local controller owns outlet protection; the website, remote dashboard, and future AI recommendations cannot authorize or open the outlet. Verify the actual valve position and destination flow under critical faults, communications loss, and loss of power before relying on the design.\r
\r
## 3. Preliminary hazard register\r
\r
| Hazard | Potential consequence | Preventive barrier | Detection | Corrective action |\r
|---|---|---|---|---|\r
| Toilet, kitchen, or chemical stream connected | Treatment overload or hazardous exposure | Dedicated plumbing and fixture survey | Source checks, conductivity/pH anomaly, inspection | Isolate source, divert, investigate |\r
| High suspended-solids load | Filter failure and poor disinfection | Screening and equalization | Turbidity and pressure trend | Stop release, clean/backwash |\r
| Pathogen survival | User or maintenance-worker exposure | Validated disinfection | Process-condition monitoring plus microbiology | Divert, disinfect, investigate |\r
| Adsorption breakthrough | Target dissolved constituent reaches outlet | Defined media capacity and replacement logic | Paired analysis and validated surrogate | Divert or bypass reuse; replace media |\r
| Biochar leaching or fines | Water-quality deterioration | Media characterization, washing, retention screen | Turbidity, pH, laboratory analysis | Reject batch, flush, replace |\r
| Stagnation and regrowth | Microbial deterioration in storage | Residence-time control and hygienic tank design | Level/age tracking, residual and microbiology | Divert, clean, disinfect |\r
| Cross-connection with potable water | Public-health exposure | Air gap/backflow protection and labeled pipework | Commissioning and periodic cross-connection tests | Immediate shutdown and incident response |\r
| Sensor drift or fouling | False release decision | Calibration and cleaning program | Plausibility checks and reference measurements | Mark invalid, close reuse valve |\r
| Valve or power failure | Unsuitable water reaches reuse network | Normally closed or fail-to-divert design | Position feedback and flow verification | Isolate mechanically and repair |\r
| Exhausted biochar mishandling | Worker or environmental exposure | Characterization and handling procedure | Waste classification records | Regenerate or dispose through approved route |\r
| Backwash discharged incorrectly | Pollution or plumbing incident | Approved drain/containment connection | Flow and inspection | Stop cycle and contain |\r
| Public access, aerosol exposure, or unsuitable irrigation use | Human exposure outside the evaluated use | Controlled ornamental zone, drip configuration, labeling and access management | Site inspection and use review | Stop irrigation, isolate the area, investigate |\r
| Salinity, target chemicals, or disinfectant incompatible with plants/soil | Plant injury or soil/drainage impact | Source/use-specific chemical review and limits | Laboratory analysis and site observations | Stop or divert; review treatment and use |\r
\r
This register is preliminary. A multidisciplinary site hazard assessment must update likelihood, severity, ownership, and verification for the selected installation.\r
\r
## 4. Critical control concepts\r
\r
### Source acceptance\r
\r
- Only the mapped university ablution source may connect in the first version.\r
- Handwashing fixtures or any other added source require separate characterization, risk review, and a scope update before connection.\r
- Floor drains and cleaning-chemical discharges require explicit review.\r
- Abnormal source-water indicators trigger diversion and investigation.\r
\r
### Disinfection\r
\r
- The validated process condition must be met during every release period.\r
- A disinfectant dose setting is not proof that the required residual or dose reached the water.\r
- Microbiological testing verifies performance at a declared frequency.\r
\r
### Sensor integrity\r
\r
- Critical sensors carry calibration due dates and acceptable ranges.\r
- Missing, stale, implausible, or conflicting values are invalid, not normal.\r
- Maintenance mode physically or logically locks the reuse valve closed.\r
\r
### Hydraulic integrity\r
\r
- Potable make-up uses approved backflow protection or an air gap.\r
- Reuse pipework and outlets are permanently identified as non-potable.\r
- Critical fault testing verifies commanded valve state, independently observed physical position, and measured destination flow; a software flag alone is insufficient evidence.\r
- Tank overflows and drains terminate at approved destinations.\r
\r
## 5. Water not released for reuse\r
\r
Water is held, reprocessed, contained, or sent to an approved sewer when:\r
\r
- Startup flushing is incomplete.\r
- A critical parameter is outside its validated operating envelope.\r
- Required disinfection conditions are not demonstrated.\r
- A critical sensor or actuator has failed.\r
- Data are stale or internally inconsistent.\r
- Calibration has expired.\r
- Cross-connection status is uncertain.\r
- The system is in backwash, maintenance, or fault state.\r
- The treated water has exceeded its validated storage time.\r
\r
## 6. Laboratory verification\r
\r
Operational sensors are supplemented by paired influent and effluent analyses. The panel and frequency depend on the end use and risk assessment. Microbial results, selected dissolved constituents, solids, organics, salinity, and disinfection by-products may be required.\r
\r
An accredited laboratory or recognized method should be used for decisions affecting public health or regulatory compliance.\r
\r
No sensor reading, \`REUSE_READY\` display, clear-looking water, or simulated laboratory comparison certifies the intended use. Adsorption/biochar is optional and requires a selected constituent, leaching assessment, and defined acceptance criteria when included; it is not a disinfection barrier.\r
\r
## 7. Residuals and end of life\r
\r
Treatment transfers some contamination into screenings, backwash water, tank sediment, and spent media. It does not make these residuals disappear.\r
\r
- Screenings are handled hygienically and disposed through an approved route.\r
- Backwash and cleaning water return to an approved sewer or treatment route.\r
- Spent biochar is characterized before regeneration, reuse, or disposal.\r
- Spent biochar is not applied to soil by default.\r
- Chemical regeneration, if tested, includes management of the concentrated regenerant stream.\r
\r
## 8. Regulatory pathway\r
\r
Saudi Water Law encourages greywater reuse subject to ministry rules. Installation still requires confirmation of current requirements for source water, intended use, water quality, plumbing, building code, environmental discharge, worker safety, and public health.\r
\r
International documents such as WHO guidance, EPA risk-based frameworks, ISO standards, and NSF/ANSI 350 are useful design benchmarks. They do not themselves authorize a Saudi installation or certify MAWRID.\r
\r
## 9. Incident response\r
\r
No partner, required permission, or approved pilot is currently documented. Before a physical pilot, its plan must define:\r
\r
- Automatic isolation and alarm behaviour.\r
- Manual emergency stop and lockout.\r
- Sampling after a critical event.\r
- Tank and pipework cleaning/disinfection.\r
- Notification responsibilities.\r
- Root-cause analysis and authorization to restart.\r
- Retention of sensor, valve, maintenance, and laboratory records.\r
`;export{e as default};