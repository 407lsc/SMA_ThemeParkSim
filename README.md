# Theme Park ABM and DES Engine

<i>40.015 Simulation Modelling and Analysis</i><br>
<i>Singapore University of Technology and Design</i>

This project uses simulation and modelling techniques in Python to simulate theme park operations for studying how different management policies affect performance metrics such as waiting times, ride utilisation, and visitor satisfaction.

The model combines an Agent-Based Model (ABM) and Discrete Event Simulation (DES) to capture both visitor behaviour and ride operations. In the ABM, each visitor is represented as an agent with attributes such as group size, ride preferences, patience, and willingness to purchase priority access. Agents move through the park and choose attractions based on factors like wait times, distance, and personal preferences.

The DES component models the internal operation of rides, including visitor arrivals, queue selection (e.g., general, Fast Pass, or single rider), loading and unloading processes with priority handling, and ride cycle completion.

## Requirements

- Python 3.11 (tested to work on this version)
- pip

## Setup and Run using Virtual Environment

### macOS

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Documentation

### Overview of Files

| File | Purpose |
| --- | --- |
| `theme_park/main.py` | Internal module entrypoint. Creates and runs the app loop via `App().run()`. |
| `theme_park/config.py` | Centralised constants for screen size, panel size, colors, FPS, and default agent settings. |
| `theme_park/models.py` | Core domain models and state types (`Agent`, `Ride`, `NodeData`, `EdgeData`) plus queue-processing and agent movement logic. |
| `theme_park/simulation.py` | Main simulation engine (`ThemeParkSim`): builds the park graph, manages agents, advances time steps, and provides hover info/lookups. |
| `theme_park/controller.py` | Application controller (`App`): handles pygame events, UI interactions, simulation updates, and the render loop. |
| `theme_park/view.py` | Rendering and UI layer: draws map/nodes/agents/tooltips/HUD and defines the control panel widgets. |

### Quick Start Guide

| Goal | Main file(s) to edit |
| --- | --- |
| Change time-step simulation behavior (spawn logic, periodic policies) | `theme_park/simulation.py` (`execute_step`) |
| Change visitor movement/decision behavior | `theme_park/models.py` (`Agent` methods) |
| Change discrete event simulation (ride queue release/loading rules) | `theme_park/models.py` (`Ride` methods) |
| Add a new UI slider/button widget | `theme_park/view.py` (`ControlPanel.__init__`) |
| Wire slider/button events to model actions | `theme_park/controller.py` (`_handle_slider_event`, `_handle_button_event`) |
| Tune constants/default values | `theme_park/config.py` |

### config.py

Store app configuration settings or default values here as needed.

### models.py

Contains key definitions of object classes involved in simulations.

#### NodeData (Map Node Metadata)

Base class: `NodeData`

Purpose:
- Stores common metadata for all park nodes (rides and intersections).

Key attributes:
- `self.kind`: Node type (for example, `ride` or `intersection`).
- `self.name`: Display name used in labels/tooltips.
- `self.color`: Optional RGB color override for rendering.
- `self.radius`: Optional node marker radius override.
- `self.image_path`: Optional image path used for node icon rendering.

#### Ride (Attraction Node)

Base class: `Ride` (inherits from `NodeData`)

Purpose:
- Represents a ride node with queue structures and queue-processing logic for visitor flow.

Key attributes:
- `self.capacity`: Configured ride capacity metadata.
- `self.single_rider_queue`: Queue object for single-rider visitors.
- `self.normal_queue`: Queue object for regular visitors.
- `self.fastpass_queue`: Queue object for fast-pass visitors.
- `self._queued_agent_ids`: Internal tracking set used to prevent duplicate queue joins.
- `self._released_agent_ids`: Internal tracking set of agents released from queue processing.

Key methods:
- `join_queue(agent_id, queue_type)`: Adds an agent to the chosen queue and updates tracking sets.
- `remove_from_queue(source_queue, release_count)`: Removes up to `release_count` agents from the specified queue object and updates internal tracking sets.
- `process_queues(current_time_step)`: Advances queue processing and may release agents.
- `is_released_from_queue(agent_id)`: Called by agents to check whether the agent can leave the queue.

#### EdgeData (Map Path Metadata)

Base class: `EdgeData`

Purpose:
- Represents one graph edge between two nodes and tracks which agents are currently travelling on that edge.

Key attributes:
- `self.u`: First node ID of the edge.
- `self.v`: Second node ID of the edge.
- `self.length`: Geometric/route length of the edge.
- `self.agent_ids_on_edge`: Set of agent IDs currently on this edge.
- `self.crowd`: Derived crowd count (`len(self.agent_ids_on_edge)`).
- `self.key`: Canonical tuple key for consistent undirected edge lookup.

