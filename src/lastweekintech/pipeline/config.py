import yaml
from pathlib import Path
from typing import Any

CONFIG_FILE = Path(__file__).parent.parent / "config.yaml"

def load_config() -> dict[str, Any]:
    """Loads the configuration from config.yaml."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Configuration file not found at {CONFIG_FILE}")
    with open(CONFIG_FILE, 'r') as f:
        config_data = yaml.safe_load(f)
    return config_data if config_data is not None else {}

# Load config on module import to be used by other modules
config = load_config()

if __name__ == '__main__':
    # A simple script to test the config loader
    print("Loading configuration...")
    try:
        cfg = load_config()
        print("Configuration loaded successfully:")
        import json
        print(json.dumps(cfg, indent=2))
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"Error: {e}")
