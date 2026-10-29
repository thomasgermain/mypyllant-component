from unittest.mock import Mock

import pytest
from homeassistant.helpers.entity_registry import DATA_REGISTRY, EntityRegistry
from homeassistant.loader import DATA_COMPONENTS, DATA_INTEGRATIONS

from custom_components.mypyllant import SystemCoordinator
from myPyllant.api import MyPyllantAPI
from myPyllant.models import AmbisenseDevice, System
from myPyllant.tests.generate_test_data import DATA_DIR
from myPyllant.tests.utils import list_test_data, load_test_data

from custom_components.mypyllant.binary_sensor import (
    AmbisenseDeviceLowBattery,
    AmbisenseDeviceUnreachable,
    CircuitIsCoolingAllowed,
    ControlError,
    ControlOnline,
    SystemControlEntity,
    async_setup_entry,
    ZoneIsManualCoolingActive,
)
from custom_components.mypyllant.utils import (
    AmbisenseCoordinatorEntity,
    CircuitEntity,
)
from custom_components.mypyllant.const import DOMAIN
from tests.utils import get_config_entry

AmbisenseDeviceSensor = AmbisenseDeviceLowBattery | AmbisenseDeviceUnreachable


@pytest.mark.parametrize("test_data", list_test_data(only_with_systems=True))
async def test_async_setup_binary_sensors(
    hass,
    mypyllant_aioresponses,
    mocked_api: MyPyllantAPI,
    system_coordinator_mock,
    test_data,
):
    hass.data[DATA_COMPONENTS] = {}
    hass.data[DATA_INTEGRATIONS] = {}
    hass.data[DATA_REGISTRY] = EntityRegistry(hass)
    with mypyllant_aioresponses(test_data) as _:
        config_entry = get_config_entry()
        system_coordinator_mock.data = (
            await system_coordinator_mock._async_update_data()
        )
        hass.data[DOMAIN] = {
            config_entry.entry_id: {"system_coordinator": system_coordinator_mock}
        }
        mock = Mock(return_value=None)
        await async_setup_entry(hass, config_entry, mock)
        mock.assert_called_once()
        assert len(mock.call_args.args[0]) > 0

        await mocked_api.aiohttp_session.close()


@pytest.mark.parametrize("test_data", list_test_data(only_with_systems=True))
async def test_system_binary_sensors(
    mypyllant_aioresponses, mocked_api: MyPyllantAPI, system_coordinator_mock, test_data
):
    with mypyllant_aioresponses(test_data) as _:
        system_coordinator_mock.data = (
            await system_coordinator_mock._async_update_data()
        )
        system = SystemControlEntity(0, system_coordinator_mock)
        assert isinstance(system.device_info, dict)

        circuit = CircuitEntity(0, 0, system_coordinator_mock)
        assert isinstance(circuit.device_info, dict)
        assert isinstance(circuit.system, System)

        assert isinstance(ControlError(0, system_coordinator_mock).is_on, bool)
        assert isinstance(ControlError(0, system_coordinator_mock).name, str)
        assert ControlOnline(0, system_coordinator_mock).is_on is True
        assert isinstance(ControlOnline(0, system_coordinator_mock).name, str)
        # TODO: May  moved to zones, see no_cooling.yaml
        # assert isinstance(
        #    CircuitIsCoolingAllowed(0, 0, system_coordinator_mock).is_on, bool
        # )
        assert isinstance(
            CircuitIsCoolingAllowed(0, 0, system_coordinator_mock).name, str
        )
        await mocked_api.aiohttp_session.close()


async def test_control_error(
    mypyllant_aioresponses,
    mocked_api: MyPyllantAPI,
    system_coordinator_mock: SystemCoordinator,
):
    test_data = load_test_data(DATA_DIR / "ambisense2.yaml")
    with mypyllant_aioresponses(test_data) as _:
        system_coordinator_mock.data = (
            await system_coordinator_mock._async_update_data()
        )
        control_error = ControlError(0, system_coordinator_mock)
        assert control_error.is_on
        await mocked_api.aiohttp_session.close()


async def test_is_manual_cooling_active(
    mypyllant_aioresponses,
    mocked_api: MyPyllantAPI,
    system_coordinator_mock: SystemCoordinator,
):
    test_data = load_test_data(DATA_DIR / "ventilation")
    with mypyllant_aioresponses(test_data) as _:
        system_coordinator_mock.data = (
            await system_coordinator_mock._async_update_data()
        )
        manual_cooling = ZoneIsManualCoolingActive(0, 0, system_coordinator_mock)
        assert not manual_cooling.is_on
        await mocked_api.aiohttp_session.close()


async def _setup_ambisense_device_entities(
    hass, system_coordinator_mock: SystemCoordinator
) -> list[AmbisenseDeviceSensor]:
    hass.data[DATA_COMPONENTS] = {}
    hass.data[DATA_INTEGRATIONS] = {}
    hass.data[DATA_REGISTRY] = EntityRegistry(hass)
    config_entry = get_config_entry()
    system_coordinator_mock.data = await system_coordinator_mock._async_update_data()
    # Keep the coordinator's own entry, needed for later refreshes
    hass.data[DOMAIN][config_entry.entry_id] = {
        "system_coordinator": system_coordinator_mock
    }
    mock = Mock(return_value=None)
    await async_setup_entry(hass, config_entry, mock)
    return [e for e in mock.call_args.args[0] if isinstance(e, AmbisenseDeviceSensor)]


def _ambisense_devices(system: System) -> list[AmbisenseDevice]:
    return [d for r in system.ambisense_rooms for d in r.room_configuration.devices]


async def test_ambisense_device_state_follows_coordinator_update(
    hass,
    mypyllant_aioresponses,
    mocked_api: MyPyllantAPI,
    system_coordinator_mock: SystemCoordinator,
):
    test_data = load_test_data(DATA_DIR / "ambisense2.yaml")
    with mypyllant_aioresponses(test_data) as _:
        entities = await _setup_ambisense_device_entities(hass, system_coordinator_mock)
        assert entities

        # A coordinator refresh replaces coordinator.data with new objects
        system_coordinator_mock.data = (
            await system_coordinator_mock._async_update_data()
        )
        for device in _ambisense_devices(system_coordinator_mock.data[0]):
            device.low_bat = True
            device.unreach = True

        for entity in entities:
            assert entity.available
            if isinstance(entity, AmbisenseDeviceLowBattery):
                assert entity.is_on is True
            else:
                assert isinstance(entity, AmbisenseDeviceUnreachable)
                assert entity.is_on is False
        await mocked_api.aiohttp_session.close()


async def test_ambisense_device_unavailable_when_missing(
    hass,
    mypyllant_aioresponses,
    mocked_api: MyPyllantAPI,
    system_coordinator_mock: SystemCoordinator,
):
    test_data = load_test_data(DATA_DIR / "ambisense2.yaml")
    with mypyllant_aioresponses(test_data) as _:
        entities = await _setup_ambisense_device_entities(hass, system_coordinator_mock)
        unique_ids = [e.unique_id for e in entities]

        system_coordinator_mock.data = (
            await system_coordinator_mock._async_update_data()
        )
        rooms = system_coordinator_mock.data[0].ambisense_rooms
        # Device removed from its room, and a whole room gone
        rooms[0].room_configuration.devices = []
        del rooms[1]

        missing = {
            e.sgtin
            for e in entities
            if e.sgtin
            not in {
                d.sgtin for d in _ambisense_devices(system_coordinator_mock.data[0])
            }
        }
        assert len(missing) == 2
        for entity in entities:
            if entity.sgtin in missing:
                assert entity.available is False
                assert entity.device is None
                assert entity.is_on is None
                # Properties read by Home Assistant while unavailable must not raise
                assert isinstance(entity.name, str)
                assert isinstance(entity.device_info, dict)
            else:
                assert entity.available is True
        assert [e.unique_id for e in entities] == unique_ids

        missing_room = AmbisenseCoordinatorEntity(0, 99, system_coordinator_mock)
        assert missing_room.available is False
        assert isinstance(missing_room.name_prefix, str)
        await mocked_api.aiohttp_session.close()
