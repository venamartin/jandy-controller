#!/usr/bin/env python3
"""Test runner for validating Jandy RS485 protocol parsing and decoding."""

import unittest
from jandy import JandyPacket, calculate_checksum, validate_checksum


class TestJandyProtocol(unittest.TestCase):
    def test_checksum_calculations(self):
        # DEST=0x50, CMD=0x11, PERCENT=0xFF (Boost)
        # Packet: DLE, STX, 0x50, 0x11, 0xFF, CHKSUM, DLE, ETX
        packet = bytes([0x10, 0x02, 0x50, 0x11, 0xFF, 0x72, 0x10, 0x03])
        self.assertEqual(calculate_checksum(packet), 0x72)
        self.assertTrue(validate_checksum(packet))

    def test_decode_status_water_temp_available(self):
        # 0x0C Ping/Status containing:
        # FLAGS=0x01, POOL_SP=80 (0x50), SPA_SP=100 (0x64), WATER_TEMP=78 (0x4E)
        # Checksum = 0x10+0x02+0x68+0x0C+0x01+0x50+0x64+0x4E = 393 => 393 & 0xFF = 137 (0x89)
        raw_bytes = bytes([0x10, 0x02, 0x68, 0x0C, 0x01, 0x50, 0x64, 0x4E, 0x89, 0x10, 0x03])
        packet, _ = JandyPacket.parse(list(raw_bytes))
        
        self.assertIsNotNone(packet)
        self.assertTrue(packet.valid)
        self.assertEqual(packet.cmd, 0x0C)
        
        details = packet.decode_details()
        self.assertEqual(details["pool_sp"], 80)
        self.assertEqual(details["spa_sp"], 100)
        self.assertEqual(details["water_temp"], 78)
        self.assertEqual(details["formatted_water_temp"], "78°F")
        self.assertEqual(details["formatted_pool_sp"], "80°F")
        
        self.assertEqual(
            packet.summary(),
            "Jandy (CMD_JXI_PING), DEST=JXi Heater (0x68), len=4, POOL_SP=80°F SPA_SP=100°F WATER_TEMP=78°F"
        )

    def test_decode_status_water_temp_unavailable(self):
        # 0x0C Ping/Status containing:
        # FLAGS=0x01, POOL_SP=80 (0x50), SPA_SP=100 (0x64), WATER_TEMP=255 (0xFF)
        # Checksum = 0x10+0x02+0x68+0x0C+0x01+0x50+0x64+0xFF = 570 => 570 & 0xFF = 58 (0x3A)
        raw_bytes = bytes([0x10, 0x02, 0x68, 0x0C, 0x01, 0x50, 0x64, 0xFF, 0x3A, 0x10, 0x03])
        packet, _ = JandyPacket.parse(list(raw_bytes))
        
        self.assertIsNotNone(packet)
        self.assertTrue(packet.valid)
        
        details = packet.decode_details()
        self.assertEqual(details["water_temp"], 255)
        self.assertEqual(details["formatted_water_temp"], "N/A")
        
        self.assertEqual(
            packet.summary(),
            "Jandy (CMD_JXI_PING), DEST=JXi Heater (0x68), len=4, POOL_SP=80°F SPA_SP=100°F WATER_TEMP=N/A"
        )

    def test_decode_epump_status(self):
        # 0x1F status packet from Pump showing:
        # orig_cmd=0x45, echoed watts_set=0x00 0x05, actual watts=0xB9 0x07 (Little-Endian = 0x07B9 = 1977 Watts)
        # Checksum = 0x10+0x02+0x00+0x1F+0x45+0x00+0x05+0xB9+0x07 = 315 => 315 & 0xFF = 59 (0x3B)
        raw_bytes = bytes([0x10, 0x02, 0x00, 0x1F, 0x45, 0x00, 0x05, 0xB9, 0x07, 0x3B, 0x10, 0x03])
        packet, _ = JandyPacket.parse(list(raw_bytes))
        
        self.assertIsNotNone(packet)
        self.assertTrue(packet.valid)
        
        details = packet.decode_details()
        self.assertEqual(details["orig_cmd"], 0x45)
        self.assertEqual(details["watts"], 1977)
        
        self.assertEqual(
            packet.summary(),
            "Jandy (CMD_EPUMP_STATUS), DEST=Master/Controller, len=5, RPM=None WATTS=1977"
        )


if __name__ == "__main__":
    unittest.main()
