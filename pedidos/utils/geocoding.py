# -*- coding: utf-8 -*-
import requests
from django.conf import settings

GOOGLE_GEOCODING_KEY = getattr(settings, "GOOGLE_GEOCODING_KEY", None)

def reverse_geocode(lat, lng, lang="es"):
    """
    Devuelve dict con dirección formateada y componentes básicos.
    Si no hay clave o falla, retorna {} y dejamos que el front siga mostrando coords.
    """
    if not GOOGLE_GEOCODING_KEY:
        return {}

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lng}", "key": GOOGLE_GEOCODING_KEY, "language": lang}

    try:
        r = requests.get(url, params=params, timeout=5)
        j = r.json()
    except Exception:
        return {}

    if j.get("status") != "OK" or not j.get("results"):
        return {}

    res = j["results"][0]
    comps = {t: c.get("long_name")
             for c in res.get("address_components", [])
             for t in c.get("types", [])}

    formatted = res.get("formatted_address", "")
    plus_code = (j.get("plus_code") or {}).get("global_code")

    return {
        "formatted_address": formatted,
        "street": comps.get("route"),
        "street_number": comps.get("street_number"),
        "neighborhood": comps.get("neighborhood") or comps.get("sublocality"),
        "locality": comps.get("locality"),
        "province": comps.get("administrative_area_level_1"),
        "postal_code": comps.get("postal_code"),
        "plus_code": plus_code,
        "map_url": f"https://maps.google.com/?q={lat},{lng}",
    }
