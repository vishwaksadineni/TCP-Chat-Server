import unittest

from canvas_project.server import RateLimiter, sanitize_name


class RateLimiterTests(unittest.TestCase):
    def test_allows_messages_inside_limit(self) -> None:
        limiter = RateLimiter(max_messages=2, window_seconds=10)

        self.assertTrue(limiter.allow(now=1.0))
        self.assertTrue(limiter.allow(now=2.0))

    def test_blocks_messages_over_limit(self) -> None:
        limiter = RateLimiter(max_messages=2, window_seconds=10)

        self.assertTrue(limiter.allow(now=1.0))
        self.assertTrue(limiter.allow(now=2.0))
        self.assertFalse(limiter.allow(now=3.0))

    def test_expires_old_messages(self) -> None:
        limiter = RateLimiter(max_messages=1, window_seconds=10)

        self.assertTrue(limiter.allow(now=1.0))
        self.assertTrue(limiter.allow(now=12.0))


class SanitizeNameTests(unittest.TestCase):
    def test_removes_unsafe_characters(self) -> None:
        self.assertEqual(sanitize_name(" Ada Lovelace! "), "AdaLovelace")

    def test_falls_back_for_empty_names(self) -> None:
        self.assertEqual(sanitize_name(" !!! "), "guest")

    def test_limits_name_length(self) -> None:
        self.assertEqual(len(sanitize_name("a" * 40)), 24)


if __name__ == "__main__":
    unittest.main()
