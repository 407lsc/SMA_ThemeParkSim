from __future__ import annotations

import random
from queue import Empty, Queue
from pathlib import Path 
from typing import Dict, List, Literal, Optional, Protocol, Tuple
from .config import DEFAULT_AGENT_SPEED
import pygame

Vec2 = Tuple[float, float]
EdgeKey = Tuple[str, str]
NodeId = str
AgentId = int
RGBColor = Tuple[int, int, int]
Route = list[NodeId]
AgentState = Literal["stationary", "moving", "queuing", "on_ride"]


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
        self.radius = radius or 12
        self.image_path = image_path

        # store loaded image
        self.image: Optional[pygame.Surface] = None

        if image_path is not None:
            try:
                project_root = Path(__file__).resolve().parent.parent
                candidate = Path(image_path)
                full_path = candidate if candidate.is_absolute() else (project_root / candidate)

                print(f"Loading image for {name}: {full_path}")

                if not full_path.exists():
                    print(f"[ERROR] Image file not found: {full_path}")
                else:
                    img = pygame.image.load(str(full_path)).convert_alpha()

                    # 🔥 Bigger sizing logic
                    if kind == "ride":
                        size = 120   # 👈 adjust this (80–120 recommended)
                    else:
                        size = 40   # smaller for intersections

                    self.image = pygame.transform.smoothscale(img, (size, size))

            except Exception as e:
                raise e
        


