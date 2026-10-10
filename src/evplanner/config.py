from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "regions.yaml"

def load_region(region_id=None):
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    selected = region_id or config.get("default_region")
    regions = config.get("regions", {})

    if selected not in regions:
        raise ValueError(
            f"Unknown region {selected!r}. Available: {list(regions)}"
        )

    return selected, regions[selected]

def project_path(*parts):
    return ROOT.joinpath(*parts)