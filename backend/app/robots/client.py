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

    async def connect(self, *, device=None):
        if not self.config.ble_device or not self.config.ble_characteristic:
            raise ValueError('Set ble_device and ble_characteristic from the working BLE script first')
        if self.client_factory is None:
            from bleak import BleakClient, BleakScanner
            self.client_factory, self.scanner = BleakClient, BleakScanner
        wanted = self.config.ble_device
        if device is not None:
            logging.info('BLE connecting to %r (pre-resolved as %s)', wanted, device.address)
        else:
            logging.info('BLE connecting to %r (%s)', wanted,
                         'direct identifier' if self.config.ble_direct_address else 'discovery')
            if self.config.ble_direct_address:
                device = wanted
            else:
                devices = await self.scanner.discover(timeout=5)
                device = next((d for d in devices if d.name == wanted or d.address == wanted), None)
        if device is None:
            raise RuntimeError(f'BLE device {wanted!r} not found')
        self.client = self.client_factory(device, disconnected_callback=self._disconnected)
        try:
            await asyncio.wait_for(self.client.connect(), timeout=30)
        except Exception as error:
            self.fault = True
            raise RuntimeError(
                f'BLE connection failed for {wanted!r}: {type(error).__name__}: {error!r}. '
                'Connection limit is 30s. Check this laptop\'s device ID and close other controllers.'
            ) from error
        logging.info('BLE %s connected; sending initial STOP', wanted)
        # Startup sends only STOP, before any robot can arm. Match the successful
        # connection-only diagnostic without relaxing deadlines during motion.
        await self._write('S', timeout=5, stage='initial STOP')

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
        await self._write(command, timeout=.3, stage=f'command {command}')
        return True

    async def _write(self, command, *, timeout, stage):
        try:
            await asyncio.wait_for(self.client.write_gatt_char(
                self.config.ble_characteristic, command.encode('ascii'),
                response=self.config.ble_write_response,
            ), timeout=timeout)
        except Exception as error:
            self.fault = True
            detail = (f'BLE {self.config.ble_device!r} {stage} failed '
                      f'({type(error).__name__}, limit {timeout}s): {error!r}; '
                      f'characteristic={self.config.ble_characteristic}, '
                      f'response={self.config.ble_write_response}')
            if isinstance(error, TimeoutError):
                raise TimeoutError(detail) from error
            raise RuntimeError(detail) from error
        self.last_command, self.last_sent = command, self.clock()
        logging.info('BLE %s sent %s', self.config.ble_device, command)

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
