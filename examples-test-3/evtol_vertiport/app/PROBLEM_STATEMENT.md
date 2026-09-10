# Agent Brief: eVTOL Vertiport Recovery

You are advising an advanced air mobility operator that runs passenger eVTOL
service across a small metro vertiport network. The operator must decide which
requests to accept before the exact operating disruption is known, then produce
a scenario-specific aircraft schedule with passenger flights, repositioning
flights, and battery charging.

# eVTOL Vertiport Recovery

## Situation

The same accepted request set must be supportable under the listed weather and
equipment scenarios. In each scenario, aircraft begin at their home vertiports
with scenario-adjusted state of charge and release times. Schedules must keep
aircraft locations and battery state consistent while respecting route
availability, route duration, charging limits, pad use, charger use, corridor
capacity, time-specific airspace controls, grid headroom, local departure-noise
quotas, mandatory aircraft standby windows, emergency reserve requirements, and
minimum service floors by market and origin.

The evaluator checks the submitted policy exactly against the fixed public
data. Feasible schedules are scored by risk-adjusted expected profit.

## Planning Goal

Create a disruption-ready daily operating plan for the listed eVTOL fleet,
vertiports, passenger requests, routes, and weather/equipment scenarios. Before
the realized scenario is known, decide which passenger requests the operator
accepts. After each scenario is realized, produce a detailed aircraft schedule
that serves every accepted request using passenger flights, optional empty
repositioning flights, and charging sessions.

The score first checks whether the submitted policy follows all hard operating
rules. Among feasible policies, higher profit is better. The profit calculation
includes passenger fare, declined-request penalties, aircraft operating cost,
repositioning cost, charging cost, passenger delay penalties, and a tail-risk
charge for weak scenario outcomes.

## Requests And First-Stage Commitments

Each row in `data/requests.csv` is a passenger request with an origin,
destination, departure window, passenger count, market, priority class, fare,
and penalty for declining it. Submit exactly one `accept` row for every request.
The decision must be either `accept` or `decline`.

The accepted request set is a first-stage commitment. Every accepted request
must be served once in every scenario. Declined requests must not appear as
served passenger flights. To avoid a policy that only cherry-picks easy trips,
the accepted set must satisfy the global passenger fraction, medical passenger
fraction, airport passenger floor, priority-decline limit, and origin service
floors listed in the public data.

`data/request_groups.csv` lists requests that represent a small travel party,
coordinated medical movement, or linked evening recovery wave. Requests in the
same group must be accepted or declined together. When a group is accepted, its
served departures in each scenario must remain close enough to operate as one
coordinated wave.

## Aircraft, Routes, And Scenarios

Each row in `data/aircraft.csv` gives an aircraft home vertiport, passenger
capacity, initial battery state, charging rate, turnaround time, and noise
class. Scenario-specific release times and state-of-charge derates are in
`data/scenario_aircraft_availability.csv`.

Each row in `data/routes.csv` is a directed route. Scenario route status,
flight-time multipliers, and energy multipliers are in
`data/scenario_route_availability.csv`. A passenger or repositioning flight is
allowed only when its route is open in that scenario. The scheduled duration
must be at least the scenario-adjusted route duration.

Every aircraft schedule must be time ordered. An aircraft can only start an
action from its current vertiport, cannot run overlapping actions, cannot move
before its scenario release time, must observe its turnaround time between
non-charging actions, and must keep enough battery reserve after every flight.

`data/aircraft_service_windows.csv` lists scenario-specific standby or
inspection windows. During such a window, the named aircraft must be idle at the
listed vertiport and must have at least the listed state of charge. These
windows model medical standby coverage, post-release safety checks, and airport
recovery reserves.

## Charging And Energy

Use `charge` rows for scenario charging sessions. A charging session occurs at
the aircraft's current vertiport and adds the submitted `energy_kwh` to the
aircraft battery after applying no additional hidden conversion. The submitted
energy must fit within the aircraft's battery capacity, charger power, local
charger count, and scenario-adjusted grid headroom.

Charging above the high-SOC threshold is slower. If a charging session finishes
above that threshold, the portion above the threshold must fit within the
tapered charging allowance in `data/config.json`. This is a hard operational
rule, not a soft cost.

## Vertiport, Corridor, Grid, And Noise Rules

For each scenario and time slot:

- Departures and arrivals at a vertiport consume pad capacity.
- Charging sessions consume charger capacity and grid headroom.
- Flights consume the capacity of their route corridor for each occupied slot.
- Scenario-specific corridor controls in `data/corridor_slot_controls.csv`
  may further reduce the number of flights allowed on a corridor during a
  control window.
- Departures consume local noise quota based on the route and aircraft noise
  class. Day and evening quotas are separate.

The schedule may use empty repositioning flights, but those flights consume the
same route, pad, corridor, energy, and noise resources as passenger flights and
earn no fare.

`data/emergency_reserve_requirements.csv` lists checkpoint slots where the
operator must keep a minimum number of idle aircraft at a vertiport with enough
battery to absorb medical or airport recovery calls.

## Data Dictionary

`data/config.json`

- `slot_minutes`: length of one schedule slot.
- `planning_horizon_slots`: last slot boundary available for scheduled actions.
- `minimum_accepted_passenger_fraction`: minimum accepted share of all listed
  passengers.
- `minimum_medical_accepted_fraction`: minimum accepted share of medical
  passengers.
- `minimum_airport_accepted_passengers`: minimum accepted passengers in the
  airport market.
- `maximum_declined_priority_requests`: maximum declined requests whose
  priority is airport or medical.
