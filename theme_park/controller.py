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
        self.hovered_agent = None   ### UPDATED ###
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

    def add_agent(self) -> None:
        self.sim.add_agent()

    """Logic for handling changes to slider parameters"""
    def _handle_slider_event(self, event) -> None:
        if event.ui_element == self.control_panel.agent_slider:
            new_count = int(event.value)
            if new_count != self.sim.agent_count:
                self.reset_sim(agent_count=new_count)

        elif event.ui_element == self.control_panel.sim_speed_slider:
            self.simulation_speed = float(event.value)

    """Logic for handling button press events"""
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

    def update(self, dt: float) -> None:
        self.ui_manager.update(dt)
        self.sim.step(dt * self.simulation_speed)

        self.mouse_pos = pygame.mouse.get_pos()
        ### UPDATED ### detect node or agent hover
        if self.mouse_pos[0] < SIM_W:
            self.tooltip_node = self.sim.node_at_position(self.mouse_pos)
            if self.tooltip_node is None:
                self.hovered_agent = self.sim.agent_at_position(self.mouse_pos)
            else:
                self.hovered_agent = None
        else:
            self.tooltip_node = None
            self.hovered_agent = None

        ### UPDATED ### update info label based on hover
        if self.tooltip_node is not None:
            self.control_panel.info_label.set_text(self.sim.hovered_info(self.tooltip_node).replace("\n", " | "))
        elif self.hovered_agent is not None:
            self.control_panel.info_label.set_text(self.sim.agent_hovered_info(self.hovered_agent).replace("\n", " | "))
        else:
            self.control_panel.info_label.set_text("Hover a ride or agent to see info")

    def draw(self) -> None:
        ### UPDATED ### pass hovered_agent to view
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