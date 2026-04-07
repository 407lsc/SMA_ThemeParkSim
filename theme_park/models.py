from __future__ import annotations

import random
from queue import Empty, Queue

from typing import Dict, List, Literal, Optional, Protocol, Tuple

Vec2 = Tuple[float, float]
EdgeKey = Tuple[str, str]
NodeId = str
AgentId = int
RGBColor = Tuple[int, int, int]
Path = List[NodeId]
AgentState = Literal["stationary", "moving", "queuing", "on_ride", "exited"]


class AgentRuntime(Protocol):
    """Runtime services exposed by the simulation to each agent behavior."""

    def edge_length(self, u: NodeId, v: NodeId) -> float:
        ...

    def enter_edge(self, u: NodeId, v: NodeId, agent_id: AgentId) -> None:
        ...

    def leave_edge(self, u: NodeId, v: NodeId, agent_id: AgentId) -> None:
        ...

    def random_path(self, start: NodeId) -> Path:
        ...

    def node_data_for(self, node_id: NodeId) -> "NodeData":
        ...

    def refresh_agent_position(self, agent: "Agent") -> None:
        ...

    def current_time(self) -> float:
        """Return current simulation time in seconds."""
        ...

    def shortest_path(self, start: NodeId, end: NodeId) -> Path:
        """Return shortest path between two nodes."""
        ...


class NodeData:
    def __init__(
        self,
        kind: str,
        name: str,
        color: Optional[RGBColor] = None,
        radius: Optional[int] = None,
        image_path: Optional[str] = None,
    ) -> None:
        self.kind = kind
        self.name = name
        self.color = color
        self.radius = radius
        self.image_path = image_path


class Ride(NodeData):
    def __init__(
        self,
        name: str,
        capacity: int = 0,
        color: Optional[RGBColor] = None,
        radius: Optional[int] = None,
        image_path: Optional[str] = None,
    ) -> None:
        super().__init__(
            kind="ride",
            name=name,
            color=color,
            radius=radius,
            image_path=image_path,
        )

        self.capacity = capacity

        self.single_rider_queue: Queue[AgentId] = Queue()
        self.normal_queue: Queue[AgentId] = Queue()
        self.fastpass_queue: Queue[AgentId] = Queue()

        self._queued_agent_ids: set[AgentId] = set()
        self._released_agent_ids: set[AgentId] = set()

    def is_ride(self) -> bool:
        return True

    @property
    def total_queue_len(self) -> int:
        return (
            self.single_rider_queue.qsize()
            + self.normal_queue.qsize()
            + self.fastpass_queue.qsize()
        )

    def _waiting_count(self) -> int:
        return self.single_rider_queue.qsize() + self.normal_queue.qsize() + self.fastpass_queue.qsize()

    def remove_from_queue(self, source_queue: Queue[AgentId], release_count: int = 1) -> List[AgentId]:
        """Release up to release_count agents from a specific queue object."""
        if release_count <= 0:
            return []

        released_ids: List[AgentId] = []
        for _ in range(release_count):
            released_agent = self._pop_next(source_queue)
            if released_agent is None:
                break
            self._queued_agent_ids.discard(released_agent)
            self._released_agent_ids.add(released_agent)
            released_ids.append(released_agent)

        return released_ids

    def join_queue(self, agent_id: AgentId, queue_type: str = "normal") -> bool:
        if agent_id in self._queued_agent_ids:
            return True

        if queue_type == "single_rider":
            target_queue = self.single_rider_queue
        elif queue_type == "fastpass":
            target_queue = self.fastpass_queue
        else:
            target_queue = self.normal_queue

        target_queue.put(agent_id)
        self._queued_agent_ids.add(agent_id)
        return True

    @staticmethod
    def _pop_next(queue: Queue[AgentId]) -> Optional[AgentId]:
        try:
            return queue.get_nowait()
        except Empty:
            return None

    def process_queues(self, current_time_step: int) -> None:
        """Advance this ride's queue process (pending implementation)."""
        _ = current_time_step

        # Proof of concept: randomly release one agent from a random non-empty queue.
        non_empty_queues: List[Queue[AgentId]] = []
        if not self.single_rider_queue.empty():
            non_empty_queues.append(self.single_rider_queue)
        if not self.normal_queue.empty():
            non_empty_queues.append(self.normal_queue)
        if not self.fastpass_queue.empty():
            non_empty_queues.append(self.fastpass_queue)

        if not non_empty_queues:
            return

        if random.random() < 0.01:
            selected_queue = random.choice(non_empty_queues)
            self.remove_from_queue(source_queue=selected_queue, release_count=1)

    def is_released_from_queue(self, agent_id: AgentId) -> bool:
        if agent_id not in self._released_agent_ids:
            return False
        self._released_agent_ids.remove(agent_id)
        return True


class EdgeData:
    def __init__(self, u: str, v: str, length: float) -> None:
        self.u = u
        self.v = v
        self.length = length
        self.agent_ids_on_edge: set[AgentId] = set()

    @classmethod
    def canonical_key(cls, u: str, v: str) -> EdgeKey:
        return (u, v) if u <= v else (v, u)

    @property
    def key(self) -> EdgeKey:
        return self.canonical_key(self.u, self.v)

    @property
    def crowd(self) -> int:
        return len(self.agent_ids_on_edge)

    def enter_edge(self, agent_id: AgentId) -> None:
        self.agent_ids_on_edge.add(agent_id)

    def leave_edge(self, agent_id: AgentId) -> None:
        self.agent_ids_on_edge.discard(agent_id)

    def density_per_length(self, live_agents: int) -> float:
        if self.length <= 0:
            return 0.0
        return float(live_agents) / self.length


