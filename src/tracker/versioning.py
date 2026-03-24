"""Strategy versioning and iteration management."""

import hashlib
import copy
from pathlib import Path

import yaml


def compute_config_hash(config: dict) -> str:
    """Compute a stable hash of a strategy config."""
    yaml_str = yaml.dump(config, sort_keys=True, default_flow_style=False)
    return hashlib.sha256(yaml_str.encode()).hexdigest()[:12]


def increment_version(version: str) -> str:
    """Increment version string: '1.0' -> '1.1', '2.3' -> '2.4'."""
    parts = version.split(".")
    if len(parts) == 2:
        major, minor = parts
        return f"{major}.{int(minor) + 1}"
    return f"{version}.1"


def iterate_strategy(
    config: dict,
    param_updates: dict | None = None,
    new_version: str | None = None,
) -> dict:
    """Create a new version of a strategy with parameter updates.

    Args:
        config: Original strategy config dict
        param_updates: Dict of param updates, e.g. {"fast_ma.period": 15}
        new_version: Explicit version string, or auto-increment

    Returns:
        New config dict with updated params and version.
    """
    new_config = copy.deepcopy(config)

    # Update version
    old_version = new_config.get("version", "1.0")
    new_config["version"] = new_version or increment_version(old_version)

    # Apply parameter updates
    if param_updates:
        for param_key, value in param_updates.items():
            parts = param_key.split(".")
            if len(parts) == 2:
                indicator_name, param_name = parts
                for indicator in new_config.get("indicators", []):
                    if indicator["name"] == indicator_name:
                        if param_name in indicator.get("params", {}):
                            p = indicator["params"][param_name]
                            if isinstance(p, dict):
                                indicator["params"][param_name]["default"] = value
                            else:
                                indicator["params"][param_name] = value
                            break

            # Handle exit params
            elif param_key == "stop_loss":
                new_config.setdefault("exit", {}).setdefault("stop_loss", {})["value"] = value
            elif param_key == "take_profit":
                new_config.setdefault("exit", {}).setdefault("take_profit", {})["value"] = value
            elif param_key == "trailing_stop":
                new_config.setdefault("exit", {}).setdefault("trailing_stop", {})["value"] = value
            elif param_key == "max_daily_loss":
                new_config.setdefault("risk", {})["max_daily_loss"] = value

    return new_config


def save_strategy_yaml(config: dict, output_dir: str | Path = "strategies/custom") -> Path:
    """Save strategy config to YAML file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    name = config.get("name", "Strategy")
    version = config.get("version", "1.0")
    filename = f"{name}_v{version}.yaml"
    filepath = output_dir / filename

    with open(filepath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return filepath
