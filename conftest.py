"""Shared by tests/ and the plugin folders' own tests."""
import os
import tempfile

# Never pick up the plugins of whoever runs the tests.
os.environ.setdefault("HONESTBT_PLUGIN_DIR", tempfile.mkdtemp(prefix="honestbt-plugins-"))
