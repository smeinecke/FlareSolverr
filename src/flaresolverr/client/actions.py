"""ActionQueue for building browser action chains."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActionQueue:
    """Fluent builder for browser action chains.

    Actions are executed sequentially in the live browser after the page loads.
    This enables form filling, button clicks, and waiting for dynamic content.

    Example:
        >>> actions = (
        ...     ActionQueue()
        ...     .wait(2)
        ...     .fill("//input[@id='email']", "user@example.com")
        ...     .fill("//input[@id='password']", "secret")
        ...     .click("//button[@type='submit']")
        ...     .wait_for("//div[@id='dashboard']")
        ...     .build()
        ... )
        >>> response = client.request.get("https://example.com/login", actions=actions)
    """

    _actions: list[dict] = field(default_factory=list, repr=False)

    def wait(self, seconds: float) -> ActionQueue:  # noqa
        """Sleep for the given number of seconds.

        Useful to allow interaction trackers to warm up before the first input.

        Args:
            seconds: Number of seconds to sleep.

        Returns:
            Self for method chaining.
        """
        self._actions.append({"type": "wait", "seconds": seconds})
        return self

    def fill(self, selector: str, value: str) -> ActionQueue:  # noqa
        """Type a value into a form field.

        Scrolls to the element, clicks to focus, then types the value
        character-by-character with randomized inter-key delays to mimic
        human typing speed.

        Args:
            selector: XPath expression to locate the element.
            value: The text to type into the field.

        Returns:
            Self for method chaining.
        """
        self._actions.append({"type": "fill", "selector": selector, "value": value})
        return self

    def click(self, selector: str, human_like: bool = False) -> ActionQueue:  # noqa
        """Click an element on the page.

        Scrolls the element into view and clicks. When human_like is True,
        uses bezier-curve mouse movement for a more natural trajectory.

        Args:
            selector: XPath expression to locate the element.
            human_like: Use human-like mouse movement (default: False).

        Returns:
            Self for method chaining.
        """
        action: dict = {"type": "click", "selector": selector}
        if human_like:
            action["humanLike"] = True
        self._actions.append(action)
        return self

    def wait_for(self, selector: str) -> ActionQueue:  # noqa
        """Wait until an element becomes visible.

        Blocks until the matched element becomes visible on the page.
        Useful to wait for XHR-driven results to appear.

        Args:
            selector: XPath expression to locate the element.

        Returns:
            Self for method chaining.
        """
        self._actions.append({"type": "wait_for", "selector": selector})
        return self

    def build(self) -> list[dict]:  # noqa
        """Build and return the list of actions.

        Returns:
            List of action dictionaries ready to pass to request methods.
        """
        return self._actions.copy()

    def clear(self) -> ActionQueue:
        """Clear all actions from the queue.

        Returns:
            Self for method chaining.
        """
        self._actions.clear()
        return self

    def __len__(self) -> int:
        """Return the number of actions in the queue."""
        return len(self._actions)

    def __bool__(self) -> bool:
        """Return True if the queue has actions."""
        return bool(self._actions)
