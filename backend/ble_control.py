import asyncio
from bleak import BleakScanner, BleakClient

DEVICE_NAME = "WALL-Y"
COMMAND_CHAR_UUID = "abcdefab-1234-5678-1234-abcdefabcdef"


async def main():

    print("Scanning for WALL-Y...")

    devices = await BleakScanner.discover()

    target = None

    for device in devices:
        if device.name == DEVICE_NAME:
            target = device
            break

    if target is None:
        print("WALL-Y not found")
        return

    print("Found WALL-Y")
    print("Connecting...")

    async with BleakClient(target) as client:

        print("Connected!")
        print()
        print("Commands:")
        print("F = Forward")
        print("B = Backward")
        print("L = Left")
        print("R = Right")
        print("S = Stop")
        print("H = Health")
        print("Q = Quit")
        print()

        while True:

            command = input("> ").strip().upper()

            if command == "Q":
                await client.write_gatt_char(
                    COMMAND_CHAR_UUID,
                    b"S"
                )
                print("Stopping and disconnecting...")
                break

            if command not in ["F", "B", "L", "R", "S", "H"]:
                print("Invalid command")
                continue

            await client.write_gatt_char(
                COMMAND_CHAR_UUID,
                command.encode()
            )

            print("Sent:", command)


asyncio.run(main())