- `reserve_soc_kwh`: required battery reserve after each flight.
- `charge_efficiency`: used by the evaluator when checking grid draw.
- `high_soc_threshold_fraction`: battery level where tapered charging begins.
- `taper_charge_fraction`: relative rate allowed above the high-SOC threshold.
- `tail_risk_alpha`, `tail_risk_weight`: parameters for the tail-risk charge.
- `delay_penalty_per_passenger_slot`: soft penalty for leaving a served request
  later than its earliest departure slot.
- `reposition_cost_per_kwh`: cost of empty positioning movements.
- `quantity_tolerance`: numeric tolerance used by the checker.

`data/vertiports.csv`

- `vertiport_id`: vertiport identifier.
- `district`: district label.
- `pad_count`: simultaneous departure/arrival handling capacity per slot.
- `charger_count`: simultaneous charging sessions.
- `parking_stands`: physical aircraft parking stands.
- `grid_kw_limit`: normal charging grid limit.
- `departure_noise_quota_day`, `departure_noise_quota_evening`: local departure
  noise budgets.
- `medical_gateway`: whether the vertiport is a medical gateway.

`data/aircraft.csv`

- `aircraft_id`: aircraft identifier.
- `home_vertiport`: starting location.
- `seat_capacity`: passenger capacity.
- `battery_capacity_kwh`: battery capacity.
- `initial_soc_kwh`: starting state of charge before scenario derates.
- `max_charge_kw`: maximum charger power.
- `turnaround_slots`: minimum idle slots after flight-like actions.
- `noise_class`: multiplier applied to route noise points.

`data/routes.csv`

- `origin`, `destination`: directed vertiport pair.
- `corridor_id`: shared airspace corridor.
- `flight_slots`: nominal flight duration in schedule slots.
- `energy_kwh`: nominal energy required.
- `operating_cost`: passenger flight operating cost.
- `noise_points`: base departure-noise points.
- `corridor_capacity_per_slot`: simultaneous aircraft capacity.

`data/requests.csv`

- `request_id`: request identifier.
- `origin`, `destination`: requested trip.
- `earliest_slot`, `latest_depart_slot`: acceptable departure window.
- `passengers`: passenger count.
- `priority_class`: airport, medical, or standard.
- `market`: demand market label.
- `fare_per_passenger`: earned fare if served.
- `decline_penalty`: penalty for declining the request.

`data/scenarios.csv`

- `scenario_id`: scenario identifier.
- `probability`: scenario probability.
- `description`: operating condition.
- `global_delay_slots`: common disruption delay applied to scenario route
  duration.
- `charger_derate`: scenario multiplier on charging power and grid headroom.
- `soc_derate`: scenario multiplier on starting battery state.
- `target_profit`: scenario service target used in the tail-risk charge.

`data/scenario_route_availability.csv`

- `scenario_id`, `origin`, `destination`: route key.
- `open`: whether the route may be flown.
- `flight_slot_multiplier`: route duration multiplier.
- `energy_multiplier`: route energy multiplier.

`data/scenario_aircraft_availability.csv`

- `scenario_id`, `aircraft_id`: aircraft scenario key.
- `release_slot`: earliest slot when the aircraft may operate.
- `soc_derate`: starting battery derate.

`data/grid_prices.csv`

- `vertiport_id`, `slot`: grid key.
- `price_per_kwh`: charging energy price.
- `grid_limit_multiplier`: local grid headroom multiplier.

`data/origin_service_floors.csv`

- `origin`: request-origin vertiport.
- `minimum_accepted_passengers`: minimum accepted passengers from that origin.

`data/request_groups.csv`

- `group_id`: coordinated request group.
- `request_id`: request included in the group.
- `max_departure_spread_slots`: maximum spread between served departures in the
  same group and scenario when the group is accepted.
- `group_rule`: business label for the group rule.

`data/aircraft_service_windows.csv`

- `scenario_id`, `aircraft_id`: aircraft-scenario key.
- `vertiport_id`: required standby or inspection location.
- `start_slot`, `end_slot`: window during which the aircraft must remain idle.
- `min_soc_kwh`: minimum state of charge throughout the window.
- `window_type`: business reason for the window.

`data/emergency_reserve_requirements.csv`

- `scenario_id`, `vertiport_id`, `slot`: reserve checkpoint key.
- `min_idle_aircraft`: minimum idle aircraft count required at that checkpoint.
- `min_soc_kwh`: minimum battery state for an aircraft to count toward reserve.
- `reason`: business reason for the reserve checkpoint.

`data/corridor_slot_controls.csv`

- `scenario_id`, `corridor_id`: controlled airspace key.
- `start_slot`, `end_slot`: slot interval where the control applies.
- `max_flights_per_slot`: maximum simultaneous flights occupying that corridor
  during controlled slots.
- `reason`: business reason for the control.

## Submission Format

Submit a single CSV with exactly these columns:

```csv
row_type,scenario_id,aircraft_id,request_id,origin,destination,start_slot,end_slot,energy_kwh,quantity,decision
```

Use these row types:

- `accept`: one row per request. Use `request_id` and `decision` set to
  `accept` or `decline`. Leave scenario, aircraft, origin, destination, slots,
  energy, and quantity blank.
- `flight`: one row for each scenario passenger flight. Include scenario,
  aircraft, request, origin, destination, start slot, end slot, energy, served
  passenger quantity, and `decision` set to `serve`.
- `reposition`: one row for each scenario empty movement. Include scenario,
  aircraft, origin, destination, start slot, end slot, energy, and `decision`
  set to `reposition`. Leave request and quantity blank.
- `charge`: one row for each scenario charging session. Include scenario,
  aircraft, origin, start slot, end slot, charged energy, and `decision` set to
  `charge`. Leave request, destination, and quantity blank.

Slots are integer slot boundaries. Energies and quantities must be nonnegative
decimal numbers. Do not include unknown aircraft, requests, vertiports, routes,
or scenarios.
