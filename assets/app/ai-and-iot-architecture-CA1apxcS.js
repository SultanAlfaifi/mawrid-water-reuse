var e=`# AI and IoT Architecture\r
\r
> **Status:** Proposed architecture. The deterministic state machine can be prototyped before a predictive model is trained. No AI performance result is claimed.\r
\r
The first application is a university ablution-water treatment unit with a proposed irrigation outlet. The public static website is a demonstration interface for this use case. Its simulated telemetry, control state, and 3D flow illustration are separate from a field gateway, physical actuator, and laboratory record. A realistic rendering does not establish built hardware or treatment validation.\r
\r
## Design principle\r
\r
MAWRID separates decision support from safety authority:\r
\r
> AI predicts and explains. Validated rules protect the reuse outlet.\r
\r
The architecture must remain safe if the model, network, dashboard, cloud service, or a non-critical sensor fails.\r
\r
## Functional architecture\r
\r
\`\`\`mermaid\r
flowchart LR\r
    S[Water-quality and process sensors] --> E[Edge gateway]\r
    E --> V[Data validation]\r
    V --> R[Deterministic safety rules]\r
    V --> A[AI-assisted analytics]\r
    L[Laboratory results] --> Q[Traceable reconciliation]\r
    Q --> A\r
    A --> D[Dashboard and maintenance advice]\r
    R --> C[Fail-safe valve controller]\r
    C -->|validated state| U[Approved university irrigation]\r
    C -->|unknown or failed state| X[Reprocess, contain, or divert]\r
\`\`\`\r
\r
## Edge layer\r
\r
The bench prototype may use an ESP32-class gateway. A field pilot should select industrial hardware after a hazard and reliability review.\r
\r
The edge layer should:\r
\r
- timestamp and validate every reading;\r
- reject impossible, stale, or malformed values;\r
- calculate differential pressure and cumulative bed volumes;\r
- retain a local event buffer during network loss;\r
- execute the safety state machine locally;\r
- drive the diversion valve without depending on cloud connectivity.\r
\r
## Data layer\r
\r
Every observation should carry a sensor identifier, unit, timestamp, calibration status, quality flag, and evidence label. Laboratory records must preserve sample identity, collection time, method, result, unit, detection limit, and quality-control status.\r
\r
The initial implementation can use CSV or a small local database. A pilot may use MQTT for telemetry and a time-series database, subject to cybersecurity and data-governance review.\r
\r
The sample CSV uses a simulated gateway identifier and simulated calibration and quality flags. These fields demonstrate the data contract; they are not calibration certificates. A stale, missing, or invalid critical reading must produce a non-reuse state rather than be converted to zero or replaced silently with the last value.\r
\r
Browser alerts should expose the relevant reading, threshold, timestamp, rule version, and reason for the state transition. Keep control buttons and evidence labels in accessible HTML as well as any 3D scene. The public website does not command a real reuse valve.\r
\r
## Analytics layer\r
\r
### Transparent baseline\r
\r
The first release should use auditable rules:\r
\r
- rising differential pressure with falling flow suggests hydraulic clogging;\r
- rising outlet turbidity suggests loss of filtration integrity;\r
- a flat-lined or implausibly discontinuous signal suggests a sensor fault;\r
- repeated sensor-to-laboratory disagreement suggests possible drift;\r
- missing critical data forces a non-reuse state.\r
\r
### Candidate AI functions\r
\r
1. **Anomaly detection:** identify multivariable patterns that differ from validated normal operation.\r
2. **Filter-health estimation:** combine hydraulic loading, differential pressure, flow, and treatment indicators into an explainable condition estimate.\r
3. **Maintenance forecasting:** estimate a maintenance window only after multiple representative filter-life datasets are available.\r
\r
Models must be compared with the transparent baseline. A more complex model advances only if it improves prospective performance without weakening safety or interpretability.\r
\r
## Safety boundary\r
\r
AI outputs are advisory. They may trigger inspection, sampling, cleaning, or maintenance recommendations. They must not:\r
\r
- certify microbial or chemical safety;\r
- override a failed release criterion;\r
- open the reuse valve;\r
- silently change a sensor calibration;\r
- infer a safe state from the last valid reading.\r
\r
## Cybersecurity and resilience\r
\r
- Keep safety control local and independent of the public internet.\r
- Authenticate devices and restrict configuration changes.\r
- Encrypt remote communications where deployed.\r
- Log model versions, configuration changes, overrides, and alarms.\r
- Define safe behaviour for power, network, storage, and clock failures.\r
- Require human authorization for calibration changes and model deployment.\r
\r
## Minimum hackathon implementation\r
\r
- One edge gateway or a faithful hardware emulator.\r
- Flow, turbidity, and differential-pressure inputs.\r
- A local safety state machine connected to a visible valve or relay.\r
- A dashboard that shows current state, evidence label, alarms, and explanations.\r
- Reproducible normal, degradation, sensor-loss, and high-turbidity scenarios.\r
- Simulated data clearly labeled \`SIMULATED\`, with no claim of measured treatment performance.\r
`;export{e as default};