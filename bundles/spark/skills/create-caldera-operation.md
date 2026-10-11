# Create Caldera Operation

Use this skill when the operator wants Phantom to coordinate offensive
emulation and defensive telemetry.

Procedure:

1. Search or list abilities with `caldera_get_all_abilities`.
2. Map selected ability IDs to ATT&CK techniques.
3. Ask for approval before launching an operation.
4. Create the adversary with `caldera_create_adversary`.
5. Create the operation with `caldera_create_operation`.
6. Read operation logs with `caldera_get_operation_event_logs`.
7. Generate matching defensive telemetry and validation guidance.
