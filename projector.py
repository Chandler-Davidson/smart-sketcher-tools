from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Union

from bleak import BleakClient, BleakScanner

BLE_CHAR_UUID = "0000ffe3-0000-1000-8000-00805f9b34fb"
DEFAULT_DEVICE_NAME = "smART_sketcher2.0"
SEND_IMAGE_COMMAND = bytes([0x01, 0x00, 0x00, 0x00, 0x50, 0x00, 0x01, 0x00])

ProgressCallback = Union[Callable[[int, int], None], Callable[[int, int], Awaitable[None]]]


class DeviceNotFoundError(Exception):
    pass


class ProjectorClient:
    def __init__(
        self,
        ble_char_uuid: str = BLE_CHAR_UUID,
        device_name: str = DEFAULT_DEVICE_NAME,
        line_delay_seconds: float = 0.05,
    ) -> None:
        self.ble_char_uuid = ble_char_uuid
        self.device_name = device_name
        self.line_delay_seconds = line_delay_seconds

    async def discover_address(self) -> str:
        devices = await BleakScanner.discover()
        for device in devices:
            if device.name == self.device_name:
                return device.address
        raise DeviceNotFoundError(f"Could not find nearby device named '{self.device_name}'")

    async def send_image_lines(
        self,
        lines: list[bytearray],
        address: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        if address is None:
            address = await self.discover_address()

        async def _noop_notify(_: int, __: bytearray) -> None:
            return None

        async with BleakClient(address) as client:
            await client.start_notify(self.ble_char_uuid, _noop_notify)
            await client.write_gatt_char(char_specifier=self.ble_char_uuid, data=SEND_IMAGE_COMMAND)

            total = len(lines)
            sent = 0

            for line_data in lines:
                await asyncio.sleep(self.line_delay_seconds)
                await client.write_gatt_char(char_specifier=self.ble_char_uuid, data=line_data)
                sent += 1
                if progress_callback is not None:
                    progress_result = progress_callback(sent, total)
                    if asyncio.iscoroutine(progress_result):
                        await progress_result

        return address