class Ride(NodeData):
    def __init__(
        self,
        name: str,
        capacity: int = 0,
        color: Optional[RGBColor] = None,
        radius: Optional[int] = None,
        image_path: Optional[str] = None,
        ride_duration_steps: int = 60,
        min_occupancy_ratio: float = 0.80,
    ) -> None:
        super().__init__(
            kind="ride",
            name=name,
            color=color,
            radius=radius,
            image_path=image_path,
        )

        self.capacity = capacity
        self.ride_duration_minutes = ride_duration_steps
        self.min_occupancy_ratio = min_occupancy_ratio

        # Each queue entry is (agent_id, group_size, queue_type)
        self.single_rider_queue: Queue[tuple[AgentId, int, str]] = Queue()
        self.normal_queue: Queue[tuple[AgentId, int, str]] = Queue()
        self.fastpass_queue: Queue[tuple[AgentId, int, str]] = Queue()

        self._queued_agent_ids: set[AgentId] = set()
        self._boarded_agent_ids: set[AgentId] = set()
        self._released_agent_ids: set[AgentId] = set()

        self._on_ride_agents: list[tuple[AgentId, int, str]] = []
        self._ride_end_time: Optional[int] = None
        self.ride_duration_minutes = ride_duration_steps

    def is_ride(self) -> bool:
        return True

    @property
    def total_queue_len(self) -> int:
        return (
            self._queue_people_count(self.single_rider_queue)
            + self._queue_people_count(self.normal_queue)
            + self._queue_people_count(self.fastpass_queue)
        )

    @property
    def riders_on_ride_count(self) -> int:
        return sum(group_size for _, group_size, _ in self._on_ride_agents)

    @property
    def is_running(self) -> bool:
        return self._ride_end_time is not None

    @property
    def minimum_required_riders(self) -> int:
        if self.capacity <= 0:
            return 0
        return max(1, int(self.capacity * self.min_occupancy_ratio + 0.999999))

    @staticmethod
    def _queue_people_count(queue: Queue[tuple[AgentId, int, str]]) -> int:
        return sum(group_size for _, group_size, _ in list(queue.queue))

    @staticmethod
    def _pop_next(queue: Queue[tuple[AgentId, int, str]]) -> Optional[tuple[AgentId, int, str]]:
        try:
            return queue.get_nowait()
        except Empty:
            return None

    @staticmethod
    def _peek_next(queue: Queue[tuple[AgentId, int, str]]) -> Optional[tuple[AgentId, int, str]]:
        if queue.empty():
            return None
        return queue.queue[0]

    def join_queue(
        self,
        agent_id: AgentId,
        group_size: int = 1,
        queue_type: str = "normal",
    ) -> bool:
        if agent_id in self._queued_agent_ids or agent_id in self._boarded_agent_ids:
            return True

        if queue_type == "single_rider" and group_size != 1:
            queue_type = "normal"

        entry = (agent_id, group_size, queue_type)

        if queue_type == "single_rider":
            self.single_rider_queue.put(entry)
        elif queue_type == "fastpass":
            self.fastpass_queue.put(entry)
        else:
            self.normal_queue.put(entry)

        self._queued_agent_ids.add(agent_id)
        return True

    def remove_from_queue(
        self,
        source_queue: Queue[tuple[AgentId, int, str]],
        release_capacity: int,
    ) -> list[tuple[AgentId, int, str]]:
        boarded_groups: list[tuple[AgentId, int, str]] = []
        remaining_capacity = release_capacity

        while not source_queue.empty():
            next_group = self._peek_next(source_queue)
            if next_group is None:
                break

            _agent_id, group_size, _queue_type = next_group
            if group_size > remaining_capacity:
                break

            boarded = self._pop_next(source_queue)
            if boarded is None:
                break

            boarded_agent_id, boarded_group_size, boarded_queue_type = boarded
            self._queued_agent_ids.discard(boarded_agent_id)
            self._boarded_agent_ids.add(boarded_agent_id)
            boarded_groups.append((boarded_agent_id, boarded_group_size, boarded_queue_type))
            remaining_capacity -= boarded_group_size

            if remaining_capacity <= 0:
                break

        return boarded_groups

    def _restore_to_original_queue(
        self,
        entries: list[tuple[AgentId, int, str]],
    ) -> None:
        for agent_id, group_size, queue_type in reversed(entries):
            entry = (agent_id, group_size, queue_type)
            if queue_type == "single_rider":
                self.single_rider_queue.queue.appendleft(entry)
            elif queue_type == "fastpass":
                self.fastpass_queue.queue.appendleft(entry)
            else:
                self.normal_queue.queue.appendleft(entry)
            self._queued_agent_ids.add(agent_id)

    def process_queues(self, current_time_minutes: float) -> None:
        # If ride is currently running, nobody can board
        if self._ride_end_time is not None:
            if current_time_minutes < self._ride_end_time:
                return

            # Ride finishes now
            for agent_id, _group_size, _queue_type in self._on_ride_agents:
                self._boarded_agent_ids.discard(agent_id)
                self._released_agent_ids.add(agent_id)

            self._on_ride_agents.clear()
            self._ride_end_time = None

        remaining_capacity = self.capacity
        boarded_groups: list[tuple[AgentId, int, str]] = []

        # Step 1: board as many fastpass groups as possible
        new_boarded = self.remove_from_queue(self.fastpass_queue, remaining_capacity)
        if new_boarded:
            boarded_groups.extend(new_boarded)
            remaining_capacity -= sum(group_size for _, group_size, _ in new_boarded)

        # Step 2: board as many normal groups as possible
        new_boarded = self.remove_from_queue(self.normal_queue, remaining_capacity)
        if new_boarded:
            boarded_groups.extend(new_boarded)
            remaining_capacity -= sum(group_size for _, group_size, _ in new_boarded)

        # Step 3: if leftover seats remain, use single riders to fill them
        if remaining_capacity > 0:
            new_boarded = self.remove_from_queue(self.single_rider_queue, remaining_capacity)
            if new_boarded:
                boarded_groups.extend(new_boarded)
                remaining_capacity -= sum(group_size for _, group_size, _ in new_boarded)

        boarded_people = sum(group_size for _, group_size, _ in boarded_groups)

        # Only start ride if minimum occupancy threshold is reached
        if boarded_people >= self.minimum_required_riders:
            self._on_ride_agents = boarded_groups
            self._ride_end_time = current_time_minutes + self.ride_duration_minutes
        else:
            # Not enough people: restore everyone to original queues
            for agent_id, _group_size, _queue_type in boarded_groups:
                self._boarded_agent_ids.discard(agent_id)

            self._restore_to_original_queue(boarded_groups)

    def is_boarded_from_queue(self, agent_id: AgentId) -> bool:
        return agent_id in self._boarded_agent_ids

    def is_released_from_queue(self, agent_id: AgentId) -> bool:
        if agent_id not in self._released_agent_ids:
            return False
        self._released_agent_ids.remove(agent_id)
        return True


    #Need to add discrete event simulation code here

