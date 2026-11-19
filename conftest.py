"""Shared by tests/ and the plugin folders' own tests."""
import os
import tempfile

# Never pick up the plugins of whoever runs the tests.
os.environ.setdefault("HONESTBT_PLUGIN_DIR", tempfile.mkdtemp(prefix="honestbt-plugins-"))
os.environ.setdefault("TITANIUM_HOME", tempfile.mkdtemp(prefix="titanium-home-"))
# The strategies are starter packs, not built in; the tests load them straight from the source tree.
os.environ.setdefault("HONESTBT_EXTRA_PLUGIN_DIRS",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "honestbt", "plugins", "starter"))
