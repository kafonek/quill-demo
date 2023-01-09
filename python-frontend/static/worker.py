from importlib.metadata import version

import js
import pyodide
import y_py as Y
from ypy_websocket import yutils

# Sometimes we'll get an observed event that is empty. We want to check for those and
# avoid sending out needless updates. Also see https://github.com/y-crdt/ypy/issues/98 
EMPTY_UPDATE = b"\x00\x00"


class QuillBinding:
    def __init__(self):
        self.ydoc = Y.YDoc()
        self.ytext = self.ydoc.get_text('quill')
        self.ytext.observe(self._on_ytext_change)

        self.log(f"Hello from worker.py! Using y-py version {version('y_py')}.")
        
        # When we send this message over webworker, index.html will enable the quill 
        # canvas and update the text placeholder
        self.post({"type": "status", "data": "ready"})
        
        # Used in ytext change observer, wouldn't need this if yrs/y-py transactions had
        # an "origin" argument
        self.report_ytext_changes = True

    def _on_ytext_change(self, event: Y.YTextEvent):
        """
        Observe when our YDoc has changed, which could happen because we handled a 
        delta passed over the webworker (our user made a change in the quill canvas) 
        or from a sync over websocket (another user made a change in the quill canvas).

        We only want to send the update back to our quill canvas if the delta originated
        from another user. 
        """
        self.log(f"ytext change: {event}")
        deltas = []
        for delta in event.delta:
            if 'attributes' in delta:
                for k, v in delta['attributes'].items():
                    if v is None:
                        delta['attributes'][k] = False
            deltas.append(delta)
        if self.report_ytext_changes:
            self.post({'type': 'delta', 'data': deltas})
        

    def post(self, data: dict):
        """
        Send data back to the main javascript thread.
        """
        js.postMessage(pyodide.ffi.to_js(data, dict_converter=js.Object.fromEntries))

    def log(self, msg):
        js.console.log(pyodide.ffi.to_js(msg))

    def recv(self, event: pyodide.ffi.JsProxy):
        """
        When a user updates the quill canvas, there's a handler that will push the quill
        delta over webworker and we get here. As a hack around not having an "origin"
        argument in the transaction, we toggle self.report_ytext_changes off and on
        """
        delta: dict = event.data.to_py()    
        self.log(delta)    
        self.report_ytext_changes = False
        with self.ydoc.begin_transaction() as txn:
            idx = 0
            for op in delta['ops']:
                js.console.warn(op)
                if 'retain' in op:
                    idx += op['retain']
                if 'insert' in op:
                    text = op['insert']
                    if 'attributes' in op:
                        self.ytext.insert(txn, idx, text, op['attributes'])
                    else:
                        self.ytext.insert(txn, idx, text)
                    idx += len(text)
                if 'delete' in op:
                    self.ytext.delete_range(txn, idx, op['delete'])
        self.report_ytext_changes = True

        self.log(str(self.ytext))


class WebsocketProvider:
    def __init__(self, binding: QuillBinding):
        self.binding = binding
        self.ws_url = "ws://localhost:8000/ws"
        # use "native" javascript syntax for creating the websocket and attaching cbs
        self.socket = js.WebSocket.new(self.ws_url)
        self.socket.addEventListener("message", pyodide.ffi.create_proxy(self._on_message))
        self.socket.onopen = pyodide.ffi.create_proxy(self.send_sync_step1)
        self.binding.ydoc.observe_after_transaction(self.send_update)

    async def _on_message(self, event: pyodide.ffi.JsProxy):
        # all data coming over ws is binary, which means it comes into js as a Blob
        # and needs to be converted to arrayBuffer before being turned into Python bytes
        # (after going through memoryview first)
        # https://pyodide.org/en/stable/usage/type-conversions.html#using-javascript-typed-arrays-from-python
        buf = await event.data.arrayBuffer()
        data: bytes = bytes(buf.to_memoryview())
        js.console.log(f'Received {type(data)=} {data=}')
        # https://github.com/yjs/y-protocols/blob/master/PROTOCOL.md
        # we send out 0, 0 on websocket connect (sync step 1),
        # server responds with 0, 1 (sync step 2)
        # further updates go out as 0, 2 (update message)
        # awareness protocol is 1, *
        s1 = int(data[0]) 
        s2 = int(data[1]) 
        if s1 == 0 and s2 in [1, 2]:
            update = yutils.Decoder(data[2:]).read_message()
            js.console.log(f"Got update {update}")
            Y.apply_update(self.binding.ydoc, update)

    def send_sync_step1(self, connect_event: pyodide.ffi.JsProxy):
        sv = Y.encode_state_vector(self.binding.ydoc)
        update = yutils.create_sync_step1_message(sv)
        js.console.log(f"Sending {update}")
        self.socket.send(pyodide.ffi.to_js(update))

    def send_update(self, event):
        js.console.log(type(event))
        update = event.get_update()
        if update == EMPTY_UPDATE:
            return
        js.console.log(f"diff: {update}")
        data: bytes = yutils.create_update_message(update)
        js.console.log(f"Sending {data}")
        self.socket.send(pyodide.ffi.to_js(data))
        


binding = QuillBinding()
provider = WebsocketProvider(binding)
# callback for any messages coming in over the webworker (i.e. our user editing canvas)
js.onmessage = binding.recv