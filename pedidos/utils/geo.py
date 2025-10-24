# pedidos/utils/geo.py
import math
from django.conf import settings

def _to_float(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi/2)**2
         + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2)
    return 2*R*math.asin(math.sqrt(a))

def distance_from_store(lat, lng):
    store = getattr(settings, "STORE_COORDS", {"lat": 0.0, "lng": 0.0})
    return haversine_km(
        _to_float(lat), _to_float(lng),
        _to_float(store["lat"]), _to_float(store["lng"])
    )

def is_inside_radius(lat, lng):
    radius = float(getattr(settings, "DELIVERY_RADIUS_KM", 3.0))
    return distance_from_store(lat, lng) <= radius
