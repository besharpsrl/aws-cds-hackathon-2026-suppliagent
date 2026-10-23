import importlib

import pytest


@pytest.mark.parametrize("module", ["suppliagent_shared", "suppliagent_agent"])
def test_workspace_packages_are_importable(module: str) -> None:
    assert importlib.import_module(module).__doc__