Key methods:
- `canonical_key(u, v)`: Returns a deterministic `(min_node, max_node)` style edge key.
- `enter_edge(agent_id)`: Records that an agent has entered this edge.
- `leave_edge(agent_id)`: Records that an agent has left this edge.
- `density_per_length(live_agents)`: Computes crowd density using edge length.

#### Agent (Theme Park Visitor)

Base class: `Agent`

Purpose:
- Represents a visitor entity that moves through the park, reacts to arrivals, and transitions between behavior states.

Key attributes:
- `self.speed`: Movement speed used to update edge traversal progress each step.
- `self.state`: Current agent state (`stationary`, `moving`, `queuing`, `on_ride`).
- `self.path`: Ordered list of node IDs that defines the current route.
- `self.current_index`: Index of the current node/edge position within `self.path`.
- `self.has_arrived`: Whether the agent reached the next node during the current step.

Key methods:
- `execute_step(dt, runtime)`: Main per-step state machine for behavior updates.
- `advance_along_edge(dt, edge_len)`: Moves the agent along an edge and updates `has_arrived`.
- `replan_path(new_path)`: Replaces the route and resets traversal progress.
- `_execute_moving(dt, runtime)`: Uses runtime `enter_edge(...)` / `leave_edge(...)` to keep edge occupancy tracking accurate.

### simulation.py

Main simulation model overseeing entire model-level operations, such as spawning new agents and storing data related to nodes & edges. It also uses an API to act as the bridge between agents and nodes/edges.

Base class: `ThemeParkSim`

Key attributes:
- `self.graph`: NetworkX graph containing park topology (nodes and edges).
- `self.positions`: Mapping of node ID to on-screen/map coordinates used for rendering and movement interpolation.
- `self.node_data`: Mapping of node ID to `NodeData` / `Ride` metadata used by agents on arrival.
- `self.edge_data`: Mapping of canonical edge key to `EdgeData` used for edge length and crowd tracking.
- `self.agents`: Active list of `Agent` objects stepped every simulation tick.
- `self.current_time_step`: Integer simulation tick counter used by ride queue processing and time-based logic.
- `self.elapsed_sim_time`: Accumulated simulation time in seconds.
- `self.agent_count`: Current number of live agents (kept in sync with `self.agents`).
- `self.rides`: Computed property returning all node IDs whose metadata is a `Ride`.

Key methods:
- `initialise()`: Add code here to run once at start of simulation or upon simulation reset.
- `execute_step(dt)`: Add code here to run every time step, for time-based behaviour e.g. spawning of agents over time.
- `_add_node()`: Method to add a new node and store it in attribute.
- `_build_park()`: Define the park layout (nodes, edges) here.
- `add_agent()`: Define what agent settings to use when spawning them here.
- `refresh_agent_position(agent)`: Updates an agent’s x-y position from its current path edge and progress, or snaps it to the destination node if no edge is active.

### controller.py

Application-level orchestration layer connecting UI actions to simulation behavior. This is where control-panel inputs are translated into simulation actions. Add new slider/button widgets in `view.py` (`ControlPanel`), then wire their behavior here.

Base class: `App`

Key methods:
- `reset_sim(agent_count=None)`: Rebuilds the simulation and re-syncs control-panel state. Use this when a parameter change requires a fresh initial condition.
- `_handle_slider_event(event)`: Central place to map each slider to model parameters. Add new `if/elif` branches here when introducing sliders (for example, spawn rate, queue policy thresholds, or ride capacities).
- `_handle_button_event(event)`: Central place to map button presses to model actions (for example, reset, inject agents, pause/resume, scenario switching).
- `handle_events()`: Event dispatcher that routes raw pygame/pygame_gui events to specialised handlers. Usually you extend helper handlers first, then keep dispatch logic clean.

### view.py

Contains rendering and UI widget definitions.

#### ParkView

- Draws the simulation scene each frame (map, nodes, agents, queues, tooltip, and HUD).

#### ControlPanel

This is where sidebar controls (sliders/buttons/labels) are created and laid out. Add or change controls here when introducing new experiment parameters.

Key methods:
- `__init__(ui_manager, sim)`: Defines control widgets and their layout positions.
- `sync_from_sim(sim, simulation_speed)`: Re-syncs widget values after reset/model replacement.

Adding new sliders/buttons:
1. Add a new slider/button widget in `ControlPanel.__init__(...)`.
2. Give it a clear label and keep `y` spacing consistent.
3. Handle its event in `App._handle_slider_event(...)` or `App._handle_button_event(...)` in `controller.py`.
4. If reset should preserve visible UI values, update `sync_from_sim(...)` accordingly.


