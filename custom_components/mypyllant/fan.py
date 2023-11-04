from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)
from myPyllant.models import (
    System,
    Ventilation,
    VentilationFanStageType,
    VentilationOperationMode,
)

from . import SystemCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_FAN_STAGE_TYPE_OPTIONS = [
    selector.SelectOptionDict(value=v.value, label=v.value.title())
    for v in VentilationFanStageType
]

FAN_SPEED_OPTIONS = [
    VentilationOperationMode.REDUCED,
    VentilationOperationMode.NORMAL,
]


async def async_setup_entry(
    hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the climate platform."""
    coordinator: SystemCoordinator = hass.data[DOMAIN][config.entry_id][
        "system_coordinator"
    ]
    if not coordinator.data:
        _LOGGER.warning("No system data, skipping climate")
        return

    ventilation_entities: list[FanEntity] = []

    for index, system in enumerate(coordinator.data):
        for ventilation_index, _ in enumerate(system.ventilation):
            ventilation_entities.append(
                VentilationFan(
                    index,
                    ventilation_index,
                    coordinator,
                )
            )

    async_add_entities(ventilation_entities)


class VentilationFan(CoordinatorEntity, FanEntity):
    coordinator: SystemCoordinator
    _attr_preset_modes = [str(k) for k in VentilationOperationMode]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_speed_count = len(FAN_SPEED_OPTIONS)

    def __init__(
        self,
        system_index: int,
        ventilation_index: int,
        coordinator: SystemCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self.system_index = system_index
        self.ventilation_index = ventilation_index
        self.entity_id = f"{DOMAIN}.ventilation_{ventilation_index}"

    @property
    def system(self) -> System:
        return self.coordinator.data[self.system_index]

    @property
    def ventilation(self) -> Ventilation:
        return self.system.ventilation[self.ventilation_index]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"ventilation{self.ventilation.index}")},
            name=self.name,
            manufacturer=self.system.brand_name,
        )

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_climate_ventilation_{self.ventilation_index}"

    @property
    def name(self) -> str:
        return [d for d in self.system.devices if d.type == "ventilation"][
            0
        ].name_display

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attr = {
            "time_program_ventilation": self.ventilation.time_program_ventilation,
        }
        return attr

    @property
    def supported_features(self) -> FanEntityFeature:
        """Return the list of supported features."""
        return FanEntityFeature.PRESET_MODE | FanEntityFeature.SET_SPEED

    async def async_turn_on(
        self,
        speed: str | None = None,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not preset_mode:
            preset_mode = str(VentilationOperationMode.TIME_CONTROLLED)
        await self.coordinator.api.set_ventilation_operation_mode(
            self.ventilation,
            VentilationOperationMode(preset_mode),
        )
        await self.coordinator.async_request_refresh_delayed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.api.set_ventilation_operation_mode(
            self.ventilation,
            VentilationOperationMode.OFF,
        )
        await self.coordinator.async_request_refresh_delayed()

    @property
    def is_on(self) -> bool | None:
        return (
            self.ventilation.operation_mode_ventilation != VentilationOperationMode.OFF
        )

    @property
    def preset_mode(self) -> str | None:
        return (
            str(self.ventilation.operation_mode_ventilation)
            if self.ventilation.operation_mode_ventilation
            else None
        )

    async def async_set_preset_mode(self, preset_mode):
        await self.coordinator.api.set_ventilation_operation_mode(
            self.ventilation,
            VentilationOperationMode(preset_mode),
        )
        await self.coordinator.async_request_refresh_delayed()

    @property
    def percentage(self) -> int | None:
        # See https://developers.home-assistant.io/docs/core/entity/fan#set-speed-percentage
        if (
            self.ventilation.operation_mode_ventilation
            == VentilationOperationMode.TIME_CONTROLLED
        ):
            return 100
        elif (
            self.ventilation.operation_mode_ventilation == VentilationOperationMode.OFF
        ):
            return 0
        else:
            return ordered_list_item_to_percentage(
                FAN_SPEED_OPTIONS,
                self.ventilation.operation_mode_ventilation,
            )

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.coordinator.api.set_ventilation_operation_mode(
                self.ventilation,
                VentilationOperationMode.OFF,
            )
        else:
            mode = percentage_to_ordered_list_item(FAN_SPEED_OPTIONS, percentage)
            await self.coordinator.api.set_ventilation_operation_mode(
                self.ventilation,
                mode,
            )
        await self.coordinator.async_request_refresh_delayed()
