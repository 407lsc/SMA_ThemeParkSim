from __future__ import annotations

from typing import Optional, Tuple

import pygame
import pygame_gui

from .config import FPS, HEIGHT, SIM_W, WIDTH
from .models import Ride
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
        self._step_accumulator = 0.0
        self._max_steps_hard_cap = 400
        self._max_frame_dt_for_steps = 0.1
        self.tooltip_node: Optional[str] = None
        self.mouse_pos: Tuple[int, int] = (0, 0)

        self.ui_manager = pygame_gui.UIManager((WIDTH, HEIGHT))
        self.control_panel = ControlPanel(self.ui_manager, self.sim)
        self.view = ParkView(self.screen, self.font, self.small_font)
        self._dirty_text_entries: set[pygame_gui.elements.UITextEntryLine] = set()

    def reset_sim(self) -> None:
        self.sim = ThemeParkSim()
        self.control_panel.sync_from_sim(self.sim, 1.0)
        self.simulation_speed = 1.0
        self._step_accumulator = 0.0

    def add_agent(self) -> None:
        self.sim.add_agent()

    @staticmethod
    def _clamp(value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(max_value, value))

    def _apply_sim_speed(self, speed: float) -> None:
        previous_speed = self.simulation_speed
        self.simulation_speed = speed
        if speed < previous_speed:
            # Prevent high-speed backlog from continuing to execute after slowdown.
            self._step_accumulator = 0.0
        self.control_panel.sim_speed_value_entry.set_text(f"{speed:.1f}")

    def _jump_slider_to_mouse(self, mouse_pos: Tuple[int, int]) -> None:
        slider_specs = [
            (self.control_panel.sim_speed_slider, self.control_panel.sim_speed_range),
        ]

        for slider, (min_v, max_v) in slider_specs:
            rect = slider.rect
            if rect is None:
                continue
            if not rect.collidepoint(mouse_pos):
                continue

            # Let arrow buttons use slider click_increment behavior.
            arrow_w = getattr(slider, "arrow_button_width", 0)
            if arrow_w > 0:
                if mouse_pos[0] <= rect.left + arrow_w:
                    return
                if mouse_pos[0] >= rect.right - arrow_w:
                    return

            ratio = (mouse_pos[0] - rect.left) / max(1, rect.width)
            ratio = self._clamp(ratio, 0.0, 1.0)
            raw_value = min_v + ratio * (max_v - min_v)

            value = self._clamp(raw_value, min_v, max_v)
            slider.set_current_value(value)
            self._apply_sim_speed(value)
            return

    """Logic for handling changes to slider parameters"""
    def _handle_slider_event(self, event) -> None:
        if event.ui_element == self.control_panel.sim_speed_slider:
            self._apply_sim_speed(float(event.value))

    def _apply_text_entry_value(self, ui_element, text: str) -> None:
        if ui_element == self.control_panel.sim_speed_value_entry:
            try:
                entered = float(text.strip())
            except ValueError:
                self.control_panel.sim_speed_value_entry.set_text(f"{self.simulation_speed:.1f}")
                return
            min_v, max_v = self.control_panel.sim_speed_range
            clamped = self._clamp(entered, min_v, max_v)
            self.control_panel.sim_speed_slider.set_current_value(clamped)
            self._apply_sim_speed(clamped)
            return

        for node_id, entry in self.control_panel.ride_capacity_entries.items():
            if ui_element != entry:
                continue

            meta = self.sim.node_data.get(node_id)
            if not isinstance(meta, Ride):
                entry.set_text(text.strip())
                return

            try:
                entered_capacity = int(text.strip())
            except ValueError:
                entry.set_text(str(meta.capacity))
                return

            updated_capacity = max(1, entered_capacity)
            meta.capacity = updated_capacity
            entry.set_text(str(updated_capacity))
            return

    def _handle_text_entry_event(self, event) -> None:
        self._apply_text_entry_value(event.ui_element, event.text)

    def _commit_blurred_text_entries(self) -> None:
        tracked_entries = [
            self.control_panel.sim_speed_value_entry,
            *self.control_panel.ride_capacity_entries.values(),
        ]

        for entry in tracked_entries:
            if entry not in self._dirty_text_entries:
                continue
            if entry.is_focused:
                continue

            self._apply_text_entry_value(entry, entry.get_text())
            self._dirty_text_entries.discard(entry)

    """Logic for handling button press events"""
    def _handle_button_event(self, event) -> None:
        if event.ui_element == self.control_panel.reset_button:
            self.reset_sim()
        elif event.ui_element == self.control_panel.add_agent_button:
            self.add_agent()
        elif event.ui_element == self.control_panel.pause_button:
            self.toggle_pause()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_p or event.key == pygame.K_SPACE:
                    self.toggle_pause()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._jump_slider_to_mouse(event.pos)

            self.ui_manager.process_events(event)

            if event.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
                self._handle_slider_event(event)
            elif event.type == pygame_gui.UI_BUTTON_PRESSED:
                self._handle_button_event(event)
            elif event.type == pygame_gui.UI_TEXT_ENTRY_FINISHED:
                self._handle_text_entry_event(event)
                if hasattr(event, "ui_element"):
                    self._dirty_text_entries.discard(event.ui_element)
            elif event.type == pygame_gui.UI_TEXT_ENTRY_CHANGED:
                if hasattr(event, "ui_element"):
                    self._dirty_text_entries.add(event.ui_element)

    def update(self, dt: float) -> None:
        self.ui_manager.update(dt)

        # Run discrete simulation steps from a speed-scaled fixed-step budget.
        # This keeps step progression sequential and avoids skipping steps.
        if not self.sim.paused:
            # Clamp frame dt to avoid giant catch-up jumps after hiccups/focus loss.
            effective_dt = min(dt, self._max_frame_dt_for_steps)
            self._step_accumulator += effective_dt * self.simulation_speed * FPS
            steps_available = int(self._step_accumulator)
            # At speed=x, roughly x steps become due per rendered frame.
            # Use an adaptive cap so high speeds are not throttled by a low fixed cap.
            adaptive_cap = min(self._max_steps_hard_cap, max(8, int(self.simulation_speed) + 8))
            steps_to_run = min(steps_available, adaptive_cap)
            if steps_to_run > 0:
                self._step_accumulator -= steps_to_run
                fixed_dt = 1.0 / FPS
                for _ in range(steps_to_run):
                    self.sim.step(fixed_dt)

        self.mouse_pos = pygame.mouse.get_pos()
        if self.mouse_pos[0] < SIM_W:
            self.tooltip_node = self.sim.node_at_position(self.mouse_pos)
        else:
            self.tooltip_node = None

        self._commit_blurred_text_entries()
        self.control_panel.clock_label.set_text(
            f"Time: {self.sim.get_time_str()}"
        )

    def draw(self) -> None:
        self.view.draw(self.sim, self.simulation_speed, self.tooltip_node, self.mouse_pos)
        self.ui_manager.draw_ui(self.screen)
        pygame.display.flip()

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()
    
    def toggle_pause(self) -> None:
        self.sim.toggle_pause()
        self.control_panel.pause_button.set_text(
            "Resume" if self.sim.paused else "Pause"
        )

        
