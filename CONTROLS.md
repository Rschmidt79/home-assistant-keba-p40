# Controls and feedback contracts

All controls are disabled by default in HA's entity registry. They run only when
an enabled entity receives an explicit user/service action. No physical control
request was performed while building this package. The polling code cannot invoke
controls. The API allowlist excludes unlock, phase-toggle, firmware, reboot, OCPP
configuration and Modbus/config write endpoints.

## Number: Charging current limit

- Unique ID: `{serial}_charging_current_limit`.
- Range: 6–min(16, observed `wallbox.maxCurrent / 1000`) A. 0, <6, >16, bool,
  nonfinite values and values more precise than mA are rejected before any write.
- GET `/v2/wallboxes` must show exactly this one wallbox. The profile is charge-point
  wide; it is not a per-wallbox API suitable for an unexamined charging network.
- GET `/v2/profiles/chargepointmaxprofilezero` must return an active, absolute,
  level-zero `CHARGE_POINT_MAX_PROFILE`, socketNumber 0, with one whole-day item
  covering all seven days, no validity window and no explicit `numberOfPhases`.
- POST `/v2/profiles/chargepointmaxprofilezero` with:

```json
{
  "profileItems": [{
    "startTime": "00:00:00",
    "stopTime": "24:00:00",
    "daysOfWeek": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"],
    "maxCurrentOffered": 10000
  }]
}
```

The existing item's optional name/other fields are preserved. No phase field is
added. No new OCPP-sourced profile is created and no OCPP settings are altered.
The name “profilezero” means stack-level zero, not a zero-current request.

Feedback: GET the same profile and require the actual stored cap to match the
requested mA, then refresh wallbox, config and session data. The number reads this
profile cap; the independent PWM sensor reads `meter.currentOffered`, and actual
current sensors read `meter.lines[].current`. Higher priority profiles, installer
limits, vehicle demand and temperature can reduce current below the cap. The
integration never substitutes the desired cap for measured PWM or actual current.
A delayed/unconfirmed profile update causes an error, without replaying the write.

## Buttons: Start charging / Stop charging

POST `/v2/wallboxes/{serial}/start-charging` or
`/v2/wallboxes/{serial}/stop-charging`, no request body. No unlock call is chained.
The OpenAPI explicitly documents start without a token-id query as an example;
authorization behavior remains subject to physical validation. Feedback is a
fresh GET wallbox state/measurements and sessions. Accepted start is not proof
that the vehicle is already charging. Stop is not advertised as session-preserving
pause, and its end/unlock behavior must be recorded during the final physical test.

## Switch: Charging availability

POST `/v2/wallboxes/{serial}/change-availability` with `{"available": true}` or
`{"available": false}`. This is operational availability (out of order), not a
pause switch. OFF feedback is `state=UNAVAILABLE`. ON feedback is one of
IDLE/READY_FOR_CHARGING/CHARGING/SUSPENDED. Error/offline/unknown states make this
switch unavailable rather than pretending it is enabled. No local wish is saved.
Effects on an ongoing session remain untested; test only after start/stop trials.

## Response validation and authentication

- Only HTTP 200/202 are accepted; redirects are not followed.
- An `acceptStatus` must equal `ACCEPTED`. REJECTED, FAILED, CONFLICT, NOT_FOUND,
  unknown values and null are errors, even when other fields look valid.
- **The KEBA schema does not uniformly return acceptStatus.** HTTP 200 for the
  profile endpoint documents a `v2Profile`; HTTP 200 for start/stop/availability
  documents `v2Wallbox`. These exact alternative contracts are explicitly checked.
  A missing acceptStatus alone is never assumed to mean success; `{}`, a message
  string, wrong serial, wrong state or invalid profile is rejected. HTTP 202 without
  explicit ACCEPTED is always rejected.
- Auth/reads and fresh login for controls share one async lock. Controls are
  serialized by a second coordinator lock. Tokens are memory-only.
- Timeout, rejected command or transport error still triggers a physical GET
  refresh. No write is automatically retried. Failed feedback makes entities
  unavailable and reports an uncertain outcome.
- Request acceptance and physical achievement are different. There is no
  optimistic state, no stored phase target and no automatic control algorithm.

## Pause/resume: pending, no entity

REST 2.5.0 offers no dedicated documented session-preserving pause/resume endpoint.
A `maxCurrentOffered=0` profile might suspend charging, but its validity, session
preservation and resumption semantics have not been established by our REST audit.
We do not infer REST behavior from Modbus register 5004. No zero-current write is
implemented and stop/start or availability are not relabeled pause/resume.
This is the outstanding requested feature; it needs KEBA confirmation and a
separately authorized physical test before exposing an entity.

## Phase switching: mapped only

Documented POST `/v2/wallboxes/{serial}/phase-toggle?numberOfPhases=1|3`, `{}` body.
Profile items can also contain `numberOfPhases`. Neither path is implemented or
allowlisted. Future work must verify configuration/capabilities, accepted response,
phase feedback under real load, intermediate current and external changes. Audit
showed connector_phase_enable=false and source=CPM_PROFILES; no change was made.
