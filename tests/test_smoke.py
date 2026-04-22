"""Smoke tests for project foundation."""

import unittest

from app.main import app


class HealthEndpointTests(unittest.TestCase):
    def test_health_route_is_registered(self) -> None:
        paths = {
            path
            for route in app.routes
            if isinstance((path := getattr(route, "path", None)), str)
        }
        self.assertIn("/health", paths)
