sample_fire = {
    "latitude": 34.22,
    "longitude": -118.55,
    "intensity": 0.82
}

sample_wildlife_zones = [
    {
        "name": "Habitat Alpha",
        "latitude": 34.25,
        "longitude": -118.50,
        "species": "Mountain Lion",
        "fire_eta_minutes": 95,
        "response_time_minutes": 40,
        "safety_buffer_minutes": 20,
        "risk": 0.91
    },
    {
        "name": "Habitat Beta",
        "latitude": 34.17,
        "longitude": -118.61,
        "species": "Mule Deer",
        "fire_eta_minutes": 180,
        "response_time_minutes": 55,
        "safety_buffer_minutes": 20,
        "risk": 0.57
    }
]
# Synthetic normalized records for explicit sample mode, never a live fallback.
sample_fire_events = [
    {
        "id": "sample-fire-1", "latitude": 34.22, "longitude": -118.55,
        "observed_at": "2026-10-17T04:00:00Z", "frp_mw": 12.5,
        "source": "NASA FIRMS",
    }
]

sample_wildlife_occurrences = [
    {
        "id": "sample-1", "species": "Mountain Lion", "latitude": 34.25,
        "longitude": -118.50, "observed_at": "2020-05", "dataset_key": None,
        "license": None, "source": "GBIF",
    },
    {
        "id": "sample-2", "species": "Mule Deer", "latitude": 34.17,
        "longitude": -118.61, "observed_at": "2020-06-01", "dataset_key": None,
        "license": None, "source": "GBIF",
    },
]
