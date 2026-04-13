from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

import networkx as nx

from .config import SIM_TIME_MINUTES, SIM_TIME_STEPS, PARK_OPEN_TIME, PARK_CLOSE_TIME
from .models import Agent, AdultAgent, ElderlyAgent, TeenagerAgent, GroupAgent, EdgeData, EdgeKey, NodeData, Ride, Vec2

class ThemeParkSim:
    def __init__(self, agent_count: int = 15) -> None:
        self.graph = nx.Graph()
        self.positions: Dict[str, Vec2] = {}
        self.node_data: Dict[str, NodeData] = {}
        self.edge_data: Dict[EdgeKey, EdgeData] = {}
        self.agents: List[Agent] = []
        self.current_time_step: int = 0

        self.agent_count = agent_count
        self.paused: bool = False

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
        self.initialise()

    @property
    def rides(self) -> list[str]:
        return [node for node, meta in self.node_data.items() if isinstance(meta, Ride)]

    @property
    def elapsed_sim_time(self) -> float:
        """Elapsed simulated park time in minutes since opening."""
        return self.current_time_step * self.minutes_per_step

    @property
    def current_time_minutes(self) -> float:
        """Current simulated clock time in minutes since midnight."""
        return self.park_open_time + self.elapsed_sim_time

    def initialise(self) -> None:
        self._build_park()
        # self._spawn_initial_agents(self.agent_count)

    def execute_step(self, dt: float) -> None:
        _ = dt

        for meta in self.node_data.values():
            if isinstance(meta, Ride):
                meta.process_queues(self.current_time_minutes, self.park_is_closing)

        # Do not admit new agents after closing starts
        if not self.park_is_closing:
            if random.random() > 0.95:
                self.add_agent()

    def _random_visitor_type(self) -> str:
        # You can tune these weights if you want a different population mix
        return random.choices(
            ["teenager", "adult", "elderly", "group"],
            weights=[0.25, 0.40, 0.20, 0.15],
            k=1
        )[0]

    def _random_queue_type(self,group_size:int) -> str:
        # Only true solo visitors can become single riders.
        if group_size == 1:
            return random.choices(
                ["fastpass", "normal", "single_rider"],
                weights=[0.20, 0.60, 0.20],
                k=1,
            )[0]

        return random.choices(
            ["fastpass", "normal"],
            weights=[0.20, 0.80],
            k=1,
        )[0]

    # Defines if visitor is individual or group
    ## Called in add_agent() when spawning in a new agent
    def _random_group_size(self) -> int:
        # 70% chance individual, 30% chance group of size 2-7
        if random.random() < 0.7:
            return 1
        return random.randint(2, 7)

    def add_agent(self) -> Agent:
        agent_id = len(self.agents)
        start = "entrance"
        path = self.random_path(start)
        pos = self.positions[start]

        visitor_type = self._random_visitor_type()

        # Use your existing group size logic
        group_size = self._random_group_size()

        # If visitor type is group, enforce group_size >= 2
        if visitor_type == "group" and group_size == 1:
            group_size = random.randint(2, 7)

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
        if agent in self.agents:
            self.agents.remove(agent)

    def _add_node(
        self,
        node_id: str,
        x: float,
        y: float,
        kind: str,
        name: str,
        capacity: int = 0,
        color: Optional[Tuple[int, int, int]] = None,
        radius: Optional[int] = None,
        image_path: Optional[str] = None,
        ride_duration_steps: int = 60,
        min_occupancy_ratio: float = 0.80,
    ) -> None:
        self.graph.add_node(node_id)
        self.positions[node_id] = (x, y)

        if kind == "ride":
            node = Ride(
                name=name,
                capacity=capacity,
                color=color,
                radius=radius,
                image_path=image_path,
                ride_duration_steps =ride_duration_steps,
                min_occupancy_ratio=min_occupancy_ratio,
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
        self._add_node("ride1", 874, 381, "ride", "Log Flume", capacity=24, image_path="inputs/Log_flume.png",ride_duration_steps=17,min_occupancy_ratio=0.80)
        self._add_node("ride2", 496, 373, "ride", "Ferris Wheel", capacity=32, image_path = "inputs/Ferris_wheel.png", ride_duration_steps=20,min_occupancy_ratio=0.80)
        self._add_node("ride3", 562, 662, "ride", "Roller Coaster", capacity=20, image_path = "inputs/roller_coaster.png", ride_duration_steps=15, min_occupancy_ratio=0.80)
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
    def random_path(self, start: str) -> List[str]:
        # Provide route planning for agent decisions/replanning.
        rides = self.rides
        target = random.choice(rides)
        if start == target:
            target = random.choice([r for r in rides if r != start])
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

        self.current_time_step += 1

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

    def node_at_position(self, mouse_pos: Tuple[int, int], radius: int = 18) -> Optional[str]:
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
        total_minutes = int(self.current_time_minutes)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{hours:02d}:{minutes:02d}"
    
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

        # Optional clamp so nobody leaves instantly or stays absurdly long
        return max(20.0, min(sampled, 360.0))
    
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
    
    
    
