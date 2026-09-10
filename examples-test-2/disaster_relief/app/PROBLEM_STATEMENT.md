# Agent Brief: Disaster Relief Prepositioning

You are advising a regional emergency management agency before the next major
disaster season. The agency must decide which relief warehouses to activate and
how many water, meal, and medical kits to pre-position before the exact event is
known. After one of the listed disaster scenarios occurs, it must route supplies
over the first 72 hours, assign limited vehicle fleets, buy limited emergency
stock, and leave a small amount of demand unmet at a high penalty.

# Disaster Relief Prepositioning

## Situation

The agency has candidate warehouses, uncertain scenario demand, damaged road
capacities, warehouse usability losses, period-by-period response targets,
limited emergency procurement, finite vehicle fleets, and minimum service and
fairness expectations. Your submitted plan includes both first-stage
preparedness decisions and scenario-by-scenario, period-by-period recourse
decisions. The evaluator checks the policy exactly against the fixed public data
and scores the expected plus tail-risk relief cost.

## Planning Goal

Create a disaster-season relief plan for the listed candidate warehouses,
evacuation zones, relief items, and weighted disaster scenarios. Before the
event type is known, decide which warehouses to activate and how much stock of
each item to pre-position. After a scenario is realized, decide how to route
available stock across the first 72 hours, which fleet type carries each
shipment, how much emergency stock to buy, and how much demand remains unserved.

The score first checks whether the submitted policy follows all hard planning
rules. Among feasible policies, lower score is better. The score includes
warehouse activation cost, pre-positioning cost, expected scenario-period
transport, fleet dispatch, emergency procurement, and unmet-demand costs, plus a
tail-risk charge for the most expensive disaster scenarios.

## Warehouses And Inventory

Each row in `data/warehouses.csv` is a candidate relief warehouse. A warehouse
has an activation cost, storage capacity, outbound handling capacity, cold-chain
capability, and disaster-resilience attributes. Use one `warehouse` row in the
submission for every candidate warehouse and mark it as either `open` or
`closed`.

Each row in `data/items.csv` is a relief item. Medical kits require cold-chain
storage. Use one `inventory` row for every warehouse-item pair. Closed
warehouses must hold zero inventory. Open warehouses must respect their total
storage capacity, each item's per-warehouse stock limit, and the planning
budget. At least two activated warehouses must have cold-chain capability, and
the agency may activate no more than the listed
maximum number of warehouses.

## Scenarios, Response Periods, And Recourse

Each row in `data/scenarios.csv` is a possible disaster scenario with a
probability and scenario-level emergency procurement caps. Demand appears in
`data/scenario_demands.csv` by scenario, zone, and item.

`data/periods.csv` divides the response into three 24-hour operating periods.
For every scenario-zone-item combination, the submitted policy must account for
the full demand through delivered pre-positioned stock, emergency procurement,
and unmet demand across these periods. Emergency procurement is limited both by
the scenario's item-level cap and by each zone's local emergency-procurement
fraction. Unmet demand is allowed but expensive and cannot be used to bypass
the service rules below.

## Roads, Warehouse Damage, And Delivery

`data/lanes.csv` lists the allowed warehouse-to-zone relief lanes. Shipments are
allowed only on listed lanes. Each lane has a base capacity and transport cost.
`data/scenario_period_lane_impacts.csv` gives scenario-period capacity
multipliers, travel times, and extra transport costs for disrupted roads as they
partially recover over time.

`data/scenario_warehouse_availability.csv` gives, for each scenario and
warehouse, the usable fraction of pre-positioned stock and the outbound handling
multiplier. In a scenario, total shipments from a warehouse for an item cannot
exceed the usable portion of the stock placed there before the disaster. Total
outbound load from a warehouse across all response periods cannot exceed its
scenario-adjusted handling capacity.

`data/fleet_types.csv` defines vehicle classes, including general trucks,
cold-chain trucks, light utility vehicles, and airlift support.
`data/warehouse_fleet.csv` gives the number of trips of each fleet type
available at each warehouse and period. Medical kits must use cold-chain-capable
fleet. Mountain, bridge, and coastal disruption lanes can always use light
utility or airlift support, but heavier trucks may be blocked in early periods
when travel time exceeds their operating limit. Deliveries that arrive later
than a zone's response target incur an additional response-delay penalty in the
score. This penalty is soft; the service rules remain hard.

## Service And Fairness Rules

Every zone has item-specific final service floors. The response target schedule
specifies how much of that final service floor must be reached cumulatively by
each response period for each zone priority and item. Delivered supply,
including routed stock and emergency procurement, must
meet these period targets for every scenario, zone, and item.

Critical zones should not be sacrificed while easier standard or remote zones
are overserved. For each scenario and item, no critical zone may have a fill
rate more than the configured fairness gap below any non-critical zone's fill
rate.

## Data Dictionary

`data/config.json`

- `planning_budget`: maximum activation plus pre-positioning spend.
- `max_open_warehouses`: maximum number of warehouses that may be activated.
- `min_open_cold_chain_warehouses`: minimum activated cold-chain warehouses.
- `fairness_gap`: maximum allowed fill-rate gap from a critical zone to a
  non-critical zone for the same item and scenario.
