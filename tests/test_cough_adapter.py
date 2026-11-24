from datetime import datetime
from io import BytesIO
import unittest
import wave

from observe_cough import count_clusters, observe


class CoughAdapterTests(unittest.TestCase):
    def test_clusters_do_not_count_overlapping_frames_twice(self):
        self.assertEqual(count_clusters([0.2, 0.7, 0.9, 0.1, 0.8], 0.5), 2)

    def test_exact_coverage_and_unsigned_counters(self):
        data = BytesIO()
        with wave.open(data, "wb") as w:
            w.setparams((1, 2, 16000, 0, "NONE", "none"))
            w.writeframes(bytes(60 * 32000))
        data.seek(0)
        with wave.open(data, "rb") as stream:
            result = observe(stream, datetime(2026, 1, 1, 8, 59), 0.5, lambda raw: 0.8)
            self.assertEqual(
                (result["count"], result["observedMinutes"], result["reviewed"]),
                (1, 1, False),
            )
            with self.assertRaises(ValueError):
                observe(stream, datetime(2026, 1, 1, 8, 59, 30), 0.5, lambda raw: 0.8)
