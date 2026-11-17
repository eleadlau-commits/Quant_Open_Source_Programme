// In-browser backend: runs the honestbt Python package with Pyodide, so the
// site works as static files (e.g. GitHub Pages) with no server.
// Activated when the page is built with scripts/build_static_site.py.
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

let pyReady = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
}

async function bootPython(onStatus) {
  onStatus("Loading Python in your browser (first visit takes ~20 s)…");
  await loadScript(PYODIDE_URL + "pyodide.js");
  const py = await loadPyodide({ indexURL: PYODIDE_URL });
  onStatus("Loading numpy and pandas…");
  await py.loadPackage(["numpy", "pandas"]);
  const manifest = await (await fetch("py-manifest.json")).json();
  for (const path of manifest.files) {
    const text = await (await fetch("py/" + path)).text();
    const dir = path.split("/").slice(0, -1).join("/");
    if (dir) py.FS.mkdirTree("/home/pyodide/" + dir);
    py.FS.writeFile("/home/pyodide/" + path, text);
  }
  py.runPython(`
import json, sys
sys.path.insert(0, "/home/pyodide")
from honestbt.registry import catalog, load_plugins
from honestbt.runner import run_config
load_plugins()
def _catalog():
    return json.dumps(catalog())
def _run(cfg_json):
    return json.dumps(run_config(json.loads(cfg_json)), default=float)
`);
  onStatus("Ready. Everything runs locally in your browser.");
  return { py, manifest };
}

window.staticApi = async function (path, body, onStatus = () => {}) {
  if (!pyReady) pyReady = bootPython(onStatus);
  const { py, manifest } = await pyReady;
  if (path === "/api/plugins") return JSON.parse(py.globals.get("_catalog")());
  if (path === "/api/configs") return manifest.configs;
  if (path.startsWith("/api/configs/")) {
    const name = path.slice("/api/configs/".length);
    return (await fetch("configs/" + name + ".json")).json();
  }
  if (path === "/api/run") {
    await new Promise((r) => setTimeout(r, 30)); // let the UI repaint first
    try {
      return JSON.parse(py.globals.get("_run")(JSON.stringify(body)));
    } catch (e) {
      throw new Error(String(e.message || e).split("\n").filter(Boolean).slice(-1)[0]);
    }
  }
  throw new Error("unknown path " + path);
};
