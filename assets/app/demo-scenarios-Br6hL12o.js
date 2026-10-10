var e=`# Demonstration Scenarios\r
\r
> **Evidence status:** These scenarios test software, control logic, and communication. Simulated inputs do not demonstrate treatment performance or water safety.\r
\r
The demonstration follows one story: separately collected university ablution water enters a proposed treatment unit, then a control decision selects the irrigation or diversion path. The university scene, product rendering, telemetry, valve animation, and irrigation flow shown in the web demo are illustrative or simulated unless a specific measured record is attached. No real university partnership, physical valve test, or field reuse is implied.\r
\r
## Scenario matrix\r
\r
| Scenario | Input pattern | Expected analytics output | Required safety response |\r
|---|---|---|---|\r
| Normal operation | Valid sensors inside the prototype envelope | No anomaly; filter condition stable | The simulated irrigation path can be shown only when every demo release rule passes; physical reuse requires separate validation and approval |\r
| Progressive clogging | Differential pressure rises while flow declines | Early maintenance alert with contributing signals | Continue closed-loop rules; divert if a validated limit is crossed |\r
| Filtration-integrity loss | Outlet turbidity rises sharply | High-severity anomaly | Close reuse valve and divert |\r
| Sensor signal loss | Critical sensor becomes stale or unavailable | Sensor-health alert | Close reuse valve and enter \`FAULT\` or \`DIVERT\` |\r
| Possible sensor drift | Repeated valid laboratory pairs disagree with the online signal | Drift-review recommendation | Treat the signal as untrusted when the declared rule is met |\r
| Network loss | Dashboard connection is interrupted | Communication alert when available | Local controller continues safely; no cloud dependency |\r
| Power interruption | Controller or actuator power is lost | Event logged after recovery | Valve fails closed |\r
\r
## Demo acceptance record\r
\r
For each run, record:\r
\r
- scenario and protocol version;\r
- start and end timestamp;\r
- input data and evidence label;\r
- analytics or ruleset version;\r
- alert, explanation, and detection delay;\r
- controller state and valve response;\r
- commanded valve position, independently observed position, and destination flow where hardware is present;\r
- observed result, deviation, and corrective action.\r
\r
A displayed state or software command does not establish that a physical valve moved or that water was diverted. Record browser simulation tests separately from hydraulic and treatment experiments. Numeric demo thresholds are declared software settings, not Saudi release limits or validated microbial criteria.\r
\r
## Judge-facing sequence\r
\r
1. Show the university ablution source, treatment unit, and proposed irrigation destination; identify all simulated elements.\r
2. Start with the normal scenario and show readings, rule evaluation, controller state, and selected path.\r
3. Introduce progressive clogging and show an explainable maintenance alert.\r
4. Inject a critical sensor loss or high-turbidity event.\r
5. Show the simulated controller closing the irrigation path independently of optional AI. If hardware is available, show and cite the physical response separately.\r
6. State clearly which evidence is simulated, measured, targeted, or not yet tested, and identify the next laboratory test.\r
`;export{e as default};