console.log("Hello from worker.js")
importScripts("https://cdn.jsdelivr.net/pyodide/v0.21.3/full/pyodide.js");


async function init() {
    console.log("loading pyodide")
    self.pyodide = await loadPyodide()

    // the state of the art for importing Python files is to:
    // - use pyodide.loadPackage if the package is already compiled by pyodide (e.g. numpy)
    // - use micropip.install if the package is a wheel/pure Python hosted on Pypi
    // - read the raw .py text and write to virtual filesystem then import if it is a one-off script
    // see https://github.com/pyodide/pyodide/issues/1917
    // && https://pyodide.org/en/stable/usage/faq.html#how-can-i-load-external-python-files-in-pyodide

    // Install y-py first. As of Dec 2022, wasm wheels can't be hosted on PyPI so this wheel is built
    // and hosted separately (in this case, downloaded from y-crdt/ypy repo and served out locally)

    await pyodide.loadPackage(["micropip"])
    await self.pyodide.runPythonAsync(`
    import micropip
    from pyodide.http import pyfetch

    # Install y-py first. As of Dec 2022, wasm wheels can't be hosted on PyPI so this wheel is built
    # and hosted separately (in this case, downloaded from y-crdt/ypy repo and served out locally)
    wheel_name = "y_py-0.5.5-cp310-cp310-emscripten_3_1_14_wasm32.whl"
    resp = await pyfetch(f"./{wheel_name}")

    with open(wheel_name, "wb") as f:
        f.write(await resp.bytes())

    await micropip.install(f"emfs:./{wheel_name}")

    # Install ypy-websocket second, after y-py is there. 
    await micropip.install("ypy-websocket")

    # Force browser to avoid caching the worker.py script, annoying gotcha while developing.
    resp = await pyfetch("./worker.py", headers={"pragma": "no-cache", "cache-control": "no-cache"})
    with open("worker.py", "wb") as f:
        f.write(await resp.bytes())

    import worker
    `)
}
let initPromise = init();