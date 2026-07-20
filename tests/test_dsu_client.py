import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
import dsu_client


def make_motion_response(
    *,
    timestamp_us=1_000_000,
    acceleration=(0.0, 0.0, 1.0),
    gyroscope=(0.0, 0.0, 0.0),
):
    # The wire order is pitch, yaw, roll (LegionGoSGyroDSU's legion-hid
    # source sends these unswapped).
    payload = dsu_client.CONTROLLER_DATA.pack(
        0,
        2,
        2,
        1,
        b"\x01\x02\x03\x04\x05\x06",
        5,
        1,
        17,
        b"\0" * 32,
        timestamp_us,
        *acceleration,
        *gyroscope,
    )
    packet = bytearray(
        dsu_client.HEADER.pack(
            dsu_client.DSU_SERVER_MAGIC,
            dsu_client.DSU_VERSION,
            len(payload) + 4,
            0,
            1234,
            dsu_client.DSU_EVENT_ACTUAL_CONTROLLER_DATA,
        )
        + payload
    )
    struct.pack_into("<I", packet, 8, dsu_client._packet_crc(packet))
    return bytes(packet)


class DSUPacketTests(unittest.TestCase):
    def test_subscription_has_expected_header_payload_and_crc(self):
        packet = dsu_client.make_subscription_packet(0x12345678)
        magic, version, size, crc, client_id, event = dsu_client.HEADER.unpack_from(packet)

        self.assertEqual(magic, b"DSUC")
        self.assertEqual(version, 1001)
        self.assertEqual(size, len(packet) - 16)
        self.assertEqual(client_id, 0x12345678)
        self.assertEqual(event, dsu_client.DSU_EVENT_ACTUAL_CONTROLLER_DATA)
        self.assertEqual(crc, dsu_client._packet_crc(packet))
        self.assertEqual(dsu_client.SUBSCRIPTION.unpack_from(packet, 20), (1, 0, b"\0" * 6))

    def test_decodes_motion_axes_from_dsu_wire_order(self):
        motion = dsu_client.parse_motion_packet(
            make_motion_response(
                acceleration=(1.25, -2.5, 3.75),
                gyroscope=(10.0, 20.0, 30.0),  # pitch, yaw, roll on the wire
            )
        )

        self.assertIsNotNone(motion)
        self.assertEqual(motion.timestamp_us, 1_000_000)
        self.assertEqual(motion.acceleration, (-1.25, -3.75, 2.5))
        scale = dsu_client.DSU_GYRO_DEGREES_SCALE
        self.assertEqual(motion.gyroscope, (-10.0 * scale, 30.0 * scale, 20.0 * scale))

    def test_rejects_corrupted_packet(self):
        packet = bytearray(make_motion_response())
        packet[-1] ^= 0x01
        self.assertIsNone(dsu_client.parse_motion_packet(bytes(packet)))

    def test_rejects_non_server_packet(self):
        packet = bytearray(make_motion_response())
        packet[:4] = b"DSUC"
        struct.pack_into("<I", packet, 8, dsu_client._packet_crc(packet))
        self.assertIsNone(dsu_client.parse_motion_packet(bytes(packet)))


class OrientationFilterTests(unittest.TestCase):
    def test_stationary_device_remains_level(self):
        estimator = dsu_client.OrientationFilter()
        estimator.update(
            dsu_client.MotionData(1_000_000, (0.0, 0.0, 1.0), (0.0, 0.0, 0.0)),
            now=1.0,
        )
        orientation = estimator.update(
            dsu_client.MotionData(1_010_000, (0.0, 0.0, 1.0), (0.0, 0.0, 0.0)),
            now=1.01,
        )
        self.assertAlmostEqual(orientation["roll"], 0.0, places=5)
        self.assertAlmostEqual(orientation["pitch"], 0.0, places=5)
        self.assertAlmostEqual(orientation["yaw"], 0.0, places=5)

    def test_maps_sensor_axes_to_device_rotations(self):
        cases = (
            ((90.0, 0.0, 0.0), "pitch"),
            ((0.0, 90.0, 0.0), "yaw"),
            ((0.0, 0.0, 90.0), "roll"),
        )
        for gyroscope, expected_rotation in cases:
            with self.subTest(rotation=expected_rotation):
                estimator = dsu_client.OrientationFilter()
                estimator.update(
                    dsu_client.MotionData(1_000_000, (0.0, 0.0, 0.0), gyroscope),
                    now=1.0,
                )
                orientation = estimator.update(
                    dsu_client.MotionData(1_100_000, (0.0, 0.0, 0.0), gyroscope),
                    now=1.1,
                )
                self.assertGreater(orientation[expected_rotation], 8.0)
                for rotation in {"roll", "pitch", "yaw"} - {expected_rotation}:
                    self.assertAlmostEqual(orientation[rotation], 0.0, places=5)

    def test_maps_dsu_fields_like_eden_controller_preview(self):
        cases = (
            ((90.0, 0.0, 0.0), "pitch", -1.0),
            ((0.0, 90.0, 0.0), "roll", 1.0),
            ((0.0, 0.0, 90.0), "yaw", 1.0),
        )
        for wire_gyroscope, expected_rotation, direction in cases:
            with self.subTest(rotation=expected_rotation):
                estimator = dsu_client.OrientationFilter()
                first = dsu_client.parse_motion_packet(
                    make_motion_response(
                        timestamp_us=1_000_000,
                        acceleration=(0.0, 0.0, 0.0),
                        gyroscope=wire_gyroscope,
                    )
                )
                second = dsu_client.parse_motion_packet(
                    make_motion_response(
                        timestamp_us=1_100_000,
                        acceleration=(0.0, 0.0, 0.0),
                        gyroscope=wire_gyroscope,
                    )
                )
                self.assertIsNotNone(first)
                self.assertIsNotNone(second)
                estimator.update(first, now=1.0)
                orientation = estimator.update(second, now=1.1)
                self.assertGreater(direction * orientation[expected_rotation], 10.0)

    def test_recenters_orientation(self):
        estimator = dsu_client.OrientationFilter()
        estimator.update(
            dsu_client.MotionData(1_000_000, (0.0, 0.0, 1.0), (30.0, 45.0, 60.0)),
            now=1.0,
        )
        estimator.update(
            dsu_client.MotionData(1_100_000, (0.0, 0.0, 1.0), (30.0, 45.0, 60.0)),
            now=1.1,
        )
        estimator.recenter()
        orientation = estimator.update(
            dsu_client.MotionData(1_100_000, (0.0, 0.0, 1.0), (0.0, 0.0, 0.0)),
            now=1.1,
        )
        for rotation in ("roll", "pitch", "yaw"):
            self.assertAlmostEqual(orientation[rotation], 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
