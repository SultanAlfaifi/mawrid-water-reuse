# Demonstration Scenarios

> **Evidence status:** These scenarios test software, control logic, and communication. Simulated inputs do not demonstrate treatment performance or water safety.

## Scenario matrix

| Scenario | Input pattern | Expected analytics output | Required safety response |
|---|---|---|---|
| Normal operation | Valid sensors inside the prototype envelope | No anomaly; filter condition stable | Reuse can be available only when every release rule passes |
| Progressive clogging | Differential pressure rises while flow declines | Early maintenance alert with contributing signals | Continue closed-loop rules; divert if a validated limit is crossed |
| Filtration-integrity loss | Outlet turbidity rises sharply | High-severity anomaly | Close reuse valve and divert |
| Sensor signal loss | Critical sensor becomes stale or unavailable | Sensor-health alert | Close reuse valve and enter `FAULT` or `DIVERT` |
| Possible sensor drift | Repeated valid laboratory pairs disagree with the online signal | Drift-review recommendation | Treat the signal as untrusted when the declared rule is met |
| Network loss | Dashboard connection is interrupted | Communication alert when available | Local controller continues safely; no cloud dependency |
| Power interruption | Controller or actuator power is lost | Event logged after recovery | Valve fails closed |

## Demo acceptance record

For each run, record:

- scenario and protocol version;
- start and end timestamp;
- input data and evidence label;
- analytics or ruleset version;
- alert, explanation, and detection delay;
- controller state and valve response;
- observed result, deviation, and corrective action.

## Judge-facing sequence

1. Start with the normal scenario and show the complete evidence chain.
2. Introduce progressive clogging and show an explainable maintenance alert.
3. Inject a critical sensor loss or high-turbidity event.
4. Show that deterministic logic closes the valve even if the AI service is unavailable.
5. State clearly which evidence is simulated, measured, targeted, or not yet tested.
