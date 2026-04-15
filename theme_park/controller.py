from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

import pygame
import pygame_gui

from .config import (
    CAPACITY_TUNING_STEP,
    DEFAULT_AGENT_SPEED_PX,
    DEFAULT_SIMULATION_SPEED,
    DISABLE_GRAPHICS,
    FPS,
    HEIGHT,
    OUTPUT_DIR,
    PASS_TYPE_TUNING_STEP,
    SIM_W,
    WIDTH,
)
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
        self.simulation_speed = DEFAULT_SIMULATION_SPEED
        self._step_accumulator = 0.0
        self._max_steps_hard_cap = 400
        self._max_frame_dt_for_steps = 0.1
        self._max_micro_steps_per_step = 50
        self._max_edge_fraction_per_micro_step = 0.20
        self.tooltip_node: Optional[str] = None
        self.mouse_pos: Tuple[int, int] = (0, 0)

        self.ui_manager = pygame_gui.UIManager((WIDTH, HEIGHT), "inputs/ui_theme.json")
        self.control_panel = ControlPanel(self.ui_manager, self.sim)
        self.view = ParkView(self.screen, self.font, self.small_font)
        self._dirty_text_entries: set[pygame_gui.elements.UITextEntryLine] = set()

        # Parameter tuning (base wiring)
        self.tuning_capacity_options: dict[str, list[int]] = {}
        self.tuning_pass_weight_options: list[tuple[float, float, float]] = []
        self.tuning_total_config_count: int = 0
        self.tuning_config_iter = None

    def reset_sim(self) -> None:
        self.sim = ThemeParkSim()
        self.control_panel.sync_from_sim(self.sim, DEFAULT_SIMULATION_SPEED)
        self.simulation_speed = DEFAULT_SIMULATION_SPEED
        self._step_accumulator = 0.0

    def add_agent(self) -> None:
        self.sim.add_agent()

    def _stop_current_simulation(self) -> None:
        # For now, "stop" means: pause + prevent any catch-up steps.
        self.sim.paused = True
        self._step_accumulator = 0.0
        self.control_panel.sync_from_sim(self.sim, self.simulation_speed)

    @staticmethod
    def _slugify_column(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower())
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or "ride"

    def _parameter_tuning_csv_path(self) -> Path:
        project_root = Path(__file__).resolve().parent.parent
        out_dir = Path(OUTPUT_DIR)
        if not out_dir.is_absolute():
            out_dir = project_root / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"parameter_tuning_result_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"

    def _write_parameter_tuning_csv(
        self,
        capacity_options: dict[str, list[int]],
        pass_options: list[tuple[float, float, float]],
    ) -> Path:
        """Write all parameter tuning combinations to CSV.

        Columns:
        run_id, <ride_name>_cap..., fast_pass_weight, normal_weight, single_rider_weight
        """
        csv_path = self._parameter_tuning_csv_path()

        # Build deterministic, unique capacity column names based on ride names.
        used: dict[str, int] = {}
        ride_cols: list[tuple[str, str]] = []  # (col_name, node_id)
        for node_id in capacity_options.keys():
            meta = self.sim.node_data.get(node_id)
            ride_name = meta.name if isinstance(meta, Ride) else node_id
            base = f"{self._slugify_column(ride_name)}_cap"
            count = used.get(base, 0) + 1
            used[base] = count
            col = base if count == 1 else f"{base}_{count}"
            ride_cols.append((col, node_id))

        ride_cols.sort(key=lambda x: x[0])
        header = [
            "run_id",
            *[col for col, _ in ride_cols],
            "fast_pass_weight",
            "normal_weight",
            "single_rider_weight",
        ]

        run_id = 0
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)

            # Stream the cartesian product to disk (avoid huge in-memory matrices).
            for ride_capacities, (fastpass, normal, single_rider) in self.sim.iter_parameter_tuning_configs(
                CAPACITY_TUNING_STEP,
                PASS_TYPE_TUNING_STEP,
            ):
                run_id += 1
                row: list[object] = [run_id]
                for _col, node_id in ride_cols:
                    row.append(ride_capacities[node_id])
                row.extend([fastpass, normal, single_rider])
                writer.writerow(row)

        print(f"- CSV written: {csv_path} ({run_id} rows)")
        return csv_path

    def _setup_parameter_tuning_grid(self) -> None:
        self._stop_current_simulation()

        try:
            capacity_options = self.sim.capacity_tuning_options(CAPACITY_TUNING_STEP)
            pass_options = self.sim.pass_weight_tuning_options(PASS_TYPE_TUNING_STEP)
        except ValueError as exc:
            print(f"\n[Parameter Tuning] Invalid tuning configuration: {exc}")
            return

        total_capacity_combos = 1
        for values in capacity_options.values():
            total_capacity_combos *= max(1, len(values))
        total_configs = total_capacity_combos * max(1, len(pass_options))

        self.tuning_capacity_options = capacity_options
        self.tuning_pass_weight_options = pass_options
        self.tuning_total_config_count = total_configs
        self.tuning_config_iter = self.sim.iter_parameter_tuning_configs(
            CAPACITY_TUNING_STEP,
            PASS_TYPE_TUNING_STEP,
        )

        # Console summary (base functionality)
        print("\n[Parameter Tuning] Grid generated")
        print(f"- Capacity step: {CAPACITY_TUNING_STEP}")
        for node_id, values in capacity_options.items():
            meta = self.sim.node_data.get(node_id)
            ride_name = meta.name if isinstance(meta, Ride) else node_id
            if values:
                print(f"  - {ride_name}: {values[0]}..{values[-1]} ({len(values)} values)")
            else:
                print(f"  - {ride_name}: (no values)")
        print(f"- Pass step: {PASS_TYPE_TUNING_STEP}")
        if pass_options:
            fixed_single = pass_options[0][2]
            print(f"- Single rider fixed at: {fixed_single:.2f}")
        print(f"- Pass combos (F,N,S_fixed): {len(pass_options)}")
        print(f"- Total configs (capacity x pass): {total_configs}")

        # Export all combinations to CSV
        self._write_parameter_tuning_csv(capacity_options, pass_options)

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

        queue_entries = self.control_panel.queue_ratio_entries
        if ui_element in queue_entries.values():
            # Queue ratio entries are applied only through confirm button.
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
        if event.ui_element in self.control_panel.queue_ratio_entries.values():
            return
        self._apply_text_entry_value(event.ui_element, event.text)

    def _apply_queue_ratio_entries(self) -> None:
        entries = self.control_panel.queue_ratio_entries
        try:
            fastpass = float(entries["fastpass"].get_text().strip())
            normal = float(entries["normal"].get_text().strip())
            single_rider = float(entries["single_rider"].get_text().strip())
        except (ValueError, KeyError):
            # Invalid input: revert all three to current simulation values.
            self.control_panel.sync_from_sim(self.sim, self.simulation_speed)
            return

        updated = self.sim.set_queue_ratio_weights(fastpass, normal, single_rider)
        # Repaint fields from authoritative sim values (updated or reverted).
        self.control_panel.sync_from_sim(self.sim, self.simulation_speed)
        if not updated:
            return

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

    def _compute_micro_steps(self, simulated_seconds_per_step: float) -> int:
        if simulated_seconds_per_step <= 0:
            return 1

        edge_lengths = [edge.length for edge in self.sim.edge_data.values() if edge.length > 0]
        if not edge_lengths:
            return 1

        min_edge_length = min(edge_lengths)

        max_active_speed = max((agent.speed for agent in self.sim.agents), default=0.0)
        max_possible_speed = max(DEFAULT_AGENT_SPEED_PX * 1.10, max_active_speed)
        if max_possible_speed <= 0:
            return 1

        max_dt = (self._max_edge_fraction_per_micro_step * min_edge_length) / max_possible_speed
        if max_dt <= 0:
            return 1

        micro_steps = max(1, math.ceil(simulated_seconds_per_step / max_dt))
        return min(micro_steps, self._max_micro_steps_per_step)

    """Logic for handling button press events"""
    def _handle_button_event(self, event) -> None:
        if event.ui_element == self.control_panel.reset_button:
            self.reset_sim()
        elif event.ui_element == self.control_panel.add_agent_button:
            self.add_agent()
        elif event.ui_element == self.control_panel.pause_button:
            self.toggle_pause()
        elif event.ui_element == self.control_panel.queue_ratio_confirm_button:
            self._apply_queue_ratio_entries()
        elif event.ui_element == self.control_panel.parametertuning_button:
            self._setup_parameter_tuning_grid()

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

        # Run discrete simulation steps from a speed-scaled budget.
        # 1.0x means 1 simulated second progresses per 1 real second.
        if not self.sim.paused:
            # Clamp frame dt to avoid giant catch-up jumps after hiccups/focus loss.
            effective_dt = min(dt, self._max_frame_dt_for_steps)

            simulated_seconds_per_step = self.sim.minutes_per_step * 60.0
            if simulated_seconds_per_step > 0:
                self._step_accumulator += (
                    effective_dt * self.simulation_speed / simulated_seconds_per_step
                )

            steps_available = int(self._step_accumulator)
            # Use an adaptive cap so high speeds are not throttled by a low fixed cap.
            adaptive_cap = min(self._max_steps_hard_cap, max(8, int(self.simulation_speed) + 8))
            steps_to_run = min(steps_available, adaptive_cap)
            if steps_to_run > 0:
                self._step_accumulator -= steps_to_run
                fixed_dt = simulated_seconds_per_step
                for _ in range(steps_to_run):
                    micro_steps = self._compute_micro_steps(fixed_dt)
                    micro_dt = fixed_dt / micro_steps
                    for _ in range(micro_steps):
                        self.sim.step(micro_dt)

        self.mouse_pos = pygame.mouse.get_pos()
        if self.mouse_pos[0] < SIM_W:
            self.tooltip_node = self.sim.node_at_position(self.mouse_pos)
        else:
            self.tooltip_node = None

        self._commit_blurred_text_entries()
        self.control_panel.pause_button.set_text(
            "Resume" if self.sim.paused else "Pause"
        )
        self.control_panel.clock_label.set_text(
            f"Time: {self.sim.get_time_str()}"
        )

    def draw(self) -> None:
        if DISABLE_GRAPHICS:
            return
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

    def toggle_parameter_tuning(self) -> None:
        self.toggle_pause()

        
