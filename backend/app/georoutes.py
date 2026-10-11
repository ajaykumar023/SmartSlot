"""TomTom live driving route/ETA adapter. Never synthesizes traffic values.

The backend key stays server-side; route geometry is returned to the requesting
customer's own browser so their map can draw the route. GPS is not persisted.
"""
import math
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class RoutingUnavailable(Exception):
    """Provider unavailable or returned a malformed/unroutable response."""


def estimate_travel(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float, api_key: str = "") -> dict:
    if not api_key.strip():
        raise RoutingUnavailable("TomTom Routing is not configured. Add TOMTOM_ROUTING_API_KEY to backend/.env.")
    for lat, lon in ((origin_lat, origin_lon), (dest_lat, dest_lon)):
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise RoutingUnavailable("Location coordinates are invalid.")
    # Route coordinates must be LATITUDE,LONGITUDE, not GeoJSON lon,lat.
    locations = f"{origin_lat:.6f},{origin_lon:.6f}:{dest_lat:.6f},{dest_lon:.6f}"
    query = urlencode({"key": api_key, "traffic": "true", "travelMode": "car", "routeType": "fastest"})
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{locations}/json?{query}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "AETHERX-SmartSlot/1.0"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.load(response)
        route = payload["routes"][0]
        summary = route["summary"]
        seconds = float(summary["travelTimeInSeconds"])
        meters = float(summary["lengthInMeters"])
        if not (math.isfinite(seconds) and math.isfinite(meters) and seconds >= 0 and meters >= 0):
            raise ValueError("Invalid route summary")
        # TomTom's route leg points are already road geometry, not straight lines.
        points = []
        for leg in route.get("legs", []):
            for point in leg.get("points", []):
                if not points or points[-1] != [point["latitude"], point["longitude"]]:
                    points.append([float(point["latitude"]), float(point["longitude"])])
        # Bound payload size and map rendering cost without changing ETA/distance.
        if len(points) > 600:
            indices = [round(i * (len(points) - 1) / 599) for i in range(600)]
            points = [points[i] for i in indices]
        delay_seconds = summary.get("trafficDelayInSeconds")
        delay_minutes = max(0, math.ceil(float(delay_seconds) / 60)) if delay_seconds is not None else None
        return {
            "eta_minutes": max(1, math.ceil(seconds / 60)),
            "distance_km": round(meters / 1000, 2),
            "source": "tomtom_live_traffic",
            "traffic_aware": True,
            "traffic_delay_minutes": delay_minutes,
            "route_points": points,
            "automatic_rescheduling_allowed": False,
        }
    except (IndexError, KeyError, TypeError, ValueError, HTTPError, URLError, TimeoutError, OverflowError) as exc:
        raise RoutingUnavailable("TomTom live route unavailable. Your appointment is unchanged; please retry later.") from exc
