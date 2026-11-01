"""Check available Gemini models and track new additions over time.

Saves model list to data/gemini_models.json with timestamps.
On subsequent runs, highlights models added since the last check.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from google import genai

CACHE_FILE = Path("data/gemini_models.json")


def load_previous():
    """Load previous model snapshot from cache file."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_snapshot(models, timestamp):
    """Save current model list to cache file."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "timestamp": timestamp,
        "models": models,
    }
    # Keep history of previous snapshots (last 10)
    prev = load_previous()
    history = []
    if prev:
        history = prev.get("history", [])
        # Add previous snapshot to history
        history.append({
            "timestamp": prev["timestamp"],
            "model_count": len(prev["models"]),
        })
        history = history[-10:]  # keep last 10
    data["history"] = history

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    # Load API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        # Try config.dat
        try:
            from config import load_config
            cfg = load_config()
            api_key = cfg.get("GEMINI", {}).get("api_key")
        except Exception:
            pass
    if not api_key:
        print("ERROR: No GEMINI_API_KEY found in environment or config.dat")
        return

    client = genai.Client(api_key=api_key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fetch current models
    current_models = {}
    for m in client.models.list():
        current_models[m.name] = {
            "display_name": m.display_name,
            "description": getattr(m, "description", ""),
        }

    # Load previous snapshot
    prev = load_previous()
    prev_names = set(prev["models"].keys()) if prev else set()
    curr_names = set(current_models.keys())

    new_models = sorted(curr_names - prev_names)
    removed_models = sorted(prev_names - curr_names)

    # Display results
    print(f"=== Gemini Models Check — {now} ===")
    print(f"Total models available: {len(current_models)}")
    print()

    if prev:
        print(f"Previous check: {prev['timestamp']} ({len(prev['models'])} models)")
        print()

        if new_models:
            print(f"✅ NEW models since last check ({len(new_models)}):")
            for name in new_models:
                info = current_models[name]
                desc = info.get("description", "")
                if desc and len(desc) > 80:
                    desc = desc[:77] + "..."
                print(f"   + {name:45s}  {info['display_name']}")
                if desc:
                    print(f"     {desc}")
            print()

        if removed_models:
            print(f"❌ REMOVED models since last check ({len(removed_models)}):")
            for name in removed_models:
                info = prev["models"][name]
                print(f"   - {name:45s}  {info['display_name']}")
            print()

        if not new_models and not removed_models:
            print("No changes since last check.")
            print()
    else:
        print("First run — no previous data to compare.")
        print()

    # Print all models grouped by family
    print("─" * 70)
    print("All available models:")
    print("─" * 70)
    families = {}
    for name, info in sorted(current_models.items()):
        # Group by prefix (e.g., "models/gemini-2.5" -> "gemini-2.5")
        short = name.replace("models/", "")
        parts = short.split("-")
        family = "-".join(parts[:2]) if len(parts) >= 2 else parts[0]
        families.setdefault(family, []).append((name, info))

    for family in sorted(families.keys()):
        print(f"\n  [{family}]")
        for name, info in families[family]:
            marker = " 🆕" if name in new_models else ""
            print(f"    {name:50s} {info['display_name']}{marker}")

    # Save snapshot
    save_snapshot(current_models, now)
    print(f"\nSaved to {CACHE_FILE}")


if __name__ == "__main__":
    main()