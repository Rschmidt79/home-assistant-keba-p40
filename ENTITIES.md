# Entity list

Unique IDs retain `{serial}_{key}`; for this device the prefix is `12345678_`.
One device has identifier `(keba_p40, serial)`. Entity IDs/friendly names are not
stable identifiers. All original 32 monitoring entities remain enabled by default.
The four new controls are registered disabled; enable explicitly to instantiate.
All entities use coordinator availability, and missing measurements are unavailable.

W = GET `/v2/wallboxes/{serial}`. S = GET `/v2/sessions` with serial filter, newest
first, preferring an open session and otherwise the most recent completed session.
C = REST GET config group. Strings/config properties refer to physically audited
fields except the new baseline-profile control, which is documentation-only.

| Name / key | Type | Source / conversion | Semantics |
|---|---|---|---|
| Vehicle plugged / vehicle_plugged | binary_sensor | W.vehiclePlugged | Plugged, not charging |
| Charging / charging | binary_sensor | W.state == CHARGING | Actual KEBA charging state |
| Session active / session_active | binary_sensor | W.sessionActive | Open session, may be blocked |
| Error / error | binary_sensor, problem | W.state in RECOVER_FROM_ERROR/UNRECOVERABLE_ERROR/DEGRADED | Error-state indicator, not raw error code |
| Charging state / charging_state | sensor | W.state | Known KEBA enum, unknown enum unavailable |
| Session status / session_status | sensor | S.status | INITIATED/PWM_CHARGING/BLOCKED/CLOSED |
| Active power / active_power | sensor, W, measurement | W.meter.totalActivePower / 1000 | Measured mW→W |
| Current L1 / current_l1 | sensor, A, measurement | W.meter.lines[L1].current / 1000 | Actual current |
| Current L2 / current_l2 | sensor, A, measurement | W.meter.lines[L2].current / 1000 | Actual current |
| Current L3 / current_l3 | sensor, A, measurement | W.meter.lines[L3].current / 1000 | Actual current |
| Voltage L1 / voltage_l1 | sensor, V, measurement | W.meter.lines[L1].voltage | Measured voltage |
| Voltage L2 / voltage_l2 | sensor, V, measurement | W.meter.lines[L2].voltage | Measured voltage |
| Voltage L3 / voltage_l3 | sensor, V, measurement | W.meter.lines[L3].voltage | Measured voltage |
| Current offered / current_offered | sensor, A, measurement | W.meter.currentOffered / 1000 | Actual offered PWM, not actual draw |
| Maximum current / maximum_current | sensor, A, measurement | W.maxCurrent / 1000 | Reported maximum, audit 16 A |
| Total energy / total_energy | sensor, kWh, total_increasing | W.meter.meterValue / 1000000 | Lifetime energy, Energy Dashboard |
| Session energy / session_energy | sensor, kWh, total | S.energyConsumed / 1000000 | Exact energy; last_reset=S.startDate; never energyConsumedInKwh |
| Temperature / temperature | sensor, °C, measurement | W.meter.temperature / 100 | Signed measured temperature |
| Power factor / power_factor | sensor, %, measurement | W.meter.totalPowerFactor / 10 | KEBA per-mille→percent |
| Session start / session_start | sensor, timestamp | S.startDate / 1000 → UTC datetime | API milliseconds |
| Session end / session_end | sensor, timestamp | S.endDate / 1000 → UTC datetime | Unavailable while no end exists |
| Session duration / session_duration | sensor, s, measurement | S.duration / 1000 | Includes waiting, not just charging |
| Model / model | diagnostic sensor | W.model | Device model, also device metadata |
| Serial / serial | diagnostic sensor | Authenticated identity | Stable identity |
| Package version / package_version | diagnostic sensor | C.system/application_version_package | Full package, audit 1.5.1+cert-meter |
| BaseIO firmware / baseio_firmware | diagnostic sensor | W.firmwareVersion | Audit 5.0.1 |
| Meter firmware / meter_firmware | diagnostic sensor | W.firmwareVersionMetering | Audit 3.0.1 |
| Safety firmware / safety_firmware | diagnostic sensor | W.firmwareVersionSafety | Audit 3.1.3 |
| API version / api_version | diagnostic sensor | GET /version | Audit 2.5.0 |
| REST alias / rest_alias | diagnostic sensor | C.restapi/restapi_alias | Metadata/name; not stable identity; distinct from W.alias |
| Failsafe current / failsafe_current | diagnostic sensor, A | C.modbus.modbus_failsafe_current / 1000 | Modbus failsafe config read over REST; not live PWM |
| Failsafe timeout / failsafe_timeout | diagnostic sensor, s | C.modbus.modbus_failsafe_timeout | Modbus failsafe timeout, audit 30 s |
| Charging current limit / charging_current_limit | number, A, config, disabled | GET baseline profile.items[0].maxCurrentOffered / 1000 | Observed profile cap; 6–16 A control, not load budget |
| Start charging / start_charging | button, disabled | POST …/start-charging | Explicit action; feedback from W/S |
| Stop charging / stop_charging | button, disabled | POST …/stop-charging | Explicit action; not reversible pause |
| Charging availability / charging_availability | switch, config, disabled | W.state / POST …/change-availability | Operational available/out-of-order, not pause |

Additional parsed diagnostic values (not extra entities): authorization_enabled,
load_management_budget, hardware_revision and package_base_version. Authorization
configuration is not proof of a particular vehicle/token being authorized.

No VIN, vehicle identity, frequency or measured per-phase active power entity is
invented. No active phase select, price scheduling, PV/load balancing or controls
for undocumented fields are present. Pause/resume remains deferred as explained
in CONTROLS.md and PHYSICAL_TEST_PLAN.md.
