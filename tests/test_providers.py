import sys
from unittest.mock import MagicMock, patch

import pytest

from scen_trace.providers.loader import ProviderNotInstalledError, get_provider
from scen_trace.providers.mock import MockProvider


class TestProviderFactory:
    def test_get_mock_provider(self):
        p = get_provider("mock")
        assert isinstance(p, MockProvider)

    def test_get_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("nonexistent")

    def test_get_openai_without_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            env_backup = {k: v for k, v in sys.modules.items() if "openai" in k or "scen_trace.providers.openai" in k}
            for k in env_backup:
                sys.modules.pop(k, None)
            with pytest.raises((ValueError, ProviderNotInstalledError)):
                get_provider("openai")

    def test_missing_openai_sdk_raises_install_hint(self):
        saved = {}
        for k in list(sys.modules.keys()):
            if "openai" in k or "scen_trace.providers.openai" in k:
                saved[k] = sys.modules.pop(k)
        try:
            with patch.dict("sys.modules", {"openai": None}):
                with pytest.raises(ProviderNotInstalledError, match="Install with"):
                    get_provider("openai")
        finally:
            sys.modules.update(saved)


class TestMockProvider:
    def test_deterministic_response(self):
        p = MockProvider()
        r = p.generate("sys", "hello")
        assert "hello" in r.content

    def test_failure_injection(self):
        p = MockProvider(fail_on_turn=1)
        with pytest.raises(RuntimeError):
            p.generate("sys", "hello")

    def test_realistic_integer_tokens(self):
        p = MockProvider()
        r = p.generate("system prompt", "test prompt")
        assert isinstance(r.input_tokens, int)
        assert isinstance(r.output_tokens, int)
        assert r.input_tokens > 0
        assert r.output_tokens > 0

    def test_token_count_scales_with_input(self):
        p = MockProvider()
        short = p.generate("s", "hi")
        long = p.generate("s" * 100, "hello world this is a much longer prompt")
        assert long.input_tokens > short.input_tokens
