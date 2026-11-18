import tomllib
from pathlib import Path

from app.simulator.schemas import SimulationConfig

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "nexora_simulation.toml"
)


def load_simulation_config(path: Path = DEFAULT_CONFIG_PATH) -> SimulationConfig:
    with path.open("rb") as config_file:
        contents = tomllib.load(config_file)
    simulation_settings = contents.get("simulation")
    if not isinstance(simulation_settings, dict):
        raise ValueError("Simulation config must contain a [simulation] table.")
    return SimulationConfig.model_validate(simulation_settings)
