"""
Unit tests for bot detection challenge pages.

These tests verify that the challenge pages at https://smeinecke.github.io/bot-web-challenge/
are accessible and have the expected structure.

The challenge files are maintained in a separate repository:
https://github.com/smeinecke/bot-web-challenge
"""

import unittest
import requests


class TestExternalChallenge(unittest.TestCase):
    """Test the external challenge at https://smeinecke.github.io/bot-web-challenge/"""

    CHALLENGE_URL = "https://smeinecke.github.io/bot-web-challenge"

    def test_external_challenge_accessible(self):
        """Verify the external challenge is accessible."""
        response = requests.get(self.CHALLENGE_URL, timeout=10)
        self.assertEqual(response.status_code, 200)
        self.assertIn('<!DOCTYPE html>', response.text)
        self.assertIn('Bot Detection Challenge', response.text)

    def test_external_static_page(self):
        """Verify the static test page is accessible and has required structure."""
        response = requests.get(f"{self.CHALLENGE_URL}/static.html", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text
        self.assertIn('<!DOCTYPE html>', content)
        self.assertIn('Static Fingerprinting Test', content)
        self.assertIn('Detection Results', content)
        self.assertIn('status-badge', content)
        self.assertIn('<script type="module"', content)
        self.assertIn('assets/', content)

    def test_external_interactions_page(self):
        """Verify the interactions test page is accessible and has required structure."""
        response = requests.get(f"{self.CHALLENGE_URL}/interactions.html", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text
        self.assertIn('<!DOCTYPE html>', content)
        self.assertIn('Interaction-Based Detection', content)
        self.assertIn('Login Form', content)
        self.assertIn('<script type="module"', content)
        self.assertIn('assets/', content)

        # Check form elements
        self.assertIn('id="email"', content)
        self.assertIn('id="password"', content)
        self.assertIn('type="submit"', content)


if __name__ == "__main__":
    unittest.main()
