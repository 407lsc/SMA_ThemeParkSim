from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import pygame
import pygame_gui

from .config import (
    BG,
    EDGE_COLOR,
    HEIGHT,
    HOVER_BORDER,
    HOVER_PANEL_BG,
    INTERSECTION_COLOR,
    PANEL_BG,
    PANEL_W,
    RIDE_COLOR,
    SIM_W,
    TEXT_COLOR,
)
from .models import Ride
from .simulation import ThemeParkSim


def draw_text(
    surface: pygame.Surface,
    text: str,
    pos: Tuple[int, int],
    font: pygame.font.Font,
    color=TEXT_COLOR,
    center: bool = False,
    background: Optional[Tuple[int, int, int]] = None,
) -> None:
    """Draw a single line of text.

    Args:
        center: if True, position is treated as center instead of top-left
        background: optional background color for readability
    """
    img = font.render(text, True, color, background)

    if center:
        rect = img.get_rect(center=pos)
        surface.blit(img, rect)
    else:
        surface.blit(img, pos)


def draw_multiline(
    surface: pygame.Surface,
    text: str,
    pos: Tuple[int, int],
    font: pygame.font.Font,
    color=TEXT_COLOR,
    line_gap: int = 4,
    center: bool = False,
    background: Optional[Tuple[int, int, int]] = None,
) -> None:
    """Draw multiple lines of text.

    Args:
        center: horizontally centers each line around pos[0]
        background: optional background color for readability
    """
    x, y = pos

    for line in text.splitlines():
        img = font.render(line, True, color, background)

        if center:
            rect = img.get_rect(center=(x, y + img.get_height() // 2))
            surface.blit(img, rect)
        else:
            surface.blit(img, (x, y))

        y += img.get_height() + line_gap


class ParkView:
    """Render the simulation scene and HUD elements onto the pygame screen."""

    def __init__(self, screen: pygame.Surface, font: pygame.font.Font, small_font: pygame.font.Font) -> None:
        """Store drawing surfaces and fonts used by the view layer."""
        self.screen = screen
        self.font = font
        self.small_font = small_font
        self.background = pygame.image.load("inputs/Theme_Park_Map (1).png").convert()
        self.background = pygame.transform.smoothscale(self.background, (SIM_W, HEIGHT))

    @staticmethod
    def _agent_color_map(sim: ThemeParkSim) -> Dict[int, Tuple[int, int, int]]:
        return {agent.agent_id: agent.color for agent in sim.agents}

    @staticmethod
    def _queue_entry_agent_id(entry) -> Optional[int]:
        """Extract agent_id from queue entries.

        Supports:
        - raw agent_id
        - (agent_id, group_size)
        - (agent_id, group_size, queue_type)
        """
        if isinstance(entry, int):
            return entry
        if isinstance(entry, tuple) and len(entry) >= 1:
            return entry[0]
        return None

    @staticmethod
    def _queue_entry_group_size(entry) -> int:
        """Extract group size from queue entries, defaulting to 1."""
        if isinstance(entry, tuple) and len(entry) >= 2 and isinstance(entry[1], int):
            return entry[1]
        return 1

    @staticmethod
    def _queue_people_count(queue_entries: list) -> int:
        return sum(ParkView._queue_entry_group_size(entry) for entry in queue_entries)

    def _draw_node(
        self,
        sim: ThemeParkSim,
        node_id: str,
        x: float,
        y: float,
        is_hovered: bool = False,
    ) -> None:
        """Draw one node using its image if available, otherwise a circle."""
        meta = sim.node_data[node_id]
        cx, cy = int(x), int(y)
        radius = meta.radius if meta.radius is not None else 16

        if meta.image is not None:
            rect = meta.image.get_rect(center=(cx, cy))
            self.screen.blit(meta.image, rect)

            if is_hovered:
                pygame.draw.circle(
                    self.screen,
                    (255, 255, 0),
                    (cx, cy),
                    max(rect.width, rect.height) // 2 + 4,
                    2,
                )
        else:
            fill_color = meta.color if meta.color is not None else (180, 180, 180)
            pygame.draw.circle(self.screen, fill_color, (cx, cy), radius)
            pygame.draw.circle(self.screen, (255, 255, 255), (cx, cy), radius, 2)

            if is_hovered:
                pygame.draw.circle(self.screen, (255, 255, 0), (cx, cy), radius + 4, 2)

    def _draw_ride_queues(self, sim: ThemeParkSim) -> None:
        """Draw S/N/F queue rows centered beneath each ride marker."""
        agent_colors = self._agent_color_map(sim)
        queue_rows = [
            ("S", "single_rider", (55, 55, 55)),
            ("N", "normal", (55, 55, 55)),
            ("F", "fastpass", (55, 55, 55)),
        ]

        max_visible = 20
        fade_tail_count = 10
        dot_radius = 5
        dot_spacing = 0
        label_gap = 3
        top_margin = -10 # Distance between ride node and queue visualisation
        row_gap = 6
        row_height = dot_radius * 2

        for node_id, (x, y) in sim.positions.items():
            meta = sim.node_data[node_id]
            if not isinstance(meta, Ride):
                continue

            if meta.image is not None:
                row_y_start = int(y + meta.image.get_height() / 2 + top_margin)
            else:
                base_radius = 16
                node_radius = meta.radius if meta.radius is not None else base_radius
                row_y_start = int(y + node_radius + top_margin)

            for row_index, (label, queue_type, label_color) in enumerate(queue_rows):
                if queue_type == "single_rider":
                    entries = list(meta.single_rider_queue.queue)
                elif queue_type == "fastpass":
                    entries = list(meta.fastpass_queue.queue)
                else:
                    entries = list(meta.normal_queue.queue)

                visible_entries = entries[:max_visible]
                total_people = self._queue_people_count(entries)

                label_surface = self.small_font.render(
                    f"{total_people}{label}",
                    True,
                    label_color,
                )

                dots_width = 0
                if visible_entries:
                    dots_width = (
                        len(visible_entries) * (dot_radius * 2)
                        + (len(visible_entries) - 1) * dot_spacing
                    )

                row_width = label_surface.get_width() + label_gap + dots_width
                row_y = row_y_start + row_index * (row_height + row_gap)
                row_x = int(x - row_width / 2)

                label_x = row_x
                label_y = row_y + (row_height - label_surface.get_height()) // 2
                self.screen.blit(label_surface, (label_x, label_y))

                dots_start_x = label_x + label_surface.get_width() + label_gap

                for i, entry in enumerate(visible_entries):
                    agent_id = self._queue_entry_agent_id(entry)
                    if agent_id is None:
                        continue

                    center_x = dots_start_x + dot_radius + i * ((dot_radius * 2) + dot_spacing)
                    center_y = row_y + dot_radius
                    base_color = agent_colors.get(agent_id, (120, 120, 120))

                    alpha = 255
                    if len(entries) > max_visible and max_visible > 1:
                        fade_start_index = max(0, max_visible - fade_tail_count)
                        if i >= fade_start_index and fade_tail_count > 1:
                            fade_pos = i - fade_start_index
                            fade_ratio = fade_pos / (fade_tail_count - 1)
                            alpha = max(60, int(255 * (1.0 - 0.75 * fade_ratio)))

                    dot_surface = pygame.Surface(
                        (dot_radius * 2, dot_radius * 2),
                        pygame.SRCALPHA,
                    )
                    pygame.draw.circle(
                        dot_surface,
                        (*base_color, alpha),
                        (dot_radius, dot_radius),
                        dot_radius,
                    )
                    pygame.draw.circle(
                        dot_surface,
                        (255, 255, 255, alpha),
                        (dot_radius, dot_radius),
                        dot_radius,
                        1,
                    )
                    self.screen.blit(dot_surface, (center_x - dot_radius, center_y - dot_radius))
    def draw(
        self,
        sim: ThemeParkSim,
        simulation_speed: float,
        tooltip_node: Optional[str],
        mouse_pos: Tuple[int, int],
    ) -> None:
        """Draw the full frame: map, nodes, agents, tooltip, and sidebar stats."""
        self.screen.blit(self.background, (0,0))
        pygame.draw.rect(self.screen, PANEL_BG, pygame.Rect(SIM_W, 0, PANEL_W, HEIGHT))

        for u, v in sim.graph.edges():
            x1, y1 = sim.positions[u]
            x2, y2 = sim.positions[v]
            pygame.draw.line(self.screen, EDGE_COLOR, (x1, y1), (x2, y2), 2)

        for node_id, (x, y) in sim.positions.items():
            meta = sim.node_data[node_id]
            base_radius = 16 if meta.kind == "ride" else 10
            radius = meta.radius if meta.radius is not None else base_radius
            default_color = RIDE_COLOR if meta.kind == "ride" else INTERSECTION_COLOR
            color = meta.color if meta.color is not None else default_color

            used_image = False
            image_half_height = 0

            if meta.image is not None:
                image_rect = meta.image.get_rect(center=(int(x), int(y)))
                self.screen.blit(meta.image, image_rect)
                used_image = True
                image_half_height = meta.image.get_height() // 2

            if not used_image and meta.kind=="ride":
                pygame.draw.circle(self.screen, color, (int(x), int(y)), radius)
                pygame.draw.circle(self.screen, (255, 255, 255), (int(x), int(y)), radius, 2)

            label = meta.name
            label_surface = self.small_font.render(label, True, (30, 30, 30))

            if used_image:
                label_y = int(y - image_half_height - 18)
            else:
                label_y = int(y - radius - 22)

            self.screen.blit(
                label_surface,
                (int(x - label_surface.get_width() // 2), label_y),
            )

        self._draw_ride_queues(sim)

        for agent in sim.agents:
            if agent.state in ("queuing", "on_ride"):
                continue
            x, y = agent.pos
            if agent.image_path:
                img = pygame.image.load(agent.image_path).convert_alpha()
                img = pygame.transform.smoothscale(img, (24, 24))
                rect = img.get_rect(center=(int(x), int(y)))
                self.screen.blit(img, rect)
            else:
                pygame.draw.circle(self.screen, agent.color, (int(x), int(y)), 5)

        if tooltip_node is not None and sim.node_data[tooltip_node].kind == "ride":
            mouse_x, mouse_y = pygame.mouse.get_pos()
            box_w, box_h = 220, 90
            box_x = min(mouse_x + 15, SIM_W - box_w - 10)
            box_y = min(mouse_y + 15, HEIGHT - box_h - 10)
            pygame.draw.rect(self.screen, HOVER_PANEL_BG, pygame.Rect(box_x, box_y, box_w, box_h), border_radius=6)
            pygame.draw.rect(self.screen, HOVER_BORDER, pygame.Rect(box_x, box_y, box_w, box_h), 1, border_radius=6)
            draw_multiline(self.screen, sim.hovered_info(tooltip_node), (box_x + 10, box_y + 10), self.small_font)
        else:
            hovered_agent = sim.agent_at_position(mouse_pos)
            if hovered_agent is not None:
                mouse_x, mouse_y = pygame.mouse.get_pos()
                agent_info = sim.hovered_agent_info(hovered_agent)
                line_count = len(agent_info.splitlines())
                box_w = 260
                box_h = max(88, 20 + line_count * 20)
                box_x = min(mouse_x + 15, SIM_W - box_w - 10)
                box_y = min(mouse_y + 15, HEIGHT - box_h - 10)
                pygame.draw.rect(self.screen, HOVER_PANEL_BG, pygame.Rect(box_x, box_y, box_w, box_h), border_radius=6)
                pygame.draw.rect(self.screen, HOVER_BORDER, pygame.Rect(box_x, box_y, box_w, box_h), 1, border_radius=6)
                draw_multiline(self.screen, agent_info, (box_x + 10, box_y + 10), self.small_font)

        hud_lines = [
            f"Agents: {len(sim.agents)}",
            f"People in park: {sum(a.group_size for a in sim.agents)}",
            f"Total entered: {sim.total_entered}",
            f"Total exited: {sim.total_exited}",
            f"Sim speed: {simulation_speed:.1f}x",
            f"Current step: {sim.current_time_step}",
            f"Elapsed sim time: {sim.elapsed_sim_time:.1f} min",
            f"Cursor: ({mouse_pos[0]}, {mouse_pos[1]})",
        ]
        line_height = 24
        hud_y = HEIGHT - (line_height * len(hud_lines))
        for i, line in enumerate(hud_lines):
            draw_text(self.screen, line, (SIM_W + 15, hud_y + i * line_height), self.small_font)


class ControlPanel:
    """Define and manage the pygame_gui control widgets in the sidebar."""

    @staticmethod
    def _set_label_text_black(label: pygame_gui.elements.UILabel) -> None:
        label.text_colour = pygame.Color("#000000")
        label.disabled_text_colour = pygame.Color("#000000")
        label.rebuild()

    def __init__(self, ui_manager: pygame_gui.UIManager, sim: ThemeParkSim) -> None:
        """Create sliders, buttons, and labels for simulation controls."""
        self.ui_manager = ui_manager
        self.queue_ratio_entries: dict[str, pygame_gui.elements.UITextEntryLine] = {}
        self.ride_capacity_entries: dict[str, pygame_gui.elements.UITextEntryLine] = {}

        # Set up value ranges for sliders
        self.sim_speed_range = (0.1, 50.0)

        panel_x = SIM_W + 15
        y = 20
        slider_w = 185
        value_box_w = 87
        slider_gap = 8

        self.clock_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x,y), (280,30)),
            text = "Time: 0900",
            manager = self.ui_manager,
        )
        self._set_label_text_black(self.clock_label)
        y += 50

        self.title_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 30)),
            text="Controls:",
            manager=self.ui_manager,
        )
        self._set_label_text_black(self.title_label)
        y += 40

        self.sim_speed_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 22)),
            text="Simulation speed",
            manager=self.ui_manager,
        )
        self._set_label_text_black(self.sim_speed_label)
        y += 25
        self.sim_speed_slider = pygame_gui.elements.UIHorizontalSlider(
            relative_rect=pygame.Rect((panel_x, y), (slider_w, 30)),
            start_value=1.0,
            value_range=self.sim_speed_range,
            click_increment=0.1,
            manager=self.ui_manager,
        )
        self.sim_speed_value_entry = pygame_gui.elements.UITextEntryLine(
            relative_rect=pygame.Rect((panel_x + slider_w + slider_gap, y), (value_box_w, 30)),
            manager=self.ui_manager,
        )
        self.sim_speed_value_entry.set_text("1.0")

        y += 50

        self.queue_ratio_title = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 22)),
            text="Pass ratios (add up to 1)",
            manager=self.ui_manager,
        )
        self._set_label_text_black(self.queue_ratio_title)
        y += 26

        queue_rows = [
            ("Fast Pass (>= 0)", "fastpass", sim.single_fastpass_weight),
            ("Normal (> 0)", "normal", sim.single_normal_weight),
            ("Single Rider (>= 0)", "single_rider", sim.single_rider_weight),
        ]
        for label, key, value in queue_rows:
            row_label = pygame_gui.elements.UILabel(
                relative_rect=pygame.Rect((panel_x, y), (188, 22)),
                text=label,
                manager=self.ui_manager,
            )
            self._set_label_text_black(row_label)
            entry = pygame_gui.elements.UITextEntryLine(
                relative_rect=pygame.Rect((panel_x + 196, y), (84, 22)),
                manager=self.ui_manager,
            )
            entry.set_text(f"{value:.2f}")
            self.queue_ratio_entries[key] = entry
            _ = row_label
            y += 28

        self.queue_ratio_confirm_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((panel_x, y), (280, 30)),
            text="Confirm",
            manager=self.ui_manager,
        )

        y += 44

        self.ride_capacity_title = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 22)),
            text="Ride capacities",
            manager=self.ui_manager,
        )
        self._set_label_text_black(self.ride_capacity_title)
        y += 26

        for node_id, meta in sim.node_data.items():
            if not isinstance(meta, Ride):
                continue

            row_label = pygame_gui.elements.UILabel(
                relative_rect=pygame.Rect((panel_x, y), (188, 22)),
                text=meta.name,
                manager=self.ui_manager,
            )
            self._set_label_text_black(row_label)
            entry = pygame_gui.elements.UITextEntryLine(
                relative_rect=pygame.Rect((panel_x + 196, y), (84, 22)),
                manager=self.ui_manager,
            )
            entry.set_text(str(meta.capacity))
            self.ride_capacity_entries[node_id] = entry

            # Keep label widgets alive via pygame_gui references and layout order.
            _ = row_label
            y += 28

        y += 22

        self.reset_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((panel_x, y), (90, 35)),
            text="Reset",
            manager=self.ui_manager,
        )
        self.add_agent_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((panel_x + 94.5, y), (90, 35)),
            text="Add Agent",
            manager=self.ui_manager,
        )
        self.pause_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((panel_x + 189, y), (90, 35)),
            text="Pause",
            manager=self.ui_manager,
        )

        self.parametertuning_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((panel_x, y + 45), (280, 35)),
            text="Parameter Tuning",
            manager=self.ui_manager,
        )

    def sync_from_sim(self, sim: ThemeParkSim, simulation_speed: float) -> None:
        """Sync widget values after simulation reset or model replacement."""
        self.sim_speed_slider.set_current_value(simulation_speed)
        self.sim_speed_value_entry.set_text(f"{simulation_speed:.1f}")
        self.pause_button.set_text("Resume" if sim.paused else "Pause")

        if "fastpass" in self.queue_ratio_entries:
            self.queue_ratio_entries["fastpass"].set_text(f"{sim.single_fastpass_weight:.2f}")
        if "normal" in self.queue_ratio_entries:
            self.queue_ratio_entries["normal"].set_text(f"{sim.single_normal_weight:.2f}")
        if "single_rider" in self.queue_ratio_entries:
            self.queue_ratio_entries["single_rider"].set_text(f"{sim.single_rider_weight:.2f}")

        for node_id, entry in self.ride_capacity_entries.items():
            meta = sim.node_data.get(node_id)
            if isinstance(meta, Ride):
                entry.set_text(str(meta.capacity))
