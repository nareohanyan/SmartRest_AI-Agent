"""Smoke tests for project foundation."""

import unittest

from app.main import app


class HealthEndpointTests(unittest.TestCase):
    def test_health_route_is_registered(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertIn("/health", paths)