# Feel free to inherit from or modify the above Ride class to implement different ride behaviors.
class MyRide(Ride):
    pass


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
    
    # Feel free to define additional methods or properties


class Agent:
    """Base visitor entity with movement and arrival behavior hooks.

    Subclasses can override arrival or movement logic without changing
    simulation orchestration code.
    """

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
        previous_destinations: Optional[list[NodeId]] = None,
        visitor_type: str = "adult",
        group_size: int = 1,
        queue_type: str = "normal",
        time_in_park: float = 0.0,
        planned_departure_time: float = 180.0,
        is_exiting: bool = False,
        has_left_park: bool = False,
        image_path: Optional[str] = None, # for image icon
    ) -> None:
        self.agent_id = agent_id
        self.speed = speed
        self.color = color
        self.path = path
        self.state = state
        self.image_path = image_path

        # Safety checks for visitor & queue types
        valid_visitor_types = {"teenager", "adult", "elderly", "group"}
        if visitor_type not in valid_visitor_types:
            raise ValueError(
                f"visitor_type must be one of {valid_visitor_types}, got {visitor_type!r}"
            )

        valid_queue_types = {"normal", "fastpass", "single_rider"}
        if queue_type not in valid_queue_types:
            raise ValueError(
                f"queue_type must be one of {valid_queue_types}, got {queue_type!r}"
            )

        if group_size < 1:
            raise ValueError(f"group_size must be at least 1, got {group_size}")

        self.visitor_type = visitor_type
        self.group_size = group_size
        self.queue_type = queue_type

        self.current_index = current_index
        self.progress = progress
        self.pos = pos
        self.completed_loops = completed_loops
        self.previous_destinations = (
            previous_destinations if previous_destinations is not None else []
        )

        self.time_in_park = time_in_park
        self.planned_departure_time = planned_departure_time
        self.is_exiting = is_exiting
        self.has_left_park = has_left_park

        self.has_arrived = False
        self._occupied_edge: Optional[EdgeKey] = None

    @property
    def is_group(self) -> bool:
        return self.group_size > 1

    @property
    def category_label(self) -> str:
        base = self.visitor_type
        if self.queue_type == "fastpass":
            base = f"{base}_fastpass"
        if self.is_group:
            base = f"{base}_group"
        return base

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

    def execute_step(self, dt: float, runtime: AgentRuntime) -> None:
        """Execute one simulation tick using behavior specific to current state."""
        self.time_in_park += runtime.minutes_per_step

        if (
            not self.is_exiting
            and self.time_in_park >= self.planned_departure_time
        ):
            self._start_exit(runtime)

        if self.state == "stationary":
            self._execute_stationary(runtime)
            return
        if self.state == "queuing":
            self._execute_queuing(runtime)
            return
        if self.state == "on_ride":
            self._execute_on_ride(runtime)
            return
        self._execute_moving(dt, runtime)

    def _execute_stationary(self, runtime: AgentRuntime) -> None:
        """Stationary agents choose a new route and start moving."""
        self._leave_current_edge(runtime)

        start = self._current_node_id()
        if self.is_exiting:
            self.replan_path(runtime.path_to_entrance(start))
        else:
            self.replan_path(runtime.random_path(start))

        self.state = "moving"
        runtime.refresh_agent_position(self)

    def _execute_moving(self, dt: float, runtime: AgentRuntime) -> None:
        """Moving agents traverse edges and react to node arrivals."""
        edge = self.current_edge()
        if edge is None:
            self._leave_current_edge(runtime)

            current_node = self._current_node_id()

            if self.is_exiting and current_node == "entrance":
                self.has_left_park = True
                runtime.refresh_agent_position(self)
                return

            self.completed_loops += 1

            if self.is_exiting:
                self.replan_path(runtime.path_to_entrance(current_node))
            else:
                self.replan_path(runtime.random_path(current_node))

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

            if self.is_exiting and arrived == "entrance":
                self.has_left_park = True
                runtime.refresh_agent_position(self)
                return

            if isinstance(node, Ride) and not self.is_exiting:
                self.previous_destinations.append(arrived)
                should_queue = node.join_queue(
                    self.agent_id,
                    group_size=self.group_size,
                    queue_type=self.queue_type,
                )
            else:
                should_queue = False

            if should_queue:
                self.state = "queuing"
                runtime.refresh_agent_position(self)
                return

        runtime.refresh_agent_position(self)

    def _execute_queuing(self, runtime: AgentRuntime) -> None:
        """Queued agents wait until they are boarded onto the ride."""
        self._leave_current_edge(runtime)
        node = runtime.node_data_for(self._current_node_id())

        if not isinstance(node, Ride):
            self.state = "moving"
            runtime.refresh_agent_position(self)
            return

        if node.is_boarded_from_queue(self.agent_id):
            self.state = "on_ride"

        runtime.refresh_agent_position(self)

    def _execute_on_ride(self, runtime: AgentRuntime) -> None:
        """Agents remain on the ride until the ride cycle completes."""
        self._leave_current_edge(runtime)
        node = runtime.node_data_for(self._current_node_id())

        if not isinstance(node, Ride):
            self.state = "moving"
            runtime.refresh_agent_position(self)
            return

        if node.is_released_from_queue(self.agent_id):
            start = self._current_node_id()
            if self.is_exiting:
                self.replan_path(runtime.path_to_entrance(start))
            else:
                self.replan_path(runtime.random_path(start))
            self.state = "moving"

        runtime.refresh_agent_position(self)

    def _start_exit(self, runtime: AgentRuntime) -> None:
        self._leave_current_edge(runtime)
        self.is_exiting = True

        current_node = self._current_node_id()
        exit_path = runtime.path_to_entrance(current_node)
        self.replan_path(exit_path)
        self.state = "moving"
        runtime.refresh_agent_position(self)



