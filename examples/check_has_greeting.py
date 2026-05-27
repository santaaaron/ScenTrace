"""Example Python check script for ScenTrace.

Must export a `check(response: str, context: dict) -> bool` function.
Return True for pass, False for fail.
"""


def check(response: str, context: dict) -> bool:
    return "mock response" in response.lower()
