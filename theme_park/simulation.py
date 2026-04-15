from __future__ import annotations

import math
import random
import matplotlib.pyplot as plt
from itertools import product
from typing import Dict, List, Optional, Tuple

import networkx as nx

from .config import (
    SIM_TIME_MINUTES,
    SIM_TIME_STEPS,
    PARK_OPEN_TIME,
    PARK_CLOSE_TIME,
    RANDOM_SEED,
    AGENT_SPAWN_PROB,
    GROUP_SPAWN_PROB,
    INDIVIDUAL_VISITOR_TYPE_WEIGHTS,
    GROUP_SIZE_MIN,
    GROUP_SIZE_MAX,
    GLOBAL_FASTPASS_WEIGHT,
    GLOBAL_NORMAL_WEIGHT,
    GLOBAL_SINGLE_RIDER_WEIGHT,
    METRICS_COLLECT_INTERVAL,
    CAPACITY_TUNING_STEP,
    PASS_TYPE_TUNING_STEP,
)
from .models import Agent, AdultAgent, ElderlyAgent, TeenagerAgent, GroupAgent, EdgeData, EdgeKey, NodeData, Ride, Vec2

class ThemeParkSim:
    def __init__(self) -> None:
        # Make all simulation randomness reproducible and controlled by config.
        random.seed(RANDOM_SEED)

        self.graph = nx.Graph()
        self.positions: Dict[str, Vec2] = {}
        self.node_data: Dict[str, NodeData] = {}
        self.edge_data: Dict[EdgeKey, EdgeData] = {}
        self.agents: List[Agent] = []
        self.current_time_step: int = 0
        self._elapsed_sim_minutes: float = 0.0

        self.agent_count = 0
        self.paused: bool = False
        self.enable_final_output_metrics: bool = True

        if SIM_TIME_STEPS <= 0:
            raise ValueError("SIM_TIME_STEPS must be greater than 0")
        if SIM_TIME_MINUTES <= 0:
            raise ValueError("SIM_TIME_MINUTES must be greater than 0")

        # Define simulation time mapping as:
        # SIM_TIME_STEPS steps = SIM_TIME_MINUTES simulated minutes.
        self.minutes_per_step: float = SIM_TIME_MINUTES / SIM_TIME_STEPS
        # Park time in minutes since midnight
        self.park_open_time = PARK_OPEN_TIME
        self.park_close_time = PARK_CLOSE_TIME
        self.park_is_closing = False

        self.total_entered = 0
        self.total_exited = 0

        self.group_spawn_prob = min(max(GROUP_SPAWN_PROB, 0.0), 1.0)
        self.agent_spawn_prob_per_sim_second = min(max(AGENT_SPAWN_PROB, 0.0), 1.0)
        self.individual_type_weights = INDIVIDUAL_VISITOR_TYPE_WEIGHTS
        if GROUP_SIZE_MIN < 2 or GROUP_SIZE_MAX < GROUP_SIZE_MIN:
            raise ValueError("GROUP_SIZE_MIN/GROUP_SIZE_MAX configuration is invalid")
        self.group_size_min = GROUP_SIZE_MIN
        self.group_size_max = GROUP_SIZE_MAX

        # Queue mix is driven by global queue targets from config.
        # If config is invalid, fall back to defaults in code.
        configured_ok = self.set_queue_ratio_weights(
            GLOBAL_FASTPASS_WEIGHT,
            GLOBAL_NORMAL_WEIGHT,
            GLOBAL_SINGLE_RIDER_WEIGHT,
        )
        if not configured_ok:
            self.set_queue_ratio_weights(0.20, 0.60, 0.20)

        # Metrics collection
        self.metrics_collect_interval_s = METRICS_COLLECT_INTERVAL
        self._metrics_minutes_since_last_collect: float = 0.0
        self.metrics_timesteps: List[int] = []
        self.metrics_avg_visitor_density: List[float] = []
        self.metrics_avg_num_rides_visited: List[float] = []
        self.metrics_avg_queue_time: List[float] = []
        self.metrics_total_revenue: List[float] = []
        self.metrics_total_operation_cost: List[float] = []
        self.metrics_total_profit: List[float] = []
        self._metrics_departed_agents_count: int = 0
        self._metrics_departed_total_rides_completed: float = 0.0
        self._metrics_departed_total_queue_time: float = 0.0

        self.initialise()

    @property
    def rides(self) -> list[str]:
        return [node for node, meta in self.node_data.items() if isinstance(meta, Ride)]

    @property
    def elapsed_sim_time(self) -> float:
        """Elapsed simulated park time in minutes since opening."""
        return self._elapsed_sim_minutes

    @property
    def current_time_minutes(self) -> float:
        """Current simulated clock time in minutes since midnight."""
        return self.park_open_time + self.elapsed_sim_time

    def initialise(self) -> None:
        self._build_park()

    def execute_step(self, dt: float) -> None:
        dt_sim_seconds = max(dt, 0.0)

        for meta in self.node_data.values():
            if isinstance(meta, Ride):
                meta.process_queues(self.current_time_minutes, self.park_is_closing)

        # Do not admit new agents after closing starts
        if not self.park_is_closing:
            # Convert per-sim-second spawn chance to this step's duration.
            spawn_prob_this_step = 1.0 - (1.0 - self.agent_spawn_prob_per_sim_second) ** dt_sim_seconds
            if random.random() < spawn_prob_this_step:
                self.add_agent()

    def _random_visitor_type(self) -> str:
        # Choose individual visitor type only (group handled separately).
        return random.choices(
            list(self.individual_type_weights.keys()),
            weights=list(self.individual_type_weights.values()),
            k=1
        )[0]

    def _random_queue_type(self, group_size: int) -> str:
        if group_size == 1: # If it is not a group (single visitor)
            return random.choices(
                ["fastpass", "normal", "single_rider"],
                weights=[
                    self.single_fastpass_weight,
                    self.single_normal_weight,
                    self.single_rider_weight,
                ],
                k=1,
            )[0]

        return random.choices(
            ["fastpass", "normal"],
            weights=[self.group_fastpass_weight, self.group_normal_weight],
            k=1,
        )[0]

    def _recompute_group_queue_weights(self) -> None:
        # Preserve fastpass share approximately at global level (by people)
        # while single-rider remains available only to solo visitors.
        expected_group_size = (self.group_size_min + self.group_size_max) / 2
        denom = self.group_spawn_prob * expected_group_size
        if denom > 0:
            total_people_per_spawn = (1.0 - self.group_spawn_prob) + denom
            group_fastpass_weight = (
                self.single_fastpass_weight * total_people_per_spawn
                - (1.0 - self.group_spawn_prob) * self.single_fastpass_weight
            ) / denom
        else:
            group_fastpass_weight = self.single_fastpass_weight

        group_fastpass_weight = min(max(group_fastpass_weight, 0.0), 1.0)
        self.group_fastpass_weight = group_fastpass_weight
        self.group_normal_weight = 1.0 - group_fastpass_weight

    def set_queue_ratio_weights(self, fastpass: float, normal: float, single_rider: float) -> bool:
        # Valid iff fastpass is capped, others are non-negative as required,
        # normal > 0, and total sums to 1.
        weight_sum = fastpass + normal + single_rider
        is_valid = (
            fastpass >= 0.0
            and fastpass <= 0.5
            and normal > 0.0
            and single_rider >= 0.0
            and single_rider <= 0.5
            and abs(weight_sum - 1.0) < 1e-9
        )
        if not is_valid:
            return False

        self.single_fastpass_weight = fastpass
        self.single_normal_weight = normal
        self.single_rider_weight = single_rider
        self._recompute_group_queue_weights()
        return True

    # Defines if visitor is individual or group
    ## Called in add_agent() when spawning in a new agent
    def _random_group_size(self) -> int:
        return random.randint(self.group_size_min, self.group_size_max)

    def add_agent(self) -> Agent:
        agent_id = len(self.agents)
        start = "entrance"
        path = self.random_path(start)
        pos = self.positions[start]

        # 1) First choose whether this spawn is a group or individual.
        if random.random() < self.group_spawn_prob:
            visitor_type = "group"
            group_size = self._random_group_size()
        else:
            # 2) Individual spawn: choose adult/teenager/elderly.
            visitor_type = self._random_visitor_type()
            group_size = 1

        queue_type = self._random_queue_type(group_size)
        planned_departure_time = self._sample_departure_time(visitor_type)

        random_color = (
            random.randint(30, 240),
            random.randint(30, 240),
            random.randint(30, 240),
        )

        shared_kwargs = dict(
            agent_id=agent_id,
            color=random_color,
            path=path,
            group_size=group_size,
            queue_type=queue_type,
            planned_departure_time=planned_departure_time,
            current_index=0,
            progress=0.0,
            pos=pos,
            time_in_park=0.0,
            is_exiting=False,
            has_left_park=False,
        )
        if visitor_type == "teenager":
            agent = TeenagerAgent(**shared_kwargs)
        elif visitor_type == "elderly":
            agent = ElderlyAgent(**shared_kwargs)
        elif visitor_type == "group":
            agent = GroupAgent(**shared_kwargs)
        else:
            agent = AdultAgent(**shared_kwargs)

        self.total_entered += agent.group_size

        self.agents.append(agent)
        self.refresh_agent_position(agent)
        self.agent_count = len(self.agents)
        return agent

    def remove_agent(self, agent: Agent) -> None:
        self.total_exited += agent.group_size

        # Finalize per-agent metrics when agent leaves the park.
        self._metrics_departed_agents_count += 1
        self._metrics_departed_total_rides_completed += float(agent.rides_completed)
        self._metrics_departed_total_queue_time += float(agent.queue_time_minutes)

        if agent in self.agents:
            self.agents.remove(agent)

    def _current_avg_visitor_density(self) -> float:
        if not self.edge_data:
            return 0.0
        densities: list[float] = []
        for edge in self.edge_data.values():
            if edge.length <= 0:
                densities.append(0.0)
            else:
                densities.append(edge.crowd / edge.length)
        return sum(densities) / len(densities)

    def _collect_metrics_snapshot(self) -> None:
        self.metrics_timesteps.append(self.current_time_step)
        self.metrics_avg_visitor_density.append(self._current_avg_visitor_density())

        if self._metrics_departed_agents_count > 0:
            avg_rides = self._metrics_departed_total_rides_completed / self._metrics_departed_agents_count
            avg_queue_time = self._metrics_departed_total_queue_time / self._metrics_departed_agents_count
        else:
            avg_rides = 0.0
            avg_queue_time = 0.0

        self.metrics_avg_num_rides_visited.append(avg_rides)
        self.metrics_avg_queue_time.append(avg_queue_time)

        total_revenue = 0.0
        total_operation_cost = 0.0
        for meta in self.node_data.values():
            if not isinstance(meta, Ride):
                continue
            total_revenue += meta.total_revenue
            total_operation_cost += meta.total_operation_cost

        self.metrics_total_revenue.append(total_revenue)
        self.metrics_total_operation_cost.append(total_operation_cost)
        self.metrics_total_profit.append(total_revenue - total_operation_cost)

    def _add_node(
        self,
        node_id: str,
        x: float,
        y: float,
        kind: str,
        name: str,
        max_capacity: int = 30,
        capacity: int = 0,
        color: Optional[Tuple[int, int, int]] = None,
        radius: Optional[int] = None,
        image_path: Optional[str] = None,
        ride_duration_steps: int = 60,
        min_occupancy_ratio: float = 0.80,
        operation_cost_base_per_cycle: Optional[float] = None,
        operation_cost_per_capacity_unit: Optional[float] = None,
        fastpass_price_per_ride: Optional[float] = None,
        standard_price_per_ride: Optional[float] = None,
    ) -> None:
        self.graph.add_node(node_id)
        self.positions[node_id] = (x, y)

        if kind == "ride":
            ride_financial_kwargs: dict[str, float] = {}
            if operation_cost_base_per_cycle is not None:
                ride_financial_kwargs["operation_cost_base_per_cycle"] = operation_cost_base_per_cycle
            if operation_cost_per_capacity_unit is not None:
                ride_financial_kwargs["operation_cost_per_capacity_unit"] = operation_cost_per_capacity_unit
            if fastpass_price_per_ride is not None:
                ride_financial_kwargs["fastpass_price_per_ride"] = fastpass_price_per_ride
            if standard_price_per_ride is not None:
                ride_financial_kwargs["standard_price_per_ride"] = standard_price_per_ride

            node = Ride(
                name=name,
                max_capacity=max_capacity,
                capacity=capacity,
                color=color,
                radius=radius,
                image_path=image_path,
                ride_duration_steps=ride_duration_steps,
                min_occupancy_ratio=min_occupancy_ratio,
                **ride_financial_kwargs,
            )
        else:
            node = NodeData(
                kind=kind,
                name=name,
                color=color,
                radius=radius,
                image_path=image_path,
            )
        self.node_data[node_id] = node

    def _build_park(self) -> None:
        self._add_node("entrance", 120, 360, "intersection", "")
        self._add_node("n1", 312, 490, "intersection", "")
        self._add_node("n2", 227, 550, "intersection", "")
        self._add_node("n3", 484, 724, "intersection", "")
        self._add_node("n4", 744, 539, "intersection", "")
        self._add_node("n5", 598, 445, "intersection", "")
        self._add_node("ride1", 874, 381, "ride", "Log Flume", max_capacity=30, capacity=30, image_path="inputs/Log_flume.png",ride_duration_steps=3,min_occupancy_ratio=0.80)
        self._add_node("ride2", 496, 373, "ride", "Ferris Wheel", max_capacity=100, capacity=75, image_path = "inputs/Ferris_wheel.png", ride_duration_steps=5,min_occupancy_ratio=0.80)
        self._add_node("ride3", 562, 662, "ride", "Roller Coaster", max_capacity=30, capacity=30, image_path = "inputs/roller_coaster.png", ride_duration_steps=3, min_occupancy_ratio=0.80)
        self._add_node("n6", 854, 271, "intersection", "")
        self._add_node("n7", 932, 324, "intersection", "")

        edges = [
            ("entrance", "n1"),
            ("n1", "n2"),
            ("n1", "ride2"),
            ("n2", "n3"),
            ("n3", "ride3"),
            ("n4", "ride3"),
            ("n4", "n5"),
            ("n5", "ride2"),
            ("n5", "n6"),
            ("n6", "n7"),
            ("n7", "ride1")
        ]
        for u, v in edges:
            x1, y1 = self.positions[u]
            x2, y2 = self.positions[v]
            length = math.dist((x1, y1), (x2, y2))
            edge = EdgeData(u=u, v=v, length=length)
            self.edge_data[edge.key] = edge
            self.graph.add_edge(u, v, length=edge.length, crowd=edge.crowd)


    # Agent runtime API (consumed by Agent in models.py via AgentRuntime):
    # - random_path
    # - refresh_agent_position
    # - enter_edge
    # - leave_edge
    # - edge_length
    # - node_data_for
    def random_path(self, start: str, ride_preferences: Optional[Dict[str, float]] = None) -> List[str]:
        rides = self.rides

        if ride_preferences is not None:
            # Filter preferences to only rides that exist in the current park
            valid_prefs = {r: ride_preferences[r] for r in rides if r in ride_preferences}

            if valid_prefs:
                # Fall back to uniform if all weights sum to zero
                ride_ids = list(valid_prefs.keys())
                weights = list(valid_prefs.values())
                target = random.choices(ride_ids, weights=weights, k=1)[0]
            else:
                target = random.choice(rides)
        else:
            target = random.choice(rides)

        # Avoid picking the ride the agent is already at
        if start == target and len(rides) > 1:
            remaining = [r for r in rides if r != start]
            if ride_preferences is not None:
                valid_prefs = {r: ride_preferences[r] for r in remaining if r in ride_preferences}
                if valid_prefs:
                    ride_ids = list(valid_prefs.keys())
                    weights = list(valid_prefs.values())
                    target = random.choices(ride_ids, weights=weights, k=1)[0]
                else:
                    target = random.choice(remaining)
            else:
                target = random.choice(remaining)

        try:
            return nx.shortest_path(self.graph, start, target, weight="length")
        except nx.NetworkXNoPath:
            return [start]

    def _spawn_initial_agents(self, count: int) -> None:
        for i in range(count):
            agent = self.add_agent()
            agent.agent_id = i

    def refresh_agent_position(self, agent: Agent) -> None:
        # Convert traversal state (edge + progress) into renderable coordinates.
        edge = agent.current_edge()
        if edge is None:
            agent.pos = self.positions[agent.path[-1]]
            return
        u, v = edge
        x1, y1 = self.positions[u]
        x2, y2 = self.positions[v]
        agent.pos = (
            x1 + (x2 - x1) * agent.progress,
            y1 + (y2 - y1) * agent.progress,
        )

    def enter_edge(self, u: str, v: str, agent_id: int) -> None:
        # Track edge occupancy when an agent starts traversing an edge.
        if not self.graph.has_edge(u, v):
            return
        key = EdgeData.canonical_key(u, v)
        edge = self.edge_data.get(key)
        if edge is None:
            return
        edge.enter_edge(agent_id)
        self.graph[u][v]["crowd"] = edge.crowd

    def leave_edge(self, u: str, v: str, agent_id: int) -> None:
        # Track edge occupancy when an agent leaves an edge.
        if not self.graph.has_edge(u, v):
            return
        key = EdgeData.canonical_key(u, v)
        edge = self.edge_data.get(key)
        if edge is None:
            return
        edge.leave_edge(agent_id)
        self.graph[u][v]["crowd"] = edge.crowd

    def edge_length(self, u: str, v: str) -> float:
        # Return edge travel length for movement updates.
        edge = self.edge_data.get(EdgeData.canonical_key(u, v))
        if edge is None:
            return 0.0
        return edge.length

    def node_data_for(self, node_id: str) -> NodeData:
        return self.node_data[node_id]

    def step(self, dt: float) -> None:
        if self.paused:
            return

        # dt is simulated seconds advanced in this tick.
        elapsed_minutes = dt / 60.0
        self._elapsed_sim_minutes += elapsed_minutes
        self.current_time_step = int(self._elapsed_sim_minutes / self.minutes_per_step)

        if self.current_time_minutes >= self.park_close_time:
            self._begin_park_closing()

        self.execute_step(dt)

        for agent in list(self.agents):
            agent.execute_step(dt, self)

        if self.park_is_closing:
            for agent in self.agents:
                if agent.state == "queuing":
                    agent.force_exit_from_queue(self)

        # Remove agents who have left the park
        self.agents = [agent for agent in self.agents if not agent.has_left_park]
        self.agent_count = len(self.agents)

        # Auto-stop once closing has started and everyone has exited.
        if self.park_is_closing and self.agent_count == 0:
            self.paused = True
            if self.enable_final_output_metrics:
                self.output_metrics()

        self._metrics_minutes_since_last_collect += elapsed_minutes
        while self._metrics_minutes_since_last_collect >= self.metrics_collect_interval_s:
            self._collect_metrics_snapshot()
            self._metrics_minutes_since_last_collect -= self.metrics_collect_interval_s

    def node_at_position(self, mouse_pos: Tuple[int, int], radius: int = 80) -> Optional[str]:
        mx, my = mouse_pos
        for node_id, (x, y) in self.positions.items():
            if (mx - x) ** 2 + (my - y) ** 2 <= radius ** 2:
                return node_id
        return None

    def hovered_info(self, node_id: str) -> str:
        meta = self.node_data[node_id]
        lines = [f"{meta.name}", f"Type: {meta.kind}"]
        if isinstance(meta, Ride):
            lines.append(f"Capacity: {meta.capacity}")
            lines.append(f"Queue: {meta.total_queue_len}")
            lines.append(f"On Ride: {meta.riders_on_ride_count}")
            lines.append(f"Cycle Length: {meta.ride_duration_minutes} minutes")
            lines.append("Status: Running" if meta.is_running else "Status: Idle")
        return "\n".join(lines)

    @staticmethod
    def _format_hhmm(total_minutes: float) -> str:
        minute_value = int(total_minutes)
        hours = (minute_value // 60) % 24
        minutes = minute_value % 60
        return f"{hours:02d}:{minutes:02d}"

    def agent_at_position(self, mouse_pos: Tuple[int, int], radius: int = 14) -> Optional[Agent]:
        mx, my = mouse_pos
        radius_sq = radius * radius
        for agent in reversed(self.agents):
            if agent.state in ("queuing", "on_ride"):
                continue
            ax, ay = agent.pos
            if (mx - ax) ** 2 + (my - ay) ** 2 <= radius_sq:
                return agent
        return None

    def hovered_agent_info(self, agent: Agent) -> str:
        entry_time_minutes = self.current_time_minutes - agent.time_in_park
        planned_departure_minutes = entry_time_minutes + agent.planned_departure_time

        lines = [
            f"Agent {agent.agent_id}",
            f"Visitor Type: {agent.visitor_type}",
            f"Planned Departure: {self._format_hhmm(planned_departure_minutes)}",
        ]
        if agent.group_size > 1:
            lines.append(f"Group Size: {agent.group_size}")
        return "\n".join(lines)
    
    def get_time_str(self) -> str:
        # Round to nearest second to avoid floating-point floor jitter.
        total_seconds = int(round(self.current_time_minutes * 60))
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def _sample_departure_time(self, visitor_type: str) -> float:
        """Return minutes until departure using an exponential distribution."""
        # Mean stay durations in minutes
        if visitor_type == "teenager":
            mean_minutes = 180.0
        elif visitor_type == "elderly":
            mean_minutes = 120.0        
        elif visitor_type == "group":
            mean_minutes = 130.0
        else:
            mean_minutes = 150.0

        # random.expovariate expects rate = 1 / mean
        sampled = random.expovariate(1.0 / mean_minutes)

        # Optional clamp so nobody leaves instantly or stays past park closing
        max_stay_time = self.park_close_time - self.current_time_minutes
        return max(20.0, min(sampled, max_stay_time))
    
    def path_to_entrance(self, start: str) -> list[str]:
        target = "entrance"
        if start == target:
            return [start]
        try:
            return nx.shortest_path(self.graph, start, target, weight="length")
        except nx.NetworkXNoPath:
            return [start]

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    def close_queues(self) -> list[int]:
        removed_ids = []

        for queue in [self.fastpass_queue, self.normal_queue, self.single_rider_queue]:
            while not queue.empty():
                entry = self._pop_next(queue)
                if entry is None:
                    break

                agent_id = entry[0]

                self._queued_agent_ids.discard(agent_id)
                self._boarded_agent_ids.discard(agent_id)
                self._released_agent_ids.discard(agent_id)

                removed_ids.append(agent_id)

        return removed_ids

    def _begin_park_closing(self) -> None:
        if self.park_is_closing:
            return

        self.park_is_closing = True

        queued_agent_ids: set[int] = set()

        for meta in self.node_data.values():
            if isinstance(meta, Ride):
                queued_agent_ids.update(meta.close_queues())

        for agent in self.agents:
            # Everyone still waiting in queues must leave immediately
            if agent.agent_id in queued_agent_ids:
                agent.force_exit_from_queue(self)

            # Optional: also send walkers/stationary agents home at closing
            elif agent.state in ("moving", "stationary"):
                agent.force_exit_from_queue(self)
    
    def update_edge_lengths(self) -> None:
        for (u, v), edge in self.edge_data.items():
            x1, y1 = self.positions[u]
            x2, y2 = self.positions[v]
            edge.length = math.dist((x1, y1), (x2, y2))

            if self.graph.has_edge(u, v):
                self.graph[u][v]["length"] = edge.length

    def output_metrics(self) -> None:

        # Stack key simulation and financial trends.
        fig, axs = plt.subplots(4, 1, figsize=(12, 11))
        axs[0].plot(self.metrics_timesteps, self.metrics_avg_visitor_density, label="Average Visitor Density")
        axs[0].set_xlabel("Time Step")
        axs[0].set_ylabel("Visitor Density (people per unit length)")
        axs[0].set_title("Average Visitor Density Over Time in Simulation")
        axs[0].legend()
        axs[0].grid(True)
        axs[1].plot(self.metrics_timesteps, self.metrics_avg_num_rides_visited, label="Average Number of Rides Visited", color='orange')
        axs[1].set_xlabel("Time Step")
        axs[1].set_ylabel("No. of Rides")
        axs[1].set_title("Average Number of Rides Visited Over Time in Simulation")
        axs[1].legend()
        axs[1].grid(True)
        axs[2].plot(self.metrics_timesteps, self.metrics_avg_queue_time, label="Average Queue Time (minutes)", color='green')
        axs[2].set_xlabel("Time Step")
        axs[2].set_ylabel("Time (minutes)")
        axs[2].set_title("Average Queue Time Over Time in Simulation")
        axs[2].legend()
        axs[2].grid(True)
        axs[3].plot(self.metrics_timesteps, self.metrics_total_revenue, label="Cumulative Ride Revenue", color='tab:blue')
        axs[3].plot(self.metrics_timesteps, self.metrics_total_operation_cost, label="Cumulative Ride Operating Cost", color='tab:red')
        axs[3].plot(self.metrics_timesteps, self.metrics_total_profit, label="Cumulative Ride Profit", color='tab:green')
        axs[3].set_xlabel("Time Step")
        axs[3].set_ylabel("Amount")
        axs[3].set_title("Ride Financial Metrics Over Time")
        axs[3].legend()
        axs[3].grid(True)
        plt.tight_layout()
        plt.show()
        plt.close()

        total_revenue = 0.0
        total_operation_cost = 0.0
        total_cycles = 0
        print("Ride Financial Summary")
        print("-" * 80)
        print(
            f"{'Ride':18s} {'Cycles':>8s} {'Revenue':>12s} {'Op Cost':>12s} {'Profit':>12s} {'Fastpass':>10s} {'Standard':>10s}"
        )
        for node_id, meta in self.node_data.items():
            if not isinstance(meta, Ride):
                continue

            total_revenue += meta.total_revenue
            total_operation_cost += meta.total_operation_cost
            total_cycles += meta.total_cycles_started
            print(
                f"{node_id:18s} {meta.total_cycles_started:8d} {meta.total_revenue:12.2f} "
                f"{meta.total_operation_cost:12.2f} {meta.total_profit:12.2f} "
                f"{meta.total_fastpass_customers:10d} {meta.total_standard_customers:10d}"
            )

        print("-" * 80)
        print(
            f"{'TOTAL':18s} {total_cycles:8d} {total_revenue:12.2f} {total_operation_cost:12.2f} {(total_revenue - total_operation_cost):12.2f}"
        )

    # ==================
    # Parameter tuning
    # ==================
    @staticmethod
    def _capacity_values(max_capacity: int, step: int) -> list[int]:
        step = max(1, int(step))
        max_capacity = int(max_capacity)
        if max_capacity <= 0:
            return []

        values = list(range(step, max_capacity + 1, step))
        if not values:
            values = [max_capacity]
        elif values[-1] != max_capacity:
            values.append(max_capacity)

        # Unique + sorted
        return sorted(set(values))

    def capacity_tuning_options(self, step: Optional[int] = None) -> dict[str, list[int]]:
        """Return possible capacity values for each ride node_id.

        Values are generated from the tuning step up to each ride's max_capacity,
        always including max_capacity.
        """
        step_value = CAPACITY_TUNING_STEP if step is None else step
        options: dict[str, list[int]] = {}
        for node_id, meta in self.node_data.items():
            if not isinstance(meta, Ride):
                continue
            options[node_id] = self._capacity_values(meta.max_capacity, int(step_value))
        return options

    @staticmethod
    def pass_weight_tuning_options(
        step: Optional[float] = None,
        fixed_single_rider: Optional[float] = None,
    ) -> list[tuple[float, float, float]]:
        """Return pass-weight combinations for tuning.

        `single_rider` is kept fixed (defaults to GLOBAL_SINGLE_RIDER_WEIGHT).
        `fastpass` is swept in increments of `step`, and `normal` is computed as
        `1 - fastpass - single_rider`.

        Constraints:
        - 0 <= fastpass <= 0.5
        - 0 <= single_rider <= 0.5
        - normal > 0
        - fastpass + normal + single_rider == 1

        Notes:
        - This does not require `single_rider` to be a multiple of `step`.
        """
        step_value = PASS_TYPE_TUNING_STEP if step is None else float(step)
        if step_value <= 0:
            raise ValueError("PASS_TYPE_TUNING_STEP must be > 0")

        single_rider = GLOBAL_SINGLE_RIDER_WEIGHT if fixed_single_rider is None else float(fixed_single_rider)
        if single_rider < 0.0 or single_rider > 0.5:
            raise ValueError("Fixed single rider weight must be within [0.0, 0.5]")

        # fastpass must leave strictly-positive normal.
        max_fastpass = min(0.5, 1.0 - single_rider - 1e-12)
        if max_fastpass < 0.0:
            return []

        n_steps = int(math.floor((max_fastpass + 1e-12) / step_value))
        combos: list[tuple[float, float, float]] = []
        for i in range(n_steps + 1):
            fastpass = i * step_value
            if fastpass > 0.5 + 1e-9:
                continue
            normal = 1.0 - single_rider - fastpass
            if normal <= 0.0:
                continue

            # Round for stable printing/serialization and to avoid tiny drift.
            fastpass_r = round(fastpass, 10)
            normal_r = round(normal, 10)
            single_rider_r = round(single_rider, 10)

            if abs((fastpass_r + normal_r + single_rider_r) - 1.0) > 1e-8:
                continue
            combos.append((fastpass_r, normal_r, single_rider_r))

        return combos

    def iter_parameter_tuning_configs(
        self,
        capacity_step: Optional[int] = None,
        pass_step: Optional[float] = None,
    ):
        """Yield (ride_capacities, pass_weights) for the full parameter grid.

        This is a lazy generator to avoid building huge in-memory matrices.
        - ride_capacities: dict[node_id, capacity]
        - pass_weights: (fastpass, normal, single_rider)
        """
        capacity_options = self.capacity_tuning_options(capacity_step)
        pass_options = self.pass_weight_tuning_options(pass_step)

        ride_ids = list(capacity_options.keys())
        if not ride_ids:
            return

        capacity_lists = [capacity_options[r] for r in ride_ids]
        for capacity_tuple in product(*capacity_lists):
            ride_capacities = dict(zip(ride_ids, capacity_tuple))
            for pass_weights in pass_options:
                yield ride_capacities, pass_weights
    
    
