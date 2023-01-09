from typing import List

import y_py as Y
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from ypy_websocket import yutils

# Sometimes we'll get an observed event that is empty. We want to check for those and
# avoid sending out needless updates. Also see https://github.com/y-crdt/ypy/issues/98 
EMPTY_UPDATE = b"\x00\x00"

app = FastAPI()

# Need to enable CORS since js-frontend and python-frontend are served on different ports
origins = [
    "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WebsocketManager:
    """
    Keep a list of all connections so we can broadcast updates.

    Also keep the server's YDoc here. When clients send in an update,
    we update our server Doc then broadcast to all clients.

    When new clients connect, they receive sync updates from this server
    representation of the doc, not from other clients.
    """

    # We ultimately want a singleton instance of this class in the websocket handler
    # below, there's many ways to do that. This is just my preferred syntax
    _singleton_instance = None

    def __init__(self):
        self.connections: List[WebSocket] = []
        self.ydoc = Y.YDoc()
        self.ytext = self.ydoc.get_text("quill")
        self.ytext.observe(self._on_ytext_change)
        self.ydoc.observe_after_transaction(self._on_doc_change)

    def _on_ytext_change(self, event: Y.YTextEvent):
        print(f"YText event: {event}")
        print(self.ytext)

    def _on_doc_change(self, event: Y.AfterTransactionEvent):
        # Here to let you print or introspect the full doc change event
        pass

    @classmethod
    async def instance(cls):
        if not cls._singleton_instance:
            cls._singleton_instance = cls()
        return cls._singleton_instance

    async def broadcast(self, message: bytes):
        print(f"Broadcasting message: {message}")
        for connection in self.connections:
            await connection.send_bytes(message)

    async def send(self, websocket: WebSocket, message: bytes):
        print(f"Sending message to {id(websocket)}: {message}")
        await websocket.send_bytes(message)


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    manager: WebsocketManager = Depends(WebsocketManager.instance),
):
    """
    Handle the lifecycle of a websocket connection.
     - On connect, the client will send a sync step 1, including their state vector
       - We respond with a sync step 2, passing the diff between our state and theirs
         so they can catch up to our state.

     - When a client sends us an update, we apply to our server doc and broacast
        the update delta to all connected clients

     - Reply to client heartbeat messages directly without broadcasting
    """
    await websocket.accept()
    manager.connections.append(websocket)

    try:
        while True:
            raw_data: bytes = await websocket.receive_bytes()
            # In this example we'll print out the integer values of the bytes instead of
            # the bytes themselves. Just a different way of viewing the data coming over the wire
            data: List[int] = [i for i in raw_data]
            #print(f"Received message from {id(websocket)}: {data}")
            if data[0] == 0:
                # If the first byte is 0 then the message is a SyncProtocolMessageType
                # There are three types of Sync Protocol messages (defined by second byte):
                # - 0 = SyncStep1, will include the client's state vector
                # - 1 = SyncStep2, if we sent a syncstep1 to client, it would respond with this
                #       plus the deltas we need to apply to catchup to their state
                # - 3 = UpdateMessage, the client is sending us an update to apply to our server doc
                #
                # The third* byte is the length of the rest of the message (state vector or diff)
                # (length might be more than one byte, which is why we use yutils to handle reading/creating msg)
                if data[1] == 0:
                    # SyncStep1, calculate the diff for the client to catchup to us and send it out
                    state_vector: bytes = yutils.Decoder(raw_data[2:]).read_message()
                    with manager.ydoc.begin_transaction() as txn:
                        diff = txn.diff_v1(state_vector)
                        print(f"Diff: {diff}")
                    response: bytes = yutils.create_sync_step2_message(diff)
                    print("Replying to sync step 1")
                    await manager.send(websocket, response)

                elif data[1] == 1:
                    print("Somehow got into sync step 2, how did this happen? We never send out sync step 1...")

                elif data[1] == 2:
                    print("Received update, applying to YDoc and transmitting diffs")
                    # UpdateMessage, apply the update to our server doc and broadcast to all clients
                    update: bytes = yutils.Decoder(raw_data[2:]).read_message()
                    if update == EMPTY_UPDATE:
                        continue
                    with manager.ydoc.begin_transaction() as txn:
                        before_sv = txn.state_vector_v1()
                        txn.apply_v1(update)
                        diff = txn.diff_v1(before_sv)
                    if diff == EMPTY_UPDATE:
                        # Not sure all the times this happens, but definitely occurs when one frontend is out of
                        # sync with backend (e.g. restart backend when two js frontend tabs are open -- they keep
                        # a shared YDoc through js storage, and any updates send to backend will be "empty")
                        print("Applied update but no diff, skipping broadcast")
                        continue
                    else:
                        update = yutils.create_update_message(diff)
                        await manager.broadcast(update)

                else:
                    print(f"Observed unexpected / unknown SyncProtocolMessageType: {data}")

            elif data[0] == 1:
                # TODO: support awareness messages
                pass

            else:
                print(f"Observed unexpected / unknown message type: {data}")

    except WebSocketDisconnect:
        manager.connections.remove(websocket)
    except Exception as e:
        print(e)
        raise e
