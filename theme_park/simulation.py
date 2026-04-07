from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

import networkx as nx

from .config import DEFAULT_AGENT_COLOR, DEFAULT_AGENT_SPEED
from .models import Agent, EdgeData, EdgeKey, NodeData, Ride, Vec2

class ThemeParkSim:
    def __init__(self, agent_count: int = 15) -> None:
        self.graph = nx.Graph()
        self.positions: Dict[str, Vec2] = {}
        self.node_data: Dict[str, NodeData] = {}
        self.edge_data: Dict[EdgeKey, EdgeData] = {}
        self.agents: List[Agent] = []
        self.current_time_step: int = 0
        self.elapsed_sim_time: float = 0.0

        self.agent_count = agent_count
        self.paused: bool = False

        self.minutes_per_step: float = 0.1  # 1 step = 1 minute (you can tune this)
        # Park time in minutes since midnight
        self.park_open_time = 9 * 60    # 09:00
        self.park_close_time = 21 * 60  # 21:00

        self.current_time_minutes: float = self.park_open_time
        self.initialise()

    @property
    def rides(self) -> list[str]:
        return [node for node, meta in self.node_data.items() if isinstance(meta, Ride)]

    def initialise(self) -> None:
        self._build_park()
        # self._spawn_initial_agents(self.agent_count)

    def execute_step(self, dt: float) -> None:
        _ = dt

        for meta in self.node_data.values():
            if isinstance(meta, Ride):
                meta.process_queues(self.current_time_minutes)

        # Example: spawn a new agent every 20 steps on average
        if random.random() > 0.95:
            self.add_agent()

    def _random_visitor_type(self) -> str:
        # You can tune these weights if you want a different population mix
        return random.choices(
            ["teenager", "adult", "elderly"],
            weights=[0.3, 0.5, 0.2],
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

        group_size = self._random_group_size()
        visitor_type = self._random_visitor_type()
        queue_type = self._random_queue_type(group_size)
        planned_departure_time = self._sample_departure_time(visitor_type)

        random_color = (
            random.randint(30, 240),
            random.randint(30, 240),
            random.randint(30, 240),
        )

        speed = DEFAULT_AGENT_SPEED
        if visitor_type == "teenager":
            speed *= 1.10
        elif visitor_type == "elderly":
            speed *= 0.80

        agent = Agent(
            agent_id=agent_id,
            speed=speed,
            color=random_color,
            path=path,
            current_index=0,
            progress=0.0,
            pos=pos,
            visitor_type=visitor_type,
            group_size=group_size,
            queue_type=queue_type,
            time_in_park=0.0,
            planned_departure_time=planned_departure_time,
            is_exiting=False,
            has_left_park=False,
        )

        self.agents.append(agent)
        self.refresh_agent_position(agent)
        self.agent_count = len(self.agents)
        return agent

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
        self._add_node("entrance", 120, 400, "intersection", "Entrance")
        self._add_node("n1", 300, 200, "intersection", "Crossroad A")
        self._add_node("n2", 300, 600, "intersection", "Crossroad B")
        self._add_node("ride1", 520, 180, "ride", "Roller Coaster", capacity=20, image_path="inputs/roller_coaster.png",ride_duration_steps=15,min_occupancy_ratio=0.80)
        self._add_node("ride2", 560, 410, "ride", "Ferris Wheel", capacity=32, image_path = "inputs/Ferris_wheel.png", ride_duration_steps=20,min_occupancy_ratio=0.80)
        self._add_node("ride3", 520, 650, "ride", "Log Flume", capacity=24, image_path = "inputs/Log_flume.png", ride_duration_steps=17, min_occupancy_ratio=0.80)
        self._add_node("n3", 760, 240, "intersection", "Path East")
        self._add_node("n4", 770, 560, "intersection", "Path East 2")

        edges = [
            ("entrance", "n1"),
            ("entrance", "n2"),
            ("n1", "ride1"),
            ("n1", "ride2"),
            ("n2", "ride2"),
            ("n2", "ride3"),
            ("ride1", "n3"),
            ("ride2", "n3"),
            ("ride2", "n4"),
            ("ride3", "n4")
        ]
        for u, v in edges:
            x1, y1 = self.positions[u]
            x2, y2 = self.positions[v]
            length = math.dist((x1, y1), (x2, y2))
            edge = EdgeData(u=u, v=v, length=length)
            self.edge_data[edge.key] = edge
            self.graph.add_edge(u, v, length=edge.length, crowd=edge.crowd)

    def random_path(self, start: str) -> list[str]:
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
        if not self.graph.has_edge(u, v):
            return
        key = EdgeData.canonical_key(u, v)
        edge = self.edge_data.get(key)
        if edge is None:
            return
        edge.enter_edge(agent_id)
        self.graph[u][v]["crowd"] = edge.crowd

    def leave_edge(self, u: str, v: str, agent_id: int) -> None:
        if not self.graph.has_edge(u, v):
            return
        key = EdgeData.canonical_key(u, v)
        edge = self.edge_data.get(key)
        if edge is None:
            return
        edge.leave_edge(agent_id)
        self.graph[u][v]["crowd"] = edge.crowd

    def edge_length(self, u: str, v: str) -> float:
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
        self.current_time_minutes += self.minutes_per_step

        self.elapsed_sim_time += dt
        self.execute_step(dt)

        for agent in list(self.agents):
            agent.execute_step(dt, self)

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

    
    
    
    
    
    
