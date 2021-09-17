from homeassistant.helpers.entity import Entity

from custom_components.pik_intercom.const import DATA_ENTITIES, DOMAIN
from custom_components.pik_intercom.api import PikIntercomAPI


class BasePikIntercomEntity(Entity):
    def __init__(self, config_entry_id: str) -> None:
        self._config_entry_id = config_entry_id

    @property
    def api_object(self) -> PikIntercomAPI:
        hass = self.hass
        assert hass, "Home Assistant object not loaded"

        domain_data = self.hass.data.get(DOMAIN)
        assert domain_data, "Domain data is empty"

        api_object = domain_data.get(self._config_entry_id)
        assert api_object, "API object is missing"

        return api_object

    async def async_added_to_hass(self) -> None:
        self.hass.data[DATA_ENTITIES].setdefault(self._config_entry_id, []).append(self)

    async def async_will_remove_from_hass(self) -> None:
        self.hass.data[DATA_ENTITIES].get(self._config_entry_id, []).remove(self)

    @property
    def should_poll(self) -> bool:
        return False
