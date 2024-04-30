from client.api import ClientAPI
from client.utils import Endpoint, ParameterError, get_parameters, ClientState
import requests
import socketio

# region --- Logging --- # TODO: Add internal logger to Client class
import logging
from client.utils.av import AV

# XXX: Switch back to level=logging.DEBUG
logging.basicConfig(filename='./src/middleware/logs/client.log',
                    level=logging.INFO,
                    format='[%(asctime)s] (%(levelname)s) %(name)s.%(funcName)s: %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)
# endregion

# TODO: Trim down this file

# region --- Utils ---


class UnexpectedResponse(Exception):
    pass


class ConnectionRefused(UnexpectedResponse):
    pass


class InternalClientError(Exception):
    pass


# endregion


# region --- Socket Client ---


class SocketClient():  # Not threaded because sio.connect() is not blocking

    sio = socketio.Client()
    user_id = None
    endpoint = None
    conn_token = None
    sess_token = None
    instance = None
    namespaces = None
    av = None
    video = {}
    display_message = None

    # region --- Utils ---
    logger = logging.getLogger('SocketClient')

    @classmethod
    def set_sess_token(cls, sess_token):
        cls.logger.info(f"Setting session token '{sess_token}'")
        cls.sess_token = sess_token

    @classmethod
    def is_connected(cls):
        return cls.sio.connected

    def HandleExceptions(endpoint_handler):
        """
        Decorator to handle commonly encountered
        exceptions at Socket Client endpoints.

        NOTE: This should never be called explicitly
        """
        def handler_with_exceptions(*args, **kwargs):
            cls = SocketClient

            try:
                return endpoint_handler(cls, *args, **kwargs)
            except Exception as e:  # TODO: Add excpetions
                raise e
        return handler_with_exceptions
    # endregion

    # region --- External Interface ---

    @classmethod
    # TODO: Unsure if client needed.
    def init(cls, endpoint, conn_token, user_id,
             display_message, frontend_socket):
        cls.logger.info(
            f"Initiailizing Socket Client with WebSocket endpoint {endpoint}.")

        cls.av = AV(cls, frontend_socket)
        cls.namespaces = cls.av.client_namespaces

        cls.conn_token = conn_token
        cls.endpoint = Endpoint(*endpoint)
        cls.user_id = user_id
        cls.display_message = display_message
        cls.instance = cls()
        return cls.instance

    def start(self):
        self.run()

    def run(self):
        SocketClient.connect()

    @classmethod
    def send_message(cls, msg: str, namespace='/'):
        cls.sio.send(((str(cls.user_id), cls.sess_token), msg),
                     namespace=namespace)

    @classmethod
    def connect(cls):
        cls.logger.info(f"Attempting WebSocket connection to {cls.endpoint} with connection token '{cls.conn_token}'.")
        try:
            ns = sorted(list(cls.namespaces.keys()))
            cls.sio.connect(str(cls.endpoint), wait_timeout=5, auth=(
                cls.user_id, cls.conn_token), namespaces=['/']+ns)
            for name in ns:
                cls.sio.register_namespace(cls.namespaces[name])
        except socketio.exceptions.ConnectionError as e:
            cls.logger.error(f"Connection failed: {str(e)}")

    @classmethod
    def disconnect(cls):
        # Check to make sure we're actually connected
        cls.logger.info("Disconnecting Socket Client from Websocket API.")
        cls.sio.disconnect()
        # Make sure to update state, delete instance if necessary, etc.

    @classmethod
    def kill(cls):
        cls.logger.info("Killing Socket Client")
        cls.disconnect()
        # Make sure to update state, delete instance if necessary, etc.
    # endregion

    # region --- Event Endpoints ---

    @sio.on('connect')
    @HandleExceptions
    def on_connect(cls):
        cls.logger.info(f"Socket connection established to endpoint {
                        SocketClient.endpoint}")
        ns = sorted(list(cls.namespaces.keys()))
        for name in ns:
            cls.namespaces[name].on_connect()

    @sio.on('token')
    @HandleExceptions
    def on_token(cls, sess_token):
        cls.logger.info(f"Received session token '{sess_token}'")
        SocketClient.set_sess_token(sess_token)

    @sio.on('message')
    @HandleExceptions
    def on_message(cls, user_id, msg):
        cls.logger.info(f"Received message from user {user_id}: {msg}")
        SocketClient.display_message(user_id, msg)

    # endregion
# endregion


# region --- Main Client ---


class Client:
    def __init__(self, frontend_socket, server_endpoint=None,
                 api_endpoint=None, websocket_endpoint=None):
        self.logger = logging.getLogger('Client')
        self.logger.info(f"""Initializing Client with:
                         Server endpoint {server_endpoint},
                         Client API endpoint {api_endpoint},
                         WebSocket API endpoint {websocket_endpoint}.""")
        self.user_id = None
        self.sess_token = None
        self.state = ClientState.NEW
        self.frontend_socket = frontend_socket
        self.server_endpoint = server_endpoint
        self.api_endpoint = api_endpoint
        self.websocket_endpoint = websocket_endpoint
        self.peer_endpoint = None
        self.api_instance = None
        self.websocket_instance = None

        self.gui = None
        self.start_api()
        self.connect()

    # region --- Utils ---

    def authenticate_server(self, sess_token):
        return sess_token == self.sess_token

    # TODO: All endpoint functions should take a single endpoint obj.
    def set_server_endpoint(self, endpoint):
        if self.state >= ClientState.LIVE:
            # TODO: use InvalidState
            raise InternalClientError(
                "Cannot change server endpoint after connection already established.")

        self.server_endpoint = Endpoint(*endpoint)
        self.logger.info(f"Setting server endpoint: {self.server_endpoint}")

    def set_api_endpoint(self, endpoint):
        if self.state >= ClientState.LIVE:
            # TODO: use InvalidState
            raise InternalClientError(
                "Cannot change API endpoint after connection already established.")

        self.api_endpoint = Endpoint(*endpoint)
        ClientAPI.endpoint = self.api_endpoint
        self.logger.info(f"Setting API endpoint: {self.api_endpoint}")

    def display_message(self, user_id, msg):
        print(f"({user_id}): {msg}")

    def contact_server(self, route, json=None):
        endpoint = self.server_endpoint(route)
        self.logger.info(f"Contacting Server at {endpoint}.")

        try:
            response = requests.post(str(endpoint), json=json)
        except requests.exceptions.ConnectionError as e:
            raise ConnectionRefused(
                f"Unable to reach Server API at endpoint {endpoint}.")

        if response.status_code != 200:
            try:
                json = response.json()
            except requests.exceptions.JSONDecodeError as e:
                raise UnexpectedResponse(f"Unexpected Server response at {
                                         endpoint}: {response.reason}.")

            if 'details' in response.json():
                raise UnexpectedResponse(f"Unexpected Server response at {
                                         endpoint}: {response.json()['details']}.")
            raise UnexpectedResponse(f"Unexpected Server response at {
                                     endpoint}: {response.reason}.")
        return response

    def kill(self):
        try:
            ClientAPI.kill()
        except Exception:
            pass
        try:
            SocketClient.kill()
        except Exception:
            pass
        try:
            requests.delete(str(self.server_endpoint('/remove_user')), json={
                'user_id': self.user_id,
                'sess_token': self.sess_token
            })
        except Exception:
            pass
        # TODO: Kill Socket Client
        # TODO: Kill Socket API
        # TODO: Kill Client API
        # TODO: Disconnect from server
        pass
    # endregion

    # region --- Server Interface ---
    # TODO: Client API should be LIVE first; need to give endpoint to server.

    def connect(self):
        """
        Attempt to connect to specified server.
        Expects token and user_id in return.
        Return `True` iff successful.
        """
        self.logger.info(f"Attempting to connect to server: {
                         self.server_endpoint}.")
        if (self.state >= ClientState.LIVE):
            logger.error(f"Cannot connect to {
                         self.server_endpoint}; already connected.")
            raise InternalClientError(
                f"Cannot connect to {self.server_endpoint}; already connected.")

        try:
            response = self.contact_server('/create_user', json={
                'api_endpoint': tuple(self.api_endpoint)
            })
        except ConnectionRefused as e:
            self.logger.error(str(e))
            return False
        except UnexpectedResponse as e:
            self.logger.error(str(e))
            raise e

        try:
            self.user_id, self.sess_token = get_parameters(
                response.json(), 'user_id', 'sess_token')
            self.logger.info(f"Received user_id '{
                             self.user_id}' and token '{self.sess_token}'.")
        except ParameterError as e:
            self.logger.error(f"Server response did not contain both user_id and sess_token at {
                              self.server_endpoint('/create_user')}.")
            raise UnexpectedResponse(f"Server response did not contain both user_id and sess_token at {
                                     self.server_endpoint('/create_user')}.")

        self.state = ClientState.LIVE
        print(f"Received user_id {
              self.user_id} and sess_token '{self.sess_token}'")
        return True

    def connect_to_peer(self, peer_id):
        """
        Open Socket API. Contact Server /peer_connection with `conn_token`
        and await connection from peer (authenticated by `conn_token`).
        """
        self.logger.info(
            f"Attempting to initiate connection to peer User {peer_id}.")

        print(f"Requesting connection to {peer_id}")
        try:
            response = self.contact_server('/peer_connection', json={
                'user_id': self.user_id,
                'sess_token': self.sess_token,
                'peer_id': peer_id,
            })
        except ConnectionRefused as e:
            self.logger.error(str(e))
            raise e
        except UnexpectedResponse as e:
            self.logger.error(str(e))
            raise e

        websocket_endpoint, conn_token = get_parameters(
            response.json(), 'socket_endpoint', 'conn_token')
        self.logger.info(f"Received websocket endpoint '{
                         websocket_endpoint}' and conn_token '{conn_token}' from Server.")
        self.connect_to_websocket(websocket_endpoint, conn_token)
        while True:
            if SocketClient.is_connected():
                break

    def disconnect_from_server(self):
        pass
    # endregion

    # region --- Client API Handlers ---

    def start_api(self):
        if not self.api_endpoint:
            raise InternalClientError(
                "Cannot start Client API without defined endpoint.")

        self.api_instance = ClientAPI.init(self)
        self.api_instance.start()

    # TODO: Return case for failed connections
    def handle_peer_connection(self, peer_id, socket_endpoint, conn_token):
        """
        Initialize Socket Client and attempt
        connection to specified Socket API endpoint.
        Return `True` iff connection is successful

        Parameters
        ----------

        """
        if self.state == ClientState.CONNECTED:
            raise InternalClientError(
                f"Cannot attempt peer websocket connection while {self.state}.")

        self.logger.info("Polling User")
        print(f"Incoming connection request from {peer_id}.")
        # ANDY_TODO: Remove the question
        res = self.gui.question('Incoming Peer Connection',
                                f"Peer User {peer_id} has requested to connect to you. Accept?")
        if res == 'yes':
            self.logger.info("User Accepted Connection.")
            self.logger.info(f"Attempting to connect to peer {peer_id} at {
                             socket_endpoint} with token '{conn_token}'.")

            try:
                self.connect_to_websocket(socket_endpoint, conn_token)
            except Exception as e:
                self.gui.alert('Warning', f"Connection to incoming peer User {
                               peer_id} failed.")
                return False
            self.logger.info(f"Successfully connected to peer User {peer_id}.")
            self.gui.quit('User accepted an incoming connection request.')
            self.logger.info(
                "Just quit da GUI; returning from client.handle_peer_connection().")
            return True
        else:
            self.logger.info("User Refused Connection.")
            return False
        return False

    def disconnect_from_peer(self):
        pass
    # endregion

    # region --- Web Socket Interface ---
    def connect_to_websocket(self, endpoint, conn_token):
        sio = SocketClient.init(
            endpoint, conn_token, self.user_id,
            self.display_message, self.frontend_socket)
        try:
            sio.start()
        except Exception as e:
            self.logger.error(f"Failed to connect to WebSocket at {
                              endpoint} with conn_token '{conn_token}'.")
            raise e
    # endregion
# endregion