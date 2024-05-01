from client.client import Client
from client.api import ClientAPI
from client.utils import Endpoint
import socketio
import json
import sys

DEV = False
CONFIG = f'src/middleware/{'dev_' if DEV else ''}python_config.json'

if __name__ == "__main__":
    with open(CONFIG) as json_data:
        config = json.load(json_data)

    try:
        frontend_socket = socketio.Client()
        client = Client(frontend_socket,
                        api_endpoint=ClientAPI.DEFAULT_ENDPOINT,
                        server_endpoint=Endpoint(config["SERVER_IP"],
                                                 config["SERVER_PORT"]))

        frontend_socket.connect(
            f"http://localhost:{sys.argv[1]}",
            headers={'user_id': client.user_id},
            retry=True)

        handle_conenct_to_peer = frontend_socket.on('connect_to_peer')(
            lambda data: client.connect_to_peer(data))

        while True:
            pass

    except Exception as f:
        raise f
