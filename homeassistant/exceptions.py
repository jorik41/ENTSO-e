"""Exception stubs for Home Assistant tests."""


class HomeAssistantError(Exception):
    """Base class for Home Assistant errors."""


class ServiceValidationError(HomeAssistantError):
    """Exception raised for invalid service calls."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.translation_domain = kwargs.get("translation_domain")
        self.translation_key = kwargs.get("translation_key")
        self.translation_placeholders = kwargs.get("translation_placeholders", {})
