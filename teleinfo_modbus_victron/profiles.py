"""Explicit meter profile selection; never expose two identities at one unit."""
from . import abb_b21, em24


def get_profile(name):
    try:
        return {"em24": em24, "abb_b21": abb_b21}[name]
    except KeyError as exc:
        raise ValueError("meter_profile must be em24 or abb_b21") from exc
