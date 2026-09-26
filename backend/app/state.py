"""Canonical initial world; no historical records or hardware assumptions."""
from datetime import datetime, timezone
from uuid import uuid4


def initial_world():
    return {
        "schema_version": 1, "session_id": str(uuid4()), "revision": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(), "mode": "simulation",
        "game": {"status": "READY", "goal": {"type": "earn_gold", "target": 500, "current": 80}},
        "map": {"width": 100, "height": 100, "locations": {
            "homebase": {"x": 50, "y": 50}, "farm": {"x": 20, "y": 30},
            "lake": {"x": 70, "y": 80}, "market": {"x": 80, "y": 40}}},
        "robots": [{
            "id": robot_id, "name": name,
            "physical": {"online": False, "pose": None, "pose_updated_at": None,
                         "tracking": "UNKNOWN", "battery": None, "blocked": False, "stopped": False},
            "game": {"location": None, "money": 40, "inventory": {}}, "task": None,
        } for robot_id, name in [("robot-a", "Billy"), ("robot-b", "Milo")]],
        "market": {"items": [
            {"id": "seeds", "name": "Wheat Seeds", "buy_price": 5, "sell_price": 2, "stock": None},
            {"id": "wheat", "name": "Wheat", "buy_price": None, "sell_price": 10, "stock": None},
            {"id": "fish", "name": "Fish", "buy_price": None, "sell_price": 12, "stock": None}]},
        "events": [],
    }
