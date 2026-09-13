# Sensor and Laboratory Workflow

> **Purpose:** Use laboratory evidence to check online measurements without claiming that a delayed laboratory result can automatically calibrate every sensor.

## Workflow

1. Record sensor values with UTC timestamps, units, device identifiers, and calibration status.
2. Collect a representative sample at a declared location and time.
3. Preserve, transport, and analyze the sample using a documented method and quality-control plan.
4. Record the result, unit, method, detection limit, uncertainty where available, and quality-control status.
5. Match the laboratory result to the relevant sensor window, accounting for hydraulic travel and sampling location.
6. Calculate a comparable difference only when the methods and measured quantities are compatible.
7. Look for persistent disagreement across repeated valid pairs.
8. Flag possible fouling, drift, sampling error, or process change for review.
9. Clean, inspect, or calibrate the instrument using its approved procedure.
10. Document the action and confirm performance before returning the signal to trusted service.

## Why automatic calibration is not the baseline

A disagreement is not proof that the online sensor is wrong. It can result from timing, sample handling, laboratory uncertainty, spatial variability, sensor fouling, or a real process change. MAWRID therefore uses laboratory reconciliation to recommend investigation. It does not silently rewrite calibration coefficients.

## Minimum record fields

See [`../data/laboratory-results-schema.csv`](../data/laboratory-results-schema.csv) for a machine-readable header and example record.

## Decision labels

- `MATCH`: difference is within the predeclared comparison criterion.
- `REVIEW`: repeated or material disagreement requires technical review.
- `INVALID_PAIR`: timing, location, method, or quality control prevents comparison.
- `CALIBRATION_DUE`: the instrument requires its approved calibration procedure.
- `OUT_OF_SERVICE`: the signal cannot support a release decision.

## Safety response

If the affected measurement is critical to release and cannot be trusted, the safety controller closes the reuse valve. A model cannot restore trust or reopen the valve.
