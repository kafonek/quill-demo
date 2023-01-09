# Intro

This repository demonstrates using yjs and y-py to synchronize a quilljs canvas between clients. The `js-frontend` directory is a nearly unchanged copy of the [yjs-demos](https://github.com/yjs/yjs-demos) Quill example. Instead of pointing to a public websocket host, it points to a local `backend` server written in Python and the `FastAPI` framework. The backend keeps its own `YDoc` model using y-py. Finally, the most unique part of this demonstration is the `python-frontend`. That replaces the Quill - yjs binding and y-websocket provider with y-py / Python running in a webworker with pyodide.

# Setup

Bootstrap your system to install `npm` and `python`, I recommend using [nvm](https://github.com/nvm-sh/nvm) and [pyenv](https://github.com/pyenv/pyenv). The `python-frontend` directory specifies using Python 3.10.2 so that IDE support when writing `static/worker.py` will match the version of Python when it's compiled to webassembly and run within Pyodide v0.21.3 (specified in `static/worker.js`).

# Run

Start all three servers:

 - `cd backend && poetry install && poetry run uvicorn app:app` (default port is 8000)
 - `cd js-frontend && npm start` (default port is 8081)
 - `cd python-frontend && poetry install && poetry run uvicorn app:app --port 8082`

If you need to switch ports around because you have other things running on your machine, just make sure to update the websocket urls in `js-frontend/quill.js` and `python-frontend/static/worker.py` to point to the `backend` server.

# y-py in Pyodide

`y-py` are Python bindings to `yrs`, the Rust implementation of the y-crdt algorithm. That means it is not a pure Python package, so wheels need to be built for each target machine you want to install it on. In this case, we want to install it in Pyodide 0.21.3, so the target machine is `cp310` (Pyodide 0.21.3 runs Python 3.10.2) and `emscripten 3-1-14 wasm32`.

Unfortunately, PyPI does not host wasm wheels. See y-py PR's [91](https://github.com/y-crdt/ypy/pull/91), [99](https://github.com/y-crdt/ypy/pull/99), and [103](https://github.com/y-crdt/ypy/pull/103) for ongoing attempts to build a wasm wheel as part of a y-py release and attach the binary as an asset in github. For the sake of this demo, a copy of the wheel is just included in the repo and served out as a static file. See `python-frontend/static/worker.js` for implementation of writing and installing the wheel from emscripten disk (`emfs:<path>`).

# Issues

 - Obviously missing plenty of features in this demo, such as awareness protocol and websocket disconnect/reconnect in `python-frontend`
 - Setting attributes on existing text (e.g. select text, toggle italics on/off) syncs when done in the js-served window but doesn't when initiated from python-frontend
 - Putting in data (e.g. pasting screenshot) fails in python-frontend with error `TypeError: argument 'chunk': 'dict' object cannot be converted to 'PyString'`
 - `yrs` / `y-py` doesn't have an `origin` argument in the transaction
 - It would be nice if synchronization message helpers were implented in `yrs` rather than in `ypy-websocket` utils
 - If you have more than one tab open from `js-frontend` and restart `backend`, the two frontends will have a shared `YDoc` state that's out of sync with `backend`, so any new updates aren't captured server-side nor broadcast over websocket (they still sync between tabs thanks to `y-websocket` js). Closing the second tab then refreshing the first gets you synced again




