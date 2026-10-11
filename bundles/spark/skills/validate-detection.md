# Validate Detection

Use this skill when the operator wants to prove whether generated
telemetry created the expected detection, alert, case, or XQL result.

Procedure:

1. Confirm the simulation ID and expected detection behavior.
2. Run the relevant XQL query with `xsiam_run_xql_query`.
3. Inspect cases with `xsiam_get_cases` when detection should create
   a case or alert.
4. Call `phantom_run_detection_validation` with the observed result.
5. Return pass/fail status, missed detections, noisy fields, log
   source gaps, and recommended rules.
