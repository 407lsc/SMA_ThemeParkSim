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

        # Park hours: 10:00 to 21:00 (11 hours)
        self.PARK_OPEN_HOUR = 10.0
        self.PARK_CLOSE_HOUR = 21.0
        self.DAY_DURATION_SEC = (self.PARK_CLOSE_HOUR - self.PARK_OPEN_HOUR) * 3600.0
        self.park_closed = False
        self.waiting_for_exit = False

        self.initialise()

    # ---------- Park time utilities ----------
    def get_park_time_seconds(self) -> float:
        """Return seconds since 10:00 (0 to DAY_DURATION_SEC)."""
        return self.elapsed_sim_time % self.DAY_DURATION_SEC

    def get_park_time_str(self) -> str:
        """Return formatted HH:MM:SS for park time."""
        total_sec = self.get_park_time_seconds()
        hours = int(total_sec // 3600) + int(self.PARK_OPEN_HOUR)
        minutes = int((total_sec % 3600) // 60)
        seconds = int(total_sec % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def set_park_time(self, hours_offset: float) -> None:
        """Set park time by offset (0 to 11 hours). Used by time slider."""
        # If we are in exit phase and user drags to a time before closing, force reset
        if self.waiting_for_exit and hours_offset < (self.PARK_CLOSE_HOUR - self.PARK_OPEN_HOUR):
            self._reset_park_day()
            # After reset, set the new time
            target_seconds = hours_offset * 3600.0
            self.elapsed_sim_time = target_seconds
            return

        target_seconds = hours_offset * 3600.0

        # If target is at or beyond closing time, trigger closure
        if target_seconds >= self.DAY_DURATION_SEC - 1e-6:
            if not self.park_closed:
                self._close_park()
            return

        # Otherwise, adjust time normally
        current_mod = self.elapsed_sim_time % self.DAY_DURATION_SEC
        self.elapsed_sim_time += (target_seconds - current_mod)

        # If park was closed but we jumped back to open hours, reset
        if self.park_closed and not self.waiting_for_exit:
            self.park_closed = False

    # ---------- Agent hover ----------
    def agent_at_position(self, mouse_pos: Tuple[int, int], radius: int = 8) -> Optional[Agent]:
        mx, my = mouse_pos
        for agent in self.agents:
            if agent.state not in ("queuing", "on_ride"):
                ax, ay = agent.pos
                if (mx - ax) ** 2 + (my - ay) ** 2 <= radius ** 2:
                    return agent
        return None

    def agent_hovered_info(self, agent: Agent) -> str:
        remaining = max(0.0, agent.stay_end_time - self.elapsed_sim_time)
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        return f"Agent {agent.agent_id}\nTime left: {hours}h {minutes}m"

    # ---------- Properties ----------
    @property
    def rides(self) -> List[str]:
        return [node for node, meta in self.node_data.items() if isinstance(meta, Ride)]

    # ---------- Initialisation ----------
    def initialise(self) -> None:
        self._build_park()
        # No initial agents – they spawn randomly over time

    # ---------- Simulation steps ----------
    def execute_step(self, dt: float) -> None:
        """Per-step simulation hook."""
        _ = dt
        if not self.park_closed:
            for meta in self.node_data.values():
                if isinstance(meta, Ride):
                    meta.process_queues(self.current_time_step)
            # Spawn new agents only when park is open
            if random.random() > 0.95:
                self.add_agent()

    def add_agent(self) -> Optional[Agent]:
        """Spawn one agent. Returns None if park is closed."""
        if self.park_closed:
            return None
        agent_id = len(self.agents)
        start = "entrance"
        path = self.random_path(start)
        pos = self.positions[start]

        random_color = (
            random.randint(30, 240),
            random.randint(30, 240),
            random.randint(30, 240),
        )

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

    def step(self, dt: float) -> None:
        if self.park_closed and self.waiting_for_exit:
            # During exit phase: update agents (they move to entrance) but no time advance
            agents_to_remove = []
            for agent in self.agents:
                agent.execute_step(dt, self)
                if agent.state == "exited":
                    agents_to_remove.append(agent)
            for agent in agents_to_remove:
                self.agents.remove(agent)
                self.exited_agent_count += 1
                self.agent_count = len(self.agents)

            if len(self.agents) == 0:
                self._reset_park_day()
            return

        # Normal operation (park open)
        self.current_time_step += 1
        self.elapsed_sim_time += dt
        self.execute_step(dt)

        # Check for natural closure (21:00)
        if self.get_park_time_seconds() >= self.DAY_DURATION_SEC - 1e-6:
            self._close_park()
            return

        # Update agents and remove exited ones
        agents_to_remove = []
        for agent in self.agents:
            agent.execute_step(dt, self)
            if agent.state == "exited":
                agents_to_remove.append(agent)
        for agent in agents_to_remove:
            self.agents.remove(agent)
            self.exited_agent_count += 1
            self.agent_count = len(self.agents)

    ### FIX ### improved closure that forces all agents to exit
    def _close_park(self) -> None:
        if self.park_closed:
            return
        self.park_closed = True
        self.waiting_for_exit = True

        # Force every agent to leave immediately
        for agent in self.agents:
            agent.pending_leave = True
            # Override state to moving and set path to entrance
            if agent.state in ("queuing", "on_ride", "stationary"):
                agent.state = "moving"
            start = agent._current_node_id()
            try:
                new_path = self.shortest_path(start, "entrance")
            except:
                new_path = [start, "entrance"]
            agent.replan_path(new_path)

        # Release all queued agents from every ride and mark them as released
        for meta in self.node_data.values():
            if isinstance(meta, Ride):
                for q in (meta.single_rider_queue, meta.normal_queue, meta.fastpass_queue):
                    while not q.empty():
                        try:
                            aid = q.get_nowait()
                            meta._queued_agent_ids.discard(aid)
                            meta._released_agent_ids.add(aid)
                        except:
                            break

    def _reset_park_day(self) -> None:
        """Reset park to a new day at 10:00."""
        self.park_closed = False
        self.waiting_for_exit = False
        self.agents.clear()
        self.agent_count = 0
        self.elapsed_sim_time = 0.0
        self.current_time_step = 0
        # Keep exited_agent_count cumulative (do not reset)

    # ---------- Park graph building ----------
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
            node = Ride(name=name, capacity=capacity, color=color, radius=radius, image_path=image_path)
        else:
            node = NodeData(kind=kind, name=name, color=color, radius=radius, image_path=image_path)
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
            ("entrance", "n1"), ("entrance", "n2"),
            ("n1", "ride1"), ("n1", "ride2"),
            ("n2", "ride2"), ("n2", "ride3"),
            ("ride1", "n3"), ("ride2", "n3"),
            ("ride2", "n4"), ("ride3", "n4")
        ]
        for u, v in edges:
            x1, y1 = self.positions[u]
            x2, y2 = self.positions[v]
            length = math.dist((x1, y1), (x2, y2))
            edge = EdgeData(u=u, v=v, length=length)
            self.edge_data[edge.key] = edge
            self.graph.add_edge(u, v, length=edge.length, crowd=edge.crowd)

    # ---------- Agent runtime API ----------
    def random_path(self, start: str) -> List[str]:
        rides = self.rides
        target = random.choice(rides)
        if start == target:
            target = random.choice([r for r in rides if r != start])
        try:
            return nx.shortest_path(self.graph, start, target, weight="length")
        except nx.NetworkXNoPath:
            return [start]

    def shortest_path(self, start: str, end: str) -> List[str]:
        return nx.shortest_path(self.graph, start, end, weight="length")

    def current_time(self) -> float:
        return self.elapsed_sim_time

    def refresh_agent_position(self, agent: Agent) -> None:
        edge = agent.current_edge()
        if edge is None:
            agent.pos = self.positions[agent.path[-1]]
            return
        u, v = edge
        x1, y1 = self.positions[u]
        x2, y2 = self.positions[v]
        agent.pos = (x1 + (x2 - x1) * agent.progress, y1 + (y2 - y1) * agent.progress)

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

    def get_exited_agent_count(self) -> int:
        return self.exited_agent_count

    # ---------- Mouse / hover ----------
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