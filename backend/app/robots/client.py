"""One-character BLE transport. No game state or navigation decisions."""

import asyncio
import logging
import time


class BleController:
    def __init__(self, config, *, client_factory=None, scanner=None, clock=time.monotonic):
        self.config = config
        self.client_factory = client_factory
        self.scanner = scanner
        self.clock = clock
        self.client = None
        self.fault = False
        self.last_command = None
        self.last_sent = float('-inf')

    @property
    def connected(self):
        return bool(self.client and self.client.is_connected and not self.fault)

    def _disconnected(self, _client):
        self.fault = True
        logging.error('BLE disconnected: motion disabled. Firmware must stop motors on link loss.')

    async def connect(self):
        if not self.config.ble_device or not self.config.ble_characteristic:
            raise ValueError('Set ble_device and ble_characteristic from the working BLE script first')
        if self.client_factory is None:
            from bleak import BleakClient, BleakScanner
            self.client_factory, self.scanner = BleakClient, BleakScanner
        wanted = self.config.ble_device
        if self.config.ble_direct_address:
            device = wanted
        else:
            devices = await self.scanner.discover(timeout=5)
            device = next((d for d in devices if d.name == wanted or d.address == wanted), None)
        if device is None:
            raise RuntimeError(f'BLE device {wanted!r} not found')
        self.client = self.client_factory(device, disconnected_callback=self._disconnected)
        await asyncio.wait_for(self.client.connect(), timeout=15)
        await self.send('S', force=True)

    async def send(self, command: str, *, force=False):
        if command not in ('F', 'B', 'L', 'R', 'S'):
            raise ValueError('Invalid robot command')
        if force and command != 'S':
            raise ValueError('Only stop may bypass the command rate limit')
        if not self.connected:
            raise RuntimeError('BLE unavailable; restart and re-arm after reconnecting')
        now = self.clock()
        elapsed = now - self.last_sent
        immediate_stop = command == 'S' and self.last_command != 'S'
        if not force and not immediate_stop:
            if elapsed < 1 / self.config.command_hz:
                return False
            if command == self.last_command and elapsed < self.config.refresh_seconds:
                return False
        try:
            await asyncio.wait_for(self.client.write_gatt_char(
                self.config.ble_characteristic, command.encode('ascii'),
                response=self.config.ble_write_response,
            ), timeout=.3)
        except Exception:
            self.fault = True
            raise
        self.last_command, self.last_sent = command, self.clock()
        logging.info('BLE %s sent %s', self.config.ble_device, command)
        return True

    async def close(self):
        if self.client is None:
            return
        try:
            if self.client.is_connected:
                # Best effort even after a write failure; never send motion here.
                await asyncio.wait_for(self.client.write_gatt_char(
                    self.config.ble_characteristic, b'S',
                    response=self.config.ble_write_response,
                ), timeout=.3)
        except Exception as error:
            logging.error('Could not deliver final STOP: %s', error)
        finally:
            try:
                await asyncio.wait_for(self.client.disconnect(), timeout=2)
            except Exception as error:
                logging.error('BLE disconnect failed: %s', error)
