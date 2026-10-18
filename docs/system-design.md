# System Design · تصميم النظام

> **Status:** `DESIGN` architecture and `SIMULATED` software implementation. No physical treatment result, tested physical outlet protection, site approval or confirmed partnership is established. See the [current project brief](project-brief.md) and [evidence register](evidence-register.md).

## 1. Scope and products

MAWRID targets separately collected ablution and washbasin water for defined non-potable landscape irrigation. Toilets, kitchens and mixed sewage are excluded; the connected fixtures, cleaning chemicals, source variability and intended exposure must be characterized before design approval.

The full unit combines treatment and monitoring. The retrofit **MAWRID Box** proposes monitoring and controls for an existing plant, subject to a compatibility survey. Neither a software demonstration nor a diagram establishes installed hardware. Academic facilities are a candidate customer segment; no particular university or site is a confirmed partner.

## 2. Current design basis

The current implementation follows the later station reference, summarized without redistributing the private attachment or supplier offer. It supersedes earlier planning examples of 20 m³/day, fixed 80% recovery and required date-palm carbon in the base train.

| Item | Declared design basis |
|---|---|
| Feed | 1,000 L/hour; 15 m³/day assumes 15 operating hours |
| Raw tank T-101 | 5,000 L, buried GRP design; installation and flotation checks remain |
| Product tank T-102 | 5,000 L, horizontal above-ground polyethylene |
| Base adsorption medium | Commercial activated carbon |
| Date-palm carbon | Future experimental replacement/side-column study after comparative qualification |
| Dosing | Four distinct points: pre-chlorination, SMBS, odor/pH treatment, final chlorination |
| UV | Optional additional barrier position; performance is not calculated in the twin |
| Backwash | Approximate design reference 65 L/min; actual pump curve, head, filter and stock constraints require verification |
| Normal reject | No RO process or fixed 20% continuous reject assumption |

These are sizing assumptions, not verified throughput, irrigation output, chemical doses, regulatory limits or supplier guarantees. The local twin has no automatic 15-hour daily scheduler.

## 3. Water and signal paths

```text
Separated source
  → inlet screen and diversion provision
  → raw tank / feed pump / flow and pressure monitoring
  → pre-chlorination DP-101
  → multimedia filter F-101
  → SMBS dosing DP-102 / ORP monitoring
  → commercial-carbon filter F-102
  → fine cartridge filter CF-101
  → compatible odor treatment or pH correction DP-103
  → final chlorination DP-104
  → operational-quality checks / non-reuse decision
  → optional UV position
  → product tank
  → metered irrigation
```

Backwash, overflow, inlet diversion and the designed return-to-raw branch need explicit destinations and hydraulic design. They are not extra irrigation output. The current twin calculates zero recirculation on the design return branch and does not model the experimental side column. Containment and shutdown must not be described as a functioning return flow where none is calculated.

The inlet, treatment and product states are different observations. A tank level does not establish quality; an outlet command does not establish physical valve position or destination flow. Missing critical measurements remain unknown.

## 4. Control authority

| Layer | Intended responsibility | Current evidence boundary |
|---|---|---|
| Physical controller | Independent fixed interlocks, valid-data checks and safe response on power/communication loss | Proposed hardware architecture; physical tests remain |
| Sensors and laboratory | Operational monitoring plus use-specific laboratory verification | No MAWRID field measurements or treatment results in this prototype |
| Local application | Display, operator actions, history, exports and software session management | Working Python/SQLite prototype; no actuator connected |
| Digital twin | Inventory, flow and equipment-state calculations under declared assumptions | Synthetic inputs and fixed experimental rules |
| Research ML | Anomaly scores and research alarms on a qualified public-data replay | V9 optional replay only; no authority to open the reuse path |
| Cloud/remote services | Proposed reporting and support | Not established by the local-only application |

The outlet is allowed to operate only under an independently validated operating envelope. AI may add an alarm or a hold request; it cannot turn a failed/unknown condition into permission to irrigate. Software simulation rules are not physical safety certification.

Chlorine is measured directly and is not inferred from ORP. UV254 may support a target-specific surrogate model after calibration; it does not directly measure BOD/COD or prove microbial safety. UV presence or an animation does not establish validated dose/contact conditions.

## 5. Local software and 3D experience

The application separates a guided plant experience, component explanations, technology evidence and operating records. The embedded 3D scene reads the same virtual snapshots as the dashboard: stock, feed/product/reuse/backwash flows and equipment state. It does not issue actuator commands.

UX V8 adds an explicit automatic tour through eight explanatory stages. Each stage highlights its equipment and pipe, moves the camera, then allows reading time. Pause/resume preserves the presentation clock; it is separate from pausing the virtual process. Details, manual camera interaction, navigation, an unavailable service or a plant interruption pause the tour until explicit continuation. Completion does not inject a fault or start a new round. The stage sequence explains the design; it is not hydraulic travel time or a treatment-kinetics calculation.

The twin does not compute chemical reaction efficacy, microorganism removal, UV treatment, adsorption life or actual irrigation suitability. A `SIMULATED` record remains simulated when stored in SQLite or exported to CSV.

## 6. Material study and validation

Commercial carbon is the current base medium. Date-palm carbon advances only through a separate characterization and comparison study covering target removal, leaching, pressure loss, durability, media life and lifecycle cost. A research side column or later replacement is conditional; a rendered chamber is not an executed experiment.

Before field use, freeze the selected source/use envelope, hydraulics and instruments, qualify disinfection/storage, test actual controller/valve/power faults, review cross-connections and applicable requirements, and obtain site authorization. See the [validation plan](validation.md). Demonstration limits and future gates must remain visible in the project presentation.