# Feel free to inherit from or modify the above Agent class to implement different visitor behaviors.

class TeenagerAgent(Agent):
    """Fast-moving solo or group visitor with a longer average stay."""

    def __init__(
        self,
        agent_id: int,
        color: RGBColor,
        path: Path,
        group_size: int = 1,
        queue_type: str = "normal",
        planned_departure_time: float = 180.0,
        **kwargs,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            speed=DEFAULT_AGENT_SPEED * 1.10,
            color=color,
            path=path,
            visitor_type="teenager",
            group_size=group_size,
            queue_type=queue_type,
            planned_departure_time=planned_departure_time,
            image_path="inputs/teenager.png",
            **kwargs,
        )


class AdultAgent(Agent):
    """Average-speed visitor, most common in the park."""

    def __init__(
        self,
        agent_id: int,
        color: RGBColor,
        path: Path,
        group_size: int = 1,
        queue_type: str = "normal",
        planned_departure_time: float = 150.0,
        **kwargs,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            speed=DEFAULT_AGENT_SPEED,
            color=color,
            path=path,
            visitor_type="adult",
            group_size=group_size,
            queue_type=queue_type,
            planned_departure_time=planned_departure_time,
            image_path="inputs/adult.png",
            **kwargs,
        )


class ElderlyAgent(Agent):
    """Slower-moving visitor with a shorter average stay."""

    def __init__(
        self,
        agent_id: int,
        color: RGBColor,
        path: Path,
        group_size: int = 1,
        queue_type: str = "normal",
        planned_departure_time: float = 120.0,
        **kwargs,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            speed=DEFAULT_AGENT_SPEED * 0.80,
            color=color,
            path=path,
            visitor_type="elderly",
            group_size=group_size,
            queue_type=queue_type,
            planned_departure_time=planned_departure_time,
            image_path="inputs/elderly.png",
            **kwargs,
        )

    class GroupAgent(Agent):
        """Visitors arriving as a group with unique dynamics."""

        def __init__(
            self,
            agent_id: int,
            color: RGBColor,
            path: Path,
            group_size: int = 2,
            queue_type: str = "normal",
            planned_departure_time: float = 160.0,
            **kwargs,
        ) -> None:
            if group_size < 2:
                group_size = 2  # enforce minimum
            super().__init__(
                agent_id=agent_id,
                speed=DEFAULT_AGENT_SPEED * 0.95,
                color=color,
                path=path,
                visitor_type="group",
                group_size=group_size,
                queue_type=queue_type,
                planned_departure_time=planned_departure_time,
                image_path="inputs/group.png",
                **kwargs,
            )