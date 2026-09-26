"""Device integration catalog.

Defines supported device types, brands, models, and credential requirements.
Only AquaWiz is implemented in Phase 1B. Other entries are placeholders.
"""

class IntegrationCatalog:
    """Registry of available device integrations."""

    _integrations: dict[str, type] = {}

    @classmethod
    def register(cls, device_type: str, integration_cls: type) -> None:
        cls._integrations[device_type] = integration_cls

    @classmethod
    def get(cls, device_type: str) -> type | None:
        return cls._integrations.get(device_type)

    @classmethod
    def all(cls) -> dict[str, type]:
        return dict(cls._integrations)


DEVICE_TYPES = [
    {"id": "monitor", "label": "Aquarium Monitor", "description": "Water parameter monitoring"},
    {"id": "doser", "label": "Doser", "description": "Chemical dosing automation"},
    {"id": "controller", "label": "Controller", "description": "Tank controller hub"},
    {"id": "switch", "label": "Smart Switch", "description": "Power control"},
    {"id": "light", "label": "Light", "description": "Aquarium lighting"},
    {"id": "ato", "label": "ATO", "description": "Auto top-off"},
    {"id": "heater", "label": "Heater", "description": "Temperature control"},
    {"id": "pump", "label": "Pump", "description": "Water circulation"},
    {"id": "other", "label": "Other", "description": "Other device type"},
]

BRANDS = [
    {
        "id": "aquawiz",
        "label": "AquaWiz",
        "supported": True,
        "credential_fields": ["username", "password"],
        "models": [],
    },
    {
        "id": "kamoer",
        "label": "Kamoer",
        "supported": False,
        "credential_fields": [],
        "models": [],
    },
    {
        "id": "inkbird",
        "label": "INKBIRD",
        "supported": False,
        "credential_fields": [],
        "models": [],
    },
    {
        "id": "generic",
        "label": "Generic",
        "supported": False,
        "credential_fields": [],
        "models": [],
    },
]
