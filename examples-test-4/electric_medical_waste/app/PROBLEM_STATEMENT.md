# Agent Brief: Electric Medical Waste Location-Routing

You are helping a regional healthcare logistics team plan one day of infectious
medical-waste collection with electric vehicles. The public data gives clinics,
EVs, treatment facilities, charging stations, and a directed urban travel-energy
matrix. The plan must collect every clinic's red-bag and yellow-bag waste,
respect clinic service windows, unload at compatible treatment facilities, keep
hazardous waste from riding too long, and manage EV battery state with partial
charging when needed.

# Electric Medical Waste Location-Routing

A healthcare logistics contractor must plan one collection day for infectious
medical waste. Clinics generate red-bag and yellow-bag waste. Electric vehicles
start and end at the depot, visit clinics during their service windows, unload
waste at compatible treatment facilities, and may recharge at listed charging
stations. Every clinic must be collected exactly once.

The contractor wants a low-cost, operationally credible plan. The score combines
vehicle use, treatment-facility activation, travel distance, charging energy,
treatment handling, and infection-risk exposure while waste is onboard. Risk is
higher when red-bag waste stays on vehicles longer or moves through denser urban
links. The data is intentionally not rounded to tidy planning values.

## Operational Rules

- A used vehicle starts at its listed start node and ends at its listed end node.
- A vehicle may visit multiple clinics before unloading, but total load, red-bag
  load, and yellow-bag load must stay within that vehicle's compartments.
- Clinic service may start after early arrival, but not after the listed latest
  service time.
- Waste collected from a clinic must be unloaded before that clinic's listed
  maximum onboard time for each waste class.
- Vehicles have waste-handling permits by clinic priority class. A vehicle may
  only pick up clinics whose priority class it is permitted to handle, and each
  vehicle has a daily cap on isolation pickups.
- Some clinic pairs cannot be carried on the same vehicle segment before an
  unload because the contractor requires separate sealed-tote handling for
  those generators.
- An unload event sends all onboard waste to that treatment facility. The
  facility must accept every onboard waste class and stay within its daily and
  class-specific capacities.
- Treatment facilities receive trucks through dated dock windows. Each unload
  must occur inside one listed receiving window for that facility, and each
  facility-window has both an unload-count cap and a kg cap.
- At most the listed maximum number of treatment facilities may be used. Any
  opened facility must receive a meaningful minimum amount of waste.
- EV battery is consumed on every directed road movement. Energy use depends on
  the listed empty-trip energy plus the current onboard load and distance.
- A charge event may add a positive amount of energy at the listed station, but
  the vehicle battery cannot exceed its capacity. Charging consumes queue time
  plus charging time, and each station has daily energy and session limits.
- Some central directed links have a loaded-movement curfew. If a vehicle is
  carrying waste and would traverse one of those links during the restricted
  window, it may wait until the window clears, but the waiting time still counts
  for shift time and onboard-risk exposure.
- A vehicle must finish within its shift and must be empty when it ends.

## Data Dictionary

- `config.json`: global planning settings, curfew window, and cost/risk weights.
- `nodes.csv`: node coordinates and node types used by all other tables.
- `clinics.csv`: clinic demand, service windows, service durations, priority
  class, and maximum onboard time limits.
- `vehicles.csv`: EV depot, capacity, battery, shift, and fixed-use cost.
- `vehicle_waste_permits.csv`: priority classes each EV crew may collect and
  isolation-pickup limits.
- `treatment_facilities.csv`: treatment node, opening cost, capacity, receiving
  cutoff, and permit class.
- `facility_waste_rules.csv`: which waste classes each facility may process and
  their handling costs.
- `facility_receiving_windows.csv`: facility dock windows, unload event limits,
  and kg limits by window.
- `incompatible_pickup_pairs.csv`: clinic pairs that cannot be co-loaded before
  an unload.
- `chargers.csv`: charger node, rate, expected queue delay, daily energy cap,
  session limit, and energy price.
- `travel_energy_arcs.csv`: directed travel time, distance, empty-trip energy,
  population-risk index, and loaded-curfew flag between nodes.

The hidden evaluator is not available in the public agent environment. Rebuild
your own feasibility checks from the public data and record them in
`submissions/solve_log.md`.

## Required Output

Create these artifacts under `submissions/`:

- `model.md`: your interpretation of the planning problem and the method you used.
- `solve.py`: a script that creates the submitted route plan from the public data.
- `solution.csv`: the route-event table described below.
- `solve_log.md`: commands run, solver or heuristic status, objective estimate,
  and feasibility checks.

The `solution.csv` file must have exactly these columns:

```csv
row_type,vehicle_id,sequence,node_id,clinic_id,facility_id,charger_id,charge_kwh
```

For `start` and `end` rows, fill `vehicle_id`, `sequence`, and `node_id`; leave
`clinic_id`, `facility_id`, `charger_id`, and `charge_kwh` blank.

For `pickup` rows, fill the clinic and its node. Leave facility, charger, and
charge fields blank.

For `unload` rows, fill the facility and its node. Leave clinic, charger, and
charge fields blank.

For `charge` rows, fill the charger, its node, and a positive `charge_kwh`.
Leave clinic and facility blank.
