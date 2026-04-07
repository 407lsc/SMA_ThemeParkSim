from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import pygame
import pygame_gui

from .config import (
    BG,
    DEFAULT_AGENT_SPEED,
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
from .models import Agent, Ride   ### UPDATED ### import Agent
from .simulation import ThemeParkSim


def draw_text(
    surface: pygame.Surface,
    text: str,
    pos: Tuple[int, int],
    font: pygame.font.Font,
    color=TEXT_COLOR,
) -> None:
    img = font.render(text, True, color)
    surface.blit(img, pos)


def draw_multiline(
    surface: pygame.Surface,
    text: str,
    pos: Tuple[int, int],
    font: pygame.font.Font,
    color=TEXT_COLOR,
    line_gap: int = 4,
) -> None:
    x, y = pos
    for line in text.splitlines():
        img = font.render(line, True, color)
        surface.blit(img, (x, y))
        y += img.get_height() + line_gap


class ParkView:
    """Render the simulation scene and HUD elements onto the pygame screen."""

    def __init__(self, screen: pygame.Surface, font: pygame.font.Font, small_font: pygame.font.Font) -> None:
        """Store drawing surfaces and fonts used by the view layer."""
        self.screen = screen
        self.font = font
        self.small_font = small_font
        self._image_cache: Dict[Tuple[str, int], Optional[pygame.Surface]] = {}

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parent.parent

    def _load_node_image(self, image_path: str, diameter: int) -> Optional[pygame.Surface]:
        cache_key = (image_path, diameter)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        candidate = Path(image_path)
        full_path = candidate if candidate.is_absolute() else (self._project_root() / candidate)

        if not full_path.exists():
            self._image_cache[cache_key] = None
            return None

        try:
            image = pygame.image.load(str(full_path)).convert_alpha()
            scaled = pygame.transform.smoothscale(image, (diameter, diameter))
            self._image_cache[cache_key] = scaled
            return scaled
        except pygame.error:
            self._image_cache[cache_key] = None
            return None

    @staticmethod
    def _agent_color_map(sim: ThemeParkSim) -> Dict[int, Tuple[int, int, int]]:
        return {agent.agent_id: agent.color for agent in sim.agents}

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
        top_margin = 10
        row_gap = 6
        row_height = dot_radius * 2

        for node_id, (x, y) in sim.positions.items():
            meta = sim.node_data[node_id]
            if not isinstance(meta, Ride):
                continue

            base_radius = 16
            node_radius = meta.radius if meta.radius is not None else base_radius
            row_y_start = int(y + node_radius + top_margin)

            for row_index, (label, queue_type, label_color) in enumerate(queue_rows):
                if queue_type == "single_rider":
                    ids = list(meta.single_rider_queue.queue)
                elif queue_type == "fastpass":
                    ids = list(meta.fastpass_queue.queue)
                else:
                    ids = list(meta.normal_queue.queue)

                visible_ids = ids[:max_visible]
                label_surface = self.small_font.render(str(len(ids)) + label, True, label_color)
                dots_width = 0
                if visible_ids:
                    dots_width = (len(visible_ids) * (dot_radius * 2)) + ((len(visible_ids) - 1) * dot_spacing)
                row_width = label_surface.get_width() + label_gap + dots_width

                row_y = row_y_start + row_index * (row_height + row_gap)
                row_x = int(x - row_width / 2)

                label_x = row_x
                label_y = row_y + (row_height - label_surface.get_height()) // 2
                self.screen.blit(label_surface, (label_x, label_y))

                dots_start_x = label_x + label_surface.get_width() + label_gap
                for i, agent_id in enumerate(visible_ids):
                    center_x = dots_start_x + dot_radius + i * ((dot_radius * 2) + dot_spacing)
                    center_y = row_y + dot_radius
                    base_color = agent_colors.get(agent_id, (120, 120, 120))

                    alpha = 255
                    if len(ids) > max_visible and max_visible > 1:
                        fade_start_index = max(0, max_visible - fade_tail_count)
                        if i >= fade_start_index and fade_tail_count > 1:
                            fade_pos = i - fade_start_index
                            fade_ratio = fade_pos / (fade_tail_count - 1)
                            alpha = max(60, int(255 * (1.0 - 0.75 * fade_ratio)))

                    dot_surface = pygame.Surface((dot_radius * 2, dot_radius * 2), pygame.SRCALPHA)
                    pygame.draw.circle(dot_surface, (*base_color, alpha), (dot_radius, dot_radius), dot_radius)
                    pygame.draw.circle(dot_surface, (255, 255, 255, alpha), (dot_radius, dot_radius), dot_radius, 1)
                    self.screen.blit(dot_surface, (center_x - dot_radius, center_y - dot_radius))

    ### UPDATED ### draw method now accepts hovered_agent
    def draw(
        self,
        sim: ThemeParkSim,
        simulation_speed: float,
        tooltip_node: Optional[str],
        mouse_pos: Tuple[int, int],
        hovered_agent: Optional[Agent] = None,
    ) -> None:
        """Draw the full frame: map, nodes, agents, tooltip, and sidebar stats."""
        self.screen.fill(BG)
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
            if meta.image_path:
                node_image = self._load_node_image(meta.image_path, radius * 2)
                if node_image is not None:
                    image_rect = node_image.get_rect(center=(int(x), int(y)))
                    self.screen.blit(node_image, image_rect)
                    used_image = True

            if not used_image:
                pygame.draw.circle(self.screen, color, (int(x), int(y)), radius)

            # Keep a border around both image and circle markers for consistency.
            pygame.draw.circle(self.screen, (255, 255, 255), (int(x), int(y)), radius, 2)

            label = meta.name
            label_surface = self.small_font.render(label, True, (30, 30, 30))
            self.screen.blit(label_surface, (x - label_surface.get_width() // 2, y - radius - 22))

        self._draw_ride_queues(sim)

        for agent in sim.agents:
            if agent.state in ("queuing", "on_ride"):
                continue
            x, y = agent.pos
            pygame.draw.circle(self.screen, agent.color, (int(x), int(y)), 5)

        if tooltip_node is not None and sim.node_data[tooltip_node].kind == "ride":
            mouse_x, mouse_y = pygame.mouse.get_pos()
            box_w, box_h = 220, 90
            box_x = min(mouse_x + 15, SIM_W - box_w - 10)
            box_y = min(mouse_y + 15, HEIGHT - box_h - 10)
            pygame.draw.rect(self.screen, HOVER_PANEL_BG, pygame.Rect(box_x, box_y, box_w, box_h), border_radius=6)
            pygame.draw.rect(self.screen, HOVER_BORDER, pygame.Rect(box_x, box_y, box_w, box_h), 1, border_radius=6)
            draw_multiline(self.screen, sim.hovered_info(tooltip_node), (box_x + 10, box_y + 10), self.small_font)

        ### UPDATED ### draw tooltip for agent if hovered
        if hovered_agent is not None:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            info_text = sim.agent_hovered_info(hovered_agent)
            lines = info_text.splitlines()
            max_width = max(self.small_font.size(line)[0] for line in lines) + 20
            box_h = len(lines) * 22 + 10
            box_x = min(mouse_x + 15, SIM_W - max_width - 10)
            box_y = min(mouse_y + 15, HEIGHT - box_h - 10)
            pygame.draw.rect(self.screen, HOVER_PANEL_BG, pygame.Rect(box_x, box_y, max_width, box_h), border_radius=6)
            pygame.draw.rect(self.screen, HOVER_BORDER, pygame.Rect(box_x, box_y, max_width, box_h), 1, border_radius=6)
            draw_multiline(self.screen, info_text, (box_x + 10, box_y + 8), self.small_font)

        hud_lines = [
            f"Agents: {len(sim.agents)}",
            f"Exited: {sim.exited_agent_count}",   # new line
            f"Agent speed: {DEFAULT_AGENT_SPEED:.0f}",
            f"Sim speed: {simulation_speed:.1f}x",
            f"Current step: {sim.current_time_step}",
            f"Sim time: {sim.elapsed_sim_time:.1f}s",
            f"Cursor: ({mouse_pos[0]}, {mouse_pos[1]})",
        ]
        line_height = 24
        hud_y = HEIGHT - (line_height * len(hud_lines))
        for i, line in enumerate(hud_lines):
            draw_text(self.screen, line, (SIM_W + 15, hud_y + i * line_height), self.small_font)


class ControlPanel:
    """Define and manage the pygame_gui control widgets in the sidebar."""

    def __init__(self, ui_manager: pygame_gui.UIManager, sim: ThemeParkSim) -> None:
        """Create sliders, buttons, and labels for simulation controls."""
        self.ui_manager = ui_manager
        panel_x = SIM_W + 15
        y = 20

        self.title_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 30)),
            text="Controls",
            manager=self.ui_manager,
        )
        y += 50

        self.agent_slider_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 22)),
            text="Agent count",
            manager=self.ui_manager,
        )
        y += 25
        self.agent_slider = pygame_gui.elements.UIHorizontalSlider(
            relative_rect=pygame.Rect((panel_x, y), (280, 30)),
            start_value=sim.agent_count,
            value_range=(1, 80),
            manager=self.ui_manager,
        )
        y += 55

        self.sim_speed_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 22)),
            text="Simulation speed",
            manager=self.ui_manager,
        )
        y += 25
        self.sim_speed_slider = pygame_gui.elements.UIHorizontalSlider(
            relative_rect=pygame.Rect((panel_x, y), (280, 30)),
            start_value=1.0,
            value_range=(0.2, 3.0),
            manager=self.ui_manager,
        )
        y += 70

        self.reset_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((panel_x, y), (130, 35)),
            text="Reset",
            manager=self.ui_manager,
        )
        self.add_agent_button = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((panel_x + 150, y), (130, 35)),
            text="Add Agent",
            manager=self.ui_manager,
        )
        y += 60

        self.info_label = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((panel_x, y), (280, 22)),
            text="Hover a ride or agent to see info",
            manager=self.ui_manager,
        )

    def sync_from_sim(self, sim: ThemeParkSim, simulation_speed: float) -> None:
        """Sync widget values after simulation reset or model replacement."""
        self.agent_slider.set_current_value(sim.agent_count)
        self.sim_speed_slider.set_current_value(simulation_speed)