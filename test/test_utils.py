import unittest
from DPyL_utils import ms_to_hms_ms, hms_to_ms, ms_to_hms, is_network_drive, normalize_unc_path

class TestUtils(unittest.TestCase):
    def test_ms_to_hms_ms_and_back(self):
        ms = 3723004
        hms = ms_to_hms_ms(ms)
        self.assertEqual(hms, "01:02:03.004")
        self.assertEqual(hms_to_ms(hms), ms)

    def test_ms_to_hms(self):
        self.assertEqual(ms_to_hms(3723004), "01:02:03.004")

    def test_is_network_drive(self):
        self.assertTrue(is_network_drive(r"\\server\share"))
        self.assertTrue(is_network_drive("//server/share"))
        self.assertFalse(is_network_drive(r"C:\\path"))

    def test_normalize_unc_path(self):
        expected = r"\\server\share"
        self.assertEqual(normalize_unc_path("//server/share"), expected)
        self.assertEqual(normalize_unc_path("/server/share"), expected)
        self.assertEqual(normalize_unc_path("C:/path"), r"C:\path")

if __name__ == '__main__':
    unittest.main()
