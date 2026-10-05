# First physical validation — not executed

This file is a proposed manual test plan. It authorizes no automatic job and
contains no executable HTTP commands. All development tests have sockets disabled.
Physical writes require the user's separate go-ahead for that testing session.

## 1. Install and verify reads first

Install via README. Keep all four controls disabled. Confirm serial 12345678,
package 1.5.1+cert-meter, REST 2.5.0. Compare HA with the KEBA app:
vehicle plugged, charging state, session active, PWM, phase currents/voltages,
active power, exact session energy and lifetime energy, temperature and versions.
Record a new baseline with timestamp/session ID. Existing audit values are historical.
An open session must not imply charging. Check outages yield unavailable, not 0.
Save diagnostics and verify that no credentials/tokens are present.

With read-only GET, inspect the baseline charging profile. It must satisfy the
simple all-day/no-phase/single-wallbox contract in CONTROLS.md. Save its complete
non-secret contents for restoration. Do not proceed if there is a schedule,
phase field, different profile type, validity window or more than one wallbox.
Other active/higher-priority profiles must also be understood before interpreting
PWM changes. Do not change them as part of this test.

## 2. 16 A → 10 A → physical verification

Use a connected vehicle actively drawing approximately 16 A per used phase.
Enable only the Charging current limit number. Confirm its observed cap is 16 A.
Set 10 A once. Observe the response outcome and fresh profile, PWM and actual phase
currents for 30–60 seconds. PWM should be limited appropriately; actual current
may be lower because of vehicle demand or other limits. For an actively demanding
vehicle it should settle at or below 10 A per used phase. Record power and session
energy increase. Do not equate a 10 A profile with confirmed 10 A current.
On timeout/failure inspect state before any repeat, since the write may have applied.

## 3. 10 A → 16 A → physical verification

Set 16 A once. Verify stored cap, PWM and actual phase currents/power. Record
whether the vehicle ramps back up. It may legitimately draw less than 16 A.
If any unexpected phase change, session closure or persistent state mismatch
occurs, stop control testing and restore only the verified original profile cap.

## 4. Pause → verify / resume → verify — blocked pending semantics

Do **not** use stop/start or availability for this step. No pause entity exists.
Obtain authoritative KEBA confirmation of a session-preserving REST mechanism,
including zero-current validity if relevant. Implement/test that contract offline
and obtain authorization for the physical trial. Then record power=0, actual
currents, PWM/state and unchanged session ID during pause; on resume verify power,
phase currents, session ID continuity and precise energy. Until then this stage
is explicitly incomplete, and no zero-current profile is sent.

## 5. Start/stop last

After separately agreeing to proceed despite the pending pause test, enable one
button at a time. Record current session ID before stopping. Stop once and inspect
state, actual power, session status/end/duration and connector lock behavior. The
integration never requests unlock, but charger-side side effects must be observed.
Start once and record authorization behavior, session ID (new or continuing), PWM
and actual current/power. A plugged vehicle may decline charging even after an
accepted start. Preserve the raw non-secret response for contract verification.

## 6. Availability separately, while idle

Only after the above, enable availability. Disable while idle and verify
UNAVAILABLE; enable and verify return to operational state. Record session and
authorization effects. This test is not pause/resume. Restore the original state
and profile cap, then disable experimental controls in HA if monitoring is desired.

## Acceptance record

For every action record timestamp, endpoint, HTTP status, sanitized body,
profile/PWM/current/power before and after, session ID/status and side effects.
Record actual firmware/API versions. A successful mock test or accepted HTTP
response is not a physical verification. No phase switching, Modbus writes,
firmware, OCPP, PV or load-budget changes are part of this plan.