class Agent:
    """Base visitor entity with movement and arrival behavior hooks."""

    def __init__(
        self,
        agent_id: int,
        speed: float,
        color: RGBColor,
        path: Path,
        state: AgentState = "moving",
        current_index: int = 0,
        progress: float = 0.0,
        pos: Vec2 = (0.0, 0.0),
        completed_loops: int = 0,
        previous_destinations: Optional[List[NodeId]] = None,
        stay_end_time: float = float('inf'),
        pending_leave: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.speed = speed
        self.color = color
        self.path = path
        self.state = state
        self.current_index = current_index
        self.progress = progress
        self.pos = pos
        self.completed_loops = completed_loops
        self.previous_destinations = previous_destinations if previous_destinations is not None else []
        self.has_arrived = False
        self._occupied_edge: Optional[EdgeKey] = None
        self.stay_end_time = stay_end_time
        self.pending_leave = pending_leave

    def _leave_current_edge(self, runtime: AgentRuntime) -> None:
        if self._occupied_edge is None:
            return
        u, v = self._occupied_edge
        runtime.leave_edge(u, v, self.agent_id)
        self._occupied_edge = None

    def _current_node_id(self) -> NodeId:
        if not self.path:
            return "entrance"
        idx = min(self.current_index, len(self.path) - 1)
        return self.path[idx]

    def current_edge(self) -> Optional[EdgeKey]:
        if self.current_index >= len(self.path) - 1:
            return None
        return self.path[self.current_index], self.path[self.current_index + 1]

    def advance_along_edge(self, dt: float, edge_len: float) -> None:
        self.has_arrived = False
        if edge_len <= 0:
            return
        self.progress += (self.speed * dt) / edge_len
        if self.progress >= 1.0:
            self.current_index += 1
            self.progress = 0.0
            self.has_arrived = True

    def replan_path(self, new_path: Path) -> None:
        self.path = new_path
        self.current_index = 0
        self.progress = 0.0

    def is_time_to_leave(self, current_time: float) -> bool:
        return current_time >= self.stay_end_time

    def execute_step(self, dt: float, runtime: AgentRuntime) -> None:
        if self.state == "stationary":
            self._execute_stationary(runtime)
        elif self.state == "queuing":
            self._execute_queuing(runtime)
        elif self.state == "on_ride":
            self._execute_on_ride(runtime)
        elif self.state != "exited":
            self._execute_moving(dt, runtime)

        if not self.pending_leave and self.is_time_to_leave(runtime.current_time()):
            self.pending_leave = True

    def _execute_stationary(self, runtime: AgentRuntime) -> None:
        self._leave_current_edge(runtime)
        start = self._current_node_id()
        if self.pending_leave:
            try:
                new_path = runtime.shortest_path(start, "entrance")
            except Exception:
                new_path = [start, "entrance"]
            self.replan_path(new_path)
        else:
            self.replan_path(runtime.random_path(start))
        self.state = "moving"
        runtime.refresh_agent_position(self)

    def _execute_moving(self, dt: float, runtime: AgentRuntime) -> None:
        edge = self.current_edge()
        if edge is None:
            self._leave_current_edge(runtime)
            self.completed_loops += 1
            start = self._current_node_id()
            if self.pending_leave:
                try:
                    new_path = runtime.shortest_path(start, "entrance")
                except Exception:
                    new_path = [start, "entrance"]
                self.replan_path(new_path)
            else:
                self.replan_path(runtime.random_path(start))
            runtime.refresh_agent_position(self)
            return

        u, v = edge
        edge_len = runtime.edge_length(u, v)
        if self._occupied_edge != edge:
            self._leave_current_edge(runtime)
            runtime.enter_edge(u, v, self.agent_id)
            self._occupied_edge = edge

        self.advance_along_edge(dt, edge_len)

        if self.has_arrived:
            self._leave_current_edge(runtime)
            arrived = self.path[self.current_index]
            node = runtime.node_data_for(arrived)

            if arrived == "entrance" and self.pending_leave:
                self.state = "exited"
                runtime.refresh_agent_position(self)
                return

            if isinstance(node, Ride):
                self.previous_destinations.append(arrived)
                should_queue = node.join_queue(self.agent_id, queue_type="normal")
            else:
                should_queue = False

            if should_queue:
                self.state = "queuing"
                runtime.refresh_agent_position(self)
                return

        runtime.refresh_agent_position(self)

    def _execute_queuing(self, runtime: AgentRuntime) -> None:
        self._leave_current_edge(runtime)
        node = runtime.node_data_for(self._current_node_id())
        if not isinstance(node, Ride):
            self.state = "moving"
            runtime.refresh_agent_position(self)
            return

        if node.is_released_from_queue(self.agent_id):
            start = self._current_node_id()
            if self.pending_leave:
                try:
                    new_path = runtime.shortest_path(start, "entrance")
                except Exception:
                    new_path = [start, "entrance"]
                self.replan_path(new_path)
            else:
                self.replan_path(runtime.random_path(start))
            self.state = "moving"

        runtime.refresh_agent_position(self)

    def _execute_on_ride(self, runtime: AgentRuntime) -> None:
        self._leave_current_edge(runtime)
        start = self._current_node_id()
        if self.pending_leave:
            try:
                new_path = runtime.shortest_path(start, "entrance")
            except Exception:
                new_path = [start, "entrance"]
            self.replan_path(new_path)
            self.state = "moving"
        else:
            self.state = "stationary"
        runtime.refresh_agent_position(self)