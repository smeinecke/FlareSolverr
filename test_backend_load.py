"""Quick smoke test: open a page with the configured backend and verify it loads."""

import os
import sys

# Force headless for CI/container environments
os.environ.setdefault("HEADLESS", "true")

from flaresolverr import backends


def main() -> int:
    backend_name = os.environ.get("DRIVER_BACKEND", "undetected_chromedriver")
    print(f"Testing backend: {backend_name}")

    try:
        backend = backends.get_backend(backend_name)
    except Exception as e:
        print(f"FAIL: could not get backend '{backend_name}': {e}")
        return 1

    driver = None
    try:
        print("Creating driver...")
        driver = backend.create_driver(proxy=None, stealth_mode="off")
        print(f"Driver created: {type(driver).__name__}")

        url = "https://example.com"
        print(f"Navigating to {url}...")
        driver.get(url)

        title = driver.title
        page_source = driver.page_source
        current_url = driver.current_url

        print(f"Current URL: {current_url}")
        print(f"Page title: {title}")
        print(f"Page source length: {len(page_source)}")

        if "Example Domain" in page_source or "Example Domain" in title:
            print("PASS: page loaded successfully.")
            return 0

        print(f"FAIL: expected 'Example Domain' in page, got title={title!r}")
        return 1

    except Exception as e:
        print(f"FAIL: exception during test: {e}")
        return 1

    finally:
        if driver is not None:
            print("Quitting driver...")
            try:
                driver.quit()
            except Exception as e:
                print(f"Warning: driver.quit() raised: {e}")


if __name__ == "__main__":
    sys.exit(main())