- `tail_risk_alpha`: confidence level used for the tail-risk term.
- `tail_risk_weight`: multiplier applied to the tail-risk term.
- `late_response_penalty_per_load_hour`: extra cost for deliveries that miss a
  zone's response target.
- `quantity_tolerance`: numeric tolerance used by the checker.

`data/warehouses.csv`

- `warehouse_id`: warehouse identifier.
- `region`: operating region.
- `open_cost`: fixed activation cost.
- `storage_capacity`: total storage capacity.
- `outbound_capacity`: normal outbound load capacity per scenario.
- `cold_chain`: whether cold-chain medical storage is available.
- `seismic_reinforced`: whether the facility is hardened against earthquake
  damage.
- `staff_team`: staffing team category.

`data/items.csv`

- `item_id`: relief item identifier.
- `unit_volume`: storage capacity consumed by one unit.
- `load_factor`: outbound and road capacity consumed by one unit.
- `preposition_cost`: first-stage stocking cost per unit.
- `emergency_procure_cost`: scenario procurement cost per unit.
- `shortage_penalty`: scenario cost per unit of unmet demand.
- `cold_chain_required`: whether the item requires cold-chain warehousing.
- `max_stock_per_warehouse`: maximum stock of this item at one warehouse.

`data/zones.csv`

- `zone_id`: evacuation zone identifier.
- `district`: district label.
- `priority_class`: critical, standard, or remote.
- `population`: planning population.
- `water_floor`, `meal_floor`, `medical_floor`: minimum delivered fraction.
- `emergency_procure_limit_fraction`: maximum fraction of local demand that may
  be covered by emergency procurement.
- `target_response_hours`: response-time target used for soft delay penalties.

`data/lanes.csv`

- `warehouse_id`, `zone_id`: allowed relief lane.
- `distance_km`: approximate road distance.
- `travel_time_hours`: normal delivery travel time before scenario-period
  disruption adjustments.
- `base_capacity`: normal scenario lane capacity.
- `transport_cost_per_load`: base transport cost per unit load factor.
- `road_class`: road-disruption category.

`data/scenarios.csv`

- `scenario_id`: disaster scenario identifier.
- `probability`: scenario probability.
- `disaster_type`: scenario family.
- `<item>_procure_cap`: maximum emergency procurement of that item.

`data/periods.csv`

- `period_id`: response period identifier.
- `start_hour`, `end_hour`: operating window.
- `label`: plain-language period label.
- `delay_penalty_multiplier`: relative delay-cost weight for late deliveries in
  that period.

`data/fleet_types.csv`

- `fleet_type`: vehicle class identifier.
- `capacity_load`: load capacity per available trip.
- `cold_chain_capable`: whether the fleet can carry medical kits.
- `rough_road_capable`: whether the fleet can use badly disrupted lanes.
- `airlift_capable`: whether the fleet can bypass road-class restrictions.
- `fixed_trip_cost`: dispatch cost per used trip equivalent.
- `max_travel_time_hours`: maximum one-way travel time this fleet can serve.

`data/warehouse_fleet.csv`

- `warehouse_id`, `period_id`, `fleet_type`: fleet availability key.
- `available_trips`: available trip equivalents in that period.

`data/scenario_demands.csv`

- `scenario_id`, `zone_id`, `item_id`: demand key.
- `demand`: scenario demand.

`data/scenario_warehouse_availability.csv`

- `scenario_id`, `warehouse_id`: availability key.
- `usable_fraction`: fraction of pre-positioned stock usable after damage.
- `outbound_multiplier`: multiplier on outbound handling capacity.

`data/scenario_period_lane_impacts.csv`

- `scenario_id`, `period_id`, `warehouse_id`, `zone_id`: lane-impact key.
- `capacity_multiplier`: multiplier on base lane capacity.
- `extra_transport_cost_per_load`: extra scenario transport cost.
- `travel_time_hours`: scenario-period travel time.

`data/period_service_targets.csv`

- `priority_class`, `item_id`, `period_id`: response target key.
- `cumulative_fraction_of_final_floor`: fraction of the zone's final service
  floor that must be reached by the end of that period.

## Submission Format

Submit a single CSV with exactly these columns:

```csv
row_type,scenario_id,period_id,warehouse_id,zone_id,item_id,fleet_type,quantity,decision
```

Use these row types:

- `warehouse`: one row per warehouse, with `warehouse_id` and `decision` set to
  `open` or `closed`. Leave scenario, period, zone, item, fleet, and quantity
  blank.
- `inventory`: one row per warehouse-item pair, with `warehouse_id`, `item_id`,
  `quantity`, and `decision` set to `stock`. Leave scenario, period, zone, and
  fleet blank.
- `ship`: one row for each positive shipment, with scenario, period, warehouse,
  zone, item, fleet type, quantity, and `decision` set to `ship`.
- `procure`: one row for every scenario-period-zone-item combination, with
  scenario, period, zone, item, quantity, and `decision` set to `procure`. Leave
  warehouse and fleet blank.
- `unmet`: one row for every scenario-period-zone-item combination, with
  scenario, period, zone, item, quantity, and `decision` set to `unmet`. Leave
  warehouse and fleet blank.

Quantities must be nonnegative decimal numbers. Do not include rows for
warehouses, zones, items, scenarios, or lanes that are not listed in the public
data.
