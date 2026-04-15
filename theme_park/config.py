from __future__ import annotations

# ==================
# Technical settings
# ==================

# Window configuration and graphics
WIDTH, HEIGHT = 1280, 800
PANEL_W = 320
SIM_W = WIDTH - PANEL_W
FPS = 60
BG = (245, 245, 245)
EDGE_COLOR = (190, 190, 190)
RIDE_COLOR = (220, 90, 90)
INTERSECTION_COLOR = (70, 140, 220)
HOVER_PANEL_BG = (255, 255, 255)
HOVER_BORDER = (30, 30, 30)
TEXT_COLOR = (25, 25, 25)
PANEL_BG = (235, 238, 242)
DEFAULT_AGENT_COLOR = (40, 40, 40)

# Technical simulation settings
RANDOM_SEED = 42

# Simulation clock mapping:
# SIM_TIME_STEPS steps correspond to SIM_TIME_MINUTES simulated minutes.
SIM_TIME_STEPS = 60
SIM_TIME_MINUTES = 1.0

# Simulation distance settings:
# SIM_DISTANCE_PIXELS units correspond to SIM_DISTANCE_METERS real-world meters.
SIM_DISTANCE_PIXELS = 6.7
SIM_DISTANCE_METERS = 1.0

# ===================
# Simulation settings
# ===================
AGENT_SPAWN_PROB = 0.10 # Probability of at least one spawn over 1 simulated second (when park is open)
PARK_OPEN_TIME = 9 * 60  # 9:00 AM in minutes
PARK_CLOSE_TIME = 21 * 60  # 9:00 PM in minutes
DEFAULT_AGENT_SPEED_M = 1.58  # Meters per second

# Global pass ratio targets (add up to 1.0, minimum 0.0)
GLOBAL_FASTPASS_WEIGHT = 0.20
GLOBAL_NORMAL_WEIGHT = 0.60 # Cannot be 0 for this
GLOBAL_SINGLE_RIDER_WEIGHT = 0.20

# Visitor generation defaults
# 1) GROUP_SPAWN_PROB determines whether a spawn is group vs individual.
# 2) If individual, INDIVIDUAL_VISITOR_TYPE_WEIGHTS chooses teen/adult/elderly.
GROUP_SPAWN_PROB = 0.05
INDIVIDUAL_VISITOR_TYPE_WEIGHTS = {
	"teenager": 0.25,
	"adult": 0.40,
	"elderly": 0.20,
}
GROUP_SIZE_MIN = 2
GROUP_SIZE_MAX = 7

# ==================
# Metrics collection
# ==================
METRICS_COLLECT_INTERVAL = 1 # Collect metrics every N simulated minutes

# ================
# Parameter tuning
# ================
CAPACITY_TUNING_STEP = 5
PASS_TYPE_TUNING_STEP = 0.05



# ==================
# DO NOT TOUCH BELOW
# ==================
DEFAULT_AGENT_SPEED_PX = DEFAULT_AGENT_SPEED_M * SIM_DISTANCE_PIXELS / SIM_DISTANCE_METERS