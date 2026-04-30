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

    def test_external_static_page(self):
        """Verify the static test page is accessible and has required structure."""
        response = requests.get(f"{self.CHALLENGE_URL}/static.html", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text
        self.assertIn('<!DOCTYPE html>', content)
        self.assertIn('static-detector.js', content)
        self.assertIn('shared.js', content)
        self.assertIn('Detection Results', content)
        self.assertIn('window.lastStaticResults', content)

    def test_external_interactions_page(self):
        """Verify the interactions test page is accessible and has required structure."""
        response = requests.get(f"{self.CHALLENGE_URL}/interactions.html", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text
        self.assertIn('<!DOCTYPE html>', content)
        self.assertIn('interactions-detector.js', content)
        self.assertIn('shared.js', content)
        self.assertIn('Login Form', content)
        self.assertIn('window.lastInteractionResults', content)

        # Check form elements
        self.assertIn('id="email"', content)
        self.assertIn('id="password"', content)
        self.assertIn('type="submit"', content)

    def test_external_shared_js(self):
        """Verify shared.js is accessible and has required detection functions."""
        response = requests.get(f"{self.CHALLENGE_URL}/js/shared.js", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text

        # Check required functions
        required_functions = [
            'checkBotUserAgent',
            'checkWebdriver',
            'checkPlaywright',
            'checkHeadlessChrome',
            'checkWebGLInconsistent',
            'checkAutomatedWithCDP',
            'checkInconsistentWorkerValues',
            'createResultElement',
        ]

        for func in required_functions:
            self.assertIn(f'function {func}', content, f"{func} should be defined")

        # Check exports
        self.assertIn('window.BotDetectorShared', content)

    def test_external_static_detector_js(self):
        """Verify static-detector.js is accessible and has required structure."""
        response = requests.get(f"{self.CHALLENGE_URL}/js/static-detector.js", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text

        # Check required elements
        self.assertIn('runStaticDetection', content)
        self.assertIn('updateOverallStatus', content)
        self.assertIn('window.StaticDetector', content)

        # Check for test names that should be checked
        self.assertIn('hasBotUserAgent', content)
        self.assertIn('hasWebdriverTrue', content)

    def test_external_interactions_detector_js(self):
        """Verify interactions-detector.js is accessible and has required structure."""
        response = requests.get(f"{self.CHALLENGE_URL}/js/interactions-detector.js", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text

        # Check required elements
        self.assertIn('analyzeCDPMouseLeak', content)
        self.assertIn('analyzeSuperHumanSpeed', content)
        self.assertIn('analyzeSuspiciousBehavior', content)
        self.assertIn('window.InteractionDetector', content)

    def test_external_css(self):
        """Verify CSS file is accessible and has required styles."""
        response = requests.get(f"{self.CHALLENGE_URL}/css/style.css", timeout=10)
        self.assertEqual(response.status_code, 200)

        content = response.text

        # Check required CSS classes
        self.assertIn('.results-grid', content)
        self.assertIn('.result-item', content)
        self.assertIn('.status-badge', content)


if __name__ == "__main__":
    unittest.main()
