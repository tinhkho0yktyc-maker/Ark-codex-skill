"""Configurable roaming decisions; independent of Qt and animation speed."""

import math
import random


RANGES = {
    "roaming_activity": (25, 200, 100),
    "roaming_walk_chance": (0, 100, 60),
    "roaming_distance": (20, 500, 160),
    "roaming_pause_min": (2, 120, 2),
    "roaming_pause_max": (2, 120, 5),
}


def normalize_settings(settings):
    result = {}
    for key, (lower, upper, default) in RANGES.items():
        value = settings.get(key, default)
        try:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("nonfinite setting")
            result[key] = max(lower, min(upper, round(value)))
        except (ValueError, TypeError, OverflowError):
            result[key] = default
    result["roaming_pause_max"] = max(result["roaming_pause_min"], result["roaming_pause_max"])
    return result


def pause_seconds(settings, rng=random):
    options = normalize_settings(settings)
    return rng.uniform(options["roaming_pause_min"], options["roaming_pause_max"]) * 100 / options["roaming_activity"]


def choose_action(settings, states, rng=random):
    """Choose an available action, never manufacture a missing Special/Move."""
    options = normalize_settings(settings)
    walk = options["roaming_walk_chance"] if "move" in states else 0
    if walk and rng.random() * 100 < walk:
        return "move"
    rests = [(name, weight) for name, weight in
             (("idle", 55), ("sit", 20), ("interact", 20), ("special", 5)) if name in states]
    if not rests:
        return "idle"
    draw = rng.random() * sum(weight for _, weight in rests)
    for name, weight in rests:
        draw -= weight
        if draw < 0:
            return name
    return rests[-1][0]


def walk_plan(settings, speed, rng=random):
    """A short two-dimensional destination, not perpetual boundary bouncing."""
    options = normalize_settings(settings)
    angle = rng.uniform(0, math.tau)
    dx, dy = math.cos(angle), math.sin(angle) * 0.35
    length = math.hypot(dx, dy)
    direction = (dx / length, dy / length)
    limit = options["roaming_distance"]
    distance = rng.uniform(min(35, limit), limit)
    actual_speed = max(1, speed * rng.uniform(0.8, 1.2))
    return direction, distance, actual_speed
