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
        self.exited_agent_count = 0

        self.initialise()

    
    
    ### UPDATED ### find agent near mouse position
    def agent_at_position(self, mouse_pos: Tuple[int, int], radius: int = 8) -> Optional[Agent]:
        mx, my = mouse_pos
        for agent in self.agents:
            if agent.state not in ("queuing", "on_ride"):  # only moving/stationary agents are drawn with circles
                ax, ay = agent.pos
                if (mx - ax) ** 2 + (my - ay) ** 2 <= radius ** 2:
                    return agent
        return None
    
    ### UPDATED ### get agent info for tooltip
    def agent_hovered_info(self, agent: Agent) -> str:
        remaining = max(0.0, agent.stay_end_time - self.elapsed_sim_time)
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        return f"Agent {agent.agent_id}\nTime left: {hours}h {minutes}m"

    # computed property
    @property
    def rides(self) -> List[str]:
        return [node for node, meta in self.node_data.items() if isinstance(meta, Ride)]

    # Functions

    """Add code here to run once at the start of the simulation or upon reset, for example to build the park graph and spawn initial agents."""
    def initialise(self) -> None:
        self._build_park()
        # self._spawn_initial_agents(self.agent_count)   ### ORIGINAL: no initial agents

    def execute_step(self, dt: float) -> None:
        """Per-step simulation hook for custom time-based behavior."""
        _ = dt

        for meta in self.node_data.values():
            if isinstance(meta, Ride):
                meta.process_queues(self.current_time_step)

        # Example: spawn a new agent every 20 steps on average
        if random.random() > 0.95:
            self.add_agent()

    ### UPDATED ### added stay_end_time assignment
    def add_agent(self) -> Agent:
        """Spawn one agent and append it to the active agent list."""
        agent_id = len(self.agents)
        start = "entrance"
        path = self.random_path(start)
        pos = self.positions[start]

        # Currently it randomises agent color on spawn.
        random_color = (
            random.randint(30, 240),
            random.randint(30, 240),
            random.randint(30, 240),
        )

        ### UPDATED ### random stay duration between 1 and 11 hours (converted to seconds)
        stay_hours = random.uniform(1.0, 11.0)
        stay_end_time = self.elapsed_sim_time + stay_hours * 3600.0

        agent = Agent(
            agent_id=agent_id,
            speed=DEFAULT_AGENT_SPEED,
            color=random_color,
            path=path,
            current_index=0,
            progress=0.0,
            pos=pos,
            stay_end_time=stay_end_time,
            pending_leave=False,
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
    ) -> None:
        self.graph.add_node(node_id)
        self.positions[node_id] = (x, y)
        if kind == "ride":
            node = Ride(
                name=name,
                capacity=capacity,
                color=color,
                radius=radius,
                image_path=image_path
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
        self._add_node("ride1", 520, 180, "ride", "Roller Coaster", capacity=20, image_path="inputs/coaster.png")
        self._add_node("ride2", 560, 410, "ride", "Ferris Wheel", capacity=32)
        self._add_node("ride3", 520, 650, "ride", "Log Flume", capacity=24)
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


    # Agent runtime API (consumed by Agent in models.py via AgentRuntime):
    # - random_path
    # - refresh_agent_position
    # - enter_edge
    # - leave_edge
    # - edge_length
    # - node_data_for
    ### UPDATED ### also current_time and shortest_path
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

    ### UPDATED ### new method for shortest path queries
    def shortest_path(self, start: str, end: str) -> List[str]:
        return nx.shortest_path(self.graph, start, end, weight="length")

    ### UPDATED ### new method to return current simulation time
    def current_time(self) -> float:
        return self.elapsed_sim_time

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
        # Expose node metadata so agents can react to arrivals (e.g., rides).
        return self.node_data[node_id]

    # End Agent runtime API

    # Other public methods consumed by the view or for internal logic:


    ### UPDATED ###
    def get_exited_agent_count(self) -> int:
        return self.exited_agent_count

    ### UPDATED ### step() now removes exited agents and counts them
    def step(self, dt: float) -> None:
        self.current_time_step += 1
        self.elapsed_sim_time += dt
        self.execute_step(dt)

        agents_to_remove = []
        for agent in self.agents:
            agent.execute_step(dt, self)
            if agent.state == "exited":
                agents_to_remove.append(agent)

        for agent in agents_to_remove:
            self.agents.remove(agent)
            self.exited_agent_count += 1   ### UPDATED ###
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
        return "\n".join(lines)