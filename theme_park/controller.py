from __future__ import annotations

from typing import Optional, Tuple

import pygame
import pygame_gui

from .config import FPS, HEIGHT, SIM_W, WIDTH
from .simulation import ThemeParkSim
from .view import ControlPanel, ParkView


class App:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Theme Park ABM Prototype")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        self.font = pygame.font.Font(None, 22)
        self.small_font = pygame.font.Font(None, 18)

        self.sim = ThemeParkSim()
        self.simulation_speed = 1.0
        self.tooltip_node: Optional[str] = None
        self.hovered_agent = None
        self.mouse_pos: Tuple[int, int] = (0, 0)

        self.ui_manager = pygame_gui.UIManager((WIDTH, HEIGHT))
        self.control_panel = ControlPanel(self.ui_manager, self.sim)
        self.view = ParkView(self.screen, self.font, self.small_font)

    def reset_sim(self, agent_count: Optional[int] = None) -> None:
        if agent_count is None:
            self.sim = ThemeParkSim()
        else:
            self.sim = ThemeParkSim(agent_count=agent_count)
        self.control_panel.sync_from_sim(self.sim, 1.0)
        self.simulation_speed = 1.0
        self.sync_time_slider()

    def add_agent(self) -> None:
        self.sim.add_agent()

    def _handle_slider_event(self, event) -> None:
        if event.ui_element == self.control_panel.agent_slider:
            new_count = int(event.value)
            current_count = len(self.sim.agents)
            if new_count > current_count:
                for _ in range(new_count - current_count):
                    self.sim.add_agent()
            # Sync slider to actual agent count
            self.control_panel.agent_slider.set_current_value(len(self.sim.agents))

        elif event.ui_element == self.control_panel.sim_speed_slider:
            new_speed = float(event.value)
            self.control_panel.sim_speed_label.set_text(f"Simulation speed: {new_speed:.1f}x")
            self.simulation_speed = new_speed

        elif event.ui_element == self.control_panel.time_slider:
            offset_hours = float(event.value)
            self.sim.set_park_time(offset_hours)
            # Update the label with current park time
            self.control_panel.time_value_label.set_text(f"Current time: {self.sim.get_park_time_str()}")

    def _handle_button_event(self, event) -> None:
        if event.ui_element == self.control_panel.reset_button:
            self.reset_sim()
        elif event.ui_element == self.control_panel.add_agent_button:
            self.add_agent()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            self.ui_manager.process_events(event)

            if event.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
                self._handle_slider_event(event)
            elif event.type == pygame_gui.UI_BUTTON_PRESSED:
                self._handle_button_event(event)

    def sync_time_slider(self) -> None:
        offset = self.sim.get_park_time_seconds() / 3600.0
        self.control_panel.time_slider.set_current_value(offset)
        self.control_panel.time_value_label.set_text(f"Current time: {self.sim.get_park_time_str()}")

    def update(self, dt: float) -> None:
        self.ui_manager.update(dt)
        self.sim.step(dt * self.simulation_speed)

        self.mouse_pos = pygame.mouse.get_pos()
        if self.mouse_pos[0] < SIM_W:
            self.tooltip_node = self.sim.node_at_position(self.mouse_pos)
            if self.tooltip_node is None:
                self.hovered_agent = self.sim.agent_at_position(self.mouse_pos)
            else:
                self.hovered_agent = None
        else:
            self.tooltip_node = None
            self.hovered_agent = None

        if self.tooltip_node is not None:
            self.control_panel.info_label.set_text(self.sim.hovered_info(self.tooltip_node).replace("\n", " | "))
        elif self.hovered_agent is not None:
            self.control_panel.info_label.set_text(self.sim.agent_hovered_info(self.hovered_agent).replace("\n", " | "))
        else:
            self.control_panel.info_label.set_text("Hover a ride or agent to see info")

        self.sync_time_slider()

    def draw(self) -> None:
        self.view.draw(self.sim, self.simulation_speed, self.tooltip_node, self.mouse_pos, self.hovered_agent)
        self.ui_manager.draw_ui(self.screen)
        pygame.display.flip()

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self.handle_events()
            self.update(dt)
            self.draw()

        pygame.quit()