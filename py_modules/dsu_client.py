"""Minimal, read-only DSU client and motion orientation estimator.

The protocol implementation lives outside the Decky plugin lifecycle so it can
be tested independently.  It subscribes only to controller slot zero and never
sends controller input or configuration data.
"""

from __future__ import annotations

import asyncio
import math
import random
import socket
import struct
import time
import zlib
from dataclasses import dataclass
from typing import Awaitable, Callable


DSU_HOST = "127.0.0.1"
DSU_PORT = 26760
DSU_VERSION = 1001
DSU_EVENT_ACTUAL_CONTROLLER_DATA = 0x100002
DSU_CLIENT_MAGIC = b"DSUC"
DSU_SERVER_MAGIC = b"DSUS"

HEADER = struct.Struct("<4sHHIII")
SUBSCRIPTION = struct.Struct("<BB6s")
CONTROLLER_DATA = struct.Struct("<BBBB6sBBI32sQffffff")

SUBSCRIPTION_INTERVAL_SECONDS = 1.0
SOCKET_POLL_SECONDS = 0.25
CONNECTION_TIMEOUT_SECONDS = 2.0
MAX_OUTPUT_RATE_HZ = 30.0
# Eden's Cemuhook client normalizes DSU gyro values so that 312 protocol units
# represent one revolution per second. Preserve that established client
# behavior for a preview that matches the emulator's controller-settings cube.
DSU_GYRO_DEGREES_SCALE = 360.0 / 312.0


@dataclass(frozen=True)
class MotionData:
    timestamp_us: int
    acceleration: tuple[float, float, float]
    gyroscope: tuple[float, float, float]


def _packet_crc(packet: bytes) -> int:
    mutable = bytearray(packet)
    mutable[8:12] = b"\0\0\0\0"
    return zlib.crc32(mutable) & 0xFFFFFFFF


def make_subscription_packet(client_id: int, slot: int = 0) -> bytes:
    """Build a DSU slot subscription packet with a valid IEEE CRC-32."""
    if not 0 <= slot <= 3:
        raise ValueError("DSU controller slot must be between 0 and 3")

    payload = SUBSCRIPTION.pack(1, slot, b"\0" * 6)
    packet = bytearray(
        HEADER.pack(
            DSU_CLIENT_MAGIC,
            DSU_VERSION,
            len(payload) + 4,
            0,
            client_id & 0xFFFFFFFF,
            DSU_EVENT_ACTUAL_CONTROLLER_DATA,
        )
        + payload
    )
    struct.pack_into("<I", packet, 8, _packet_crc(packet))
    return bytes(packet)


def parse_motion_packet(packet: bytes) -> MotionData | None:
    """Validate and decode a DSU controller-data response."""
    expected_size = HEADER.size + CONTROLLER_DATA.size
    if len(packet) != expected_size:
        return None

    magic, version, size, crc, _, event = HEADER.unpack_from(packet)
    if (
        magic != DSU_SERVER_MAGIC
        or version != DSU_VERSION
        or size != len(packet) - 16
        or event != DSU_EVENT_ACTUAL_CONTROLLER_DATA
        or crc != _packet_crc(packet)
    ):
        return None

    fields = CONTROLLER_DATA.unpack_from(packet, HEADER.size)
    slot, state, _, _, _, _, connected = fields[:7]
    if slot != 0 or state != 2 or connected != 1:
        return None

    # Convert the Cemuhook wire convention into the orientation frame used by
    # Eden's controller preview. The accelerometer and gyro transforms look
    # different because DSU names gyro fields by rotations rather than axes.
    pitch, yaw, roll = fields[13], fields[14], fields[15]
    accel_x, accel_y, accel_z = fields[10], fields[11], fields[12]
    return MotionData(
        timestamp_us=fields[9],
        acceleration=(-accel_x, -accel_z, -accel_y),
        gyroscope=(
            -pitch * DSU_GYRO_DEGREES_SCALE,
            roll * DSU_GYRO_DEGREES_SCALE,
            yaw * DSU_GYRO_DEGREES_SCALE,
        ),
    )


class OrientationFilter:
    """Quaternion gyro integration with a gentle accelerometer correction.

    Accelerometers provide roll and pitch but no absolute yaw.  Yaw is therefore
    relative to the most recent recenter action and may drift slowly over time.
    """

    ACCEL_CORRECTION_PER_SECOND = 0.3
    MIN_RELIABLE_ACCEL_G = 0.75
    MAX_RELIABLE_ACCEL_G = 1.25
    MAX_DT_SECONDS = 0.1

    def __init__(self) -> None:
        self._quaternion = (1.0, 0.0, 0.0, 0.0)
        self._last_timestamp_us: int | None = None
        self._last_monotonic: float | None = None
        self._zero_inverse = (1.0, 0.0, 0.0, 0.0)
        self._initialized = False

    @staticmethod
    def _normalized(values: tuple[float, ...]) -> tuple[float, ...]:
        length = math.sqrt(sum(value * value for value in values))
        if length < 1e-9:
            return values
        return tuple(value / length for value in values)

    @staticmethod
    def _euler(q: tuple[float, float, float, float]) -> tuple[float, float, float]:
        w, x, y, z = q
        roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        return tuple(math.degrees(value) for value in (roll, pitch, yaw))

    @staticmethod
    def _from_euler(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
        cr, sr = math.cos(roll / 2), math.sin(roll / 2)
        cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
        cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
        return (
            cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
        )

    @staticmethod
    def _multiply(
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        lw, lx, ly, lz = left
        rw, rx, ry, rz = right
        return (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )

    def _dt(self, timestamp_us: int, now: float) -> float | None:
        dt = None
        if self._last_timestamp_us is not None and timestamp_us > self._last_timestamp_us:
            dt = (timestamp_us - self._last_timestamp_us) / 1_000_000.0
        elif self._last_monotonic is not None:
            dt = now - self._last_monotonic
        self._last_timestamp_us = timestamp_us
        self._last_monotonic = now
        if dt is None or not 0.0 < dt <= self.MAX_DT_SECONDS:
            return None
        return dt

    def update(self, motion: MotionData, now: float | None = None) -> dict[str, float]:
        now = time.monotonic() if now is None else now
        accel_length = math.sqrt(sum(value * value for value in motion.acceleration))
        ax, ay, az = self._normalized(motion.acceleration)
        if not self._initialized and any((ax, ay, az)):
            roll = math.atan2(ay, az)
            pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az))
            self._quaternion = self._from_euler(roll, pitch, 0.0)
            self._initialized = True
        dt = self._dt(motion.timestamp_us, now)
        if dt is not None:
            w, x, y, z = self._quaternion
            gx, gy, gz = (math.radians(value) for value in motion.gyroscope)

            # Predicted gravity in the sensor frame.  The cross product with the
            # measured gravity vector supplies a low-frequency drift correction.
            gravity = (
                2 * (x * z - w * y),
                2 * (w * x + y * z),
                w * w - x * x - y * y + z * z,
            )
            if self.MIN_RELIABLE_ACCEL_G <= accel_length <= self.MAX_RELIABLE_ACCEL_G:
                ex = ay * gravity[2] - az * gravity[1]
                ey = az * gravity[0] - ax * gravity[2]
                ez = ax * gravity[1] - ay * gravity[0]
                gx += self.ACCEL_CORRECTION_PER_SECOND * ex
                gy += self.ACCEL_CORRECTION_PER_SECOND * ey
                gz += self.ACCEL_CORRECTION_PER_SECOND * ez

            derivative = (
                -0.5 * (x * gx + y * gy + z * gz),
                0.5 * (w * gx + y * gz - z * gy),
                0.5 * (w * gy - x * gz + z * gx),
                0.5 * (w * gz + x * gy - y * gx),
            )
            self._quaternion = self._normalized(
                tuple(value + delta * dt for value, delta in zip(self._quaternion, derivative))
            )

        relative = self._normalized(self._multiply(self._zero_inverse, self._quaternion))
        rotation_x, rotation_y, rotation_z = self._euler(relative)
        return {
            "pitch": rotation_x,
            "yaw": rotation_y,
            "roll": rotation_z,
        }

    def recenter(self) -> None:
        w, x, y, z = self._normalized(self._quaternion)
        self._zero_inverse = (w, -x, -y, -z)


class DSUMotionClient:
    """Maintain a DSU subscription and emit throttled orientation updates."""

    def __init__(
        self,
        emit: Callable[[str, dict], Awaitable[None]],
        host: str = DSU_HOST,
        port: int = DSU_PORT,
    ) -> None:
        self._emit = emit
        self._address = (host, port)
        self._client_id = random.SystemRandom().randrange(1, 2**32)
        self._filter = OrientationFilter()
        self._socket: socket.socket | None = None
        self._running = False

    def recenter(self) -> None:
        self._filter.recenter()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)
        self._socket.connect(self._address)
        self._running = True
        subscription = make_subscription_packet(self._client_id)
        last_subscription = 0.0
        last_packet = 0.0
        last_emit = 0.0
        connected = False

        try:
            while self._running:
                now = time.monotonic()
                if now - last_subscription >= SUBSCRIPTION_INTERVAL_SECONDS:
                    await loop.sock_sendall(self._socket, subscription)
                    last_subscription = now

                try:
                    packet = await asyncio.wait_for(
                        loop.sock_recv(self._socket, 2048), SOCKET_POLL_SECONDS
                    )
                except TimeoutError:
                    if connected and time.monotonic() - last_packet > CONNECTION_TIMEOUT_SECONDS:
                        connected = False
                        await self._emit("motion_connection", {"connected": False})
                    continue

                motion = parse_motion_packet(packet)
                if motion is None:
                    continue
                now = time.monotonic()
                last_packet = now
                if not connected:
                    connected = True
                    await self._emit("motion_connection", {"connected": True})
                orientation = self._filter.update(motion, now)
                if now - last_emit >= 1.0 / MAX_OUTPUT_RATE_HZ:
                    await self._emit("motion_sample", orientation)
                    last_emit = now
        finally:
            self._running = False
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            if connected:
                await self._emit("motion_connection", {"connected": False})

    def close(self) -> None:
        self._running = False
