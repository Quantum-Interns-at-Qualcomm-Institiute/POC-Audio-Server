from enum import Enum
from functools import total_ordering
import hashlib
import platform
from threading import Thread
from typing import Tuple

from flask import Flask, jsonify
from flask_socketio import SocketIO, emit, send
from gevent.pywsgi import WSGIServer
import psutil
from utils.namespaces.av_controller import generate_flask_namespace
from user import User
from utils import BadAuthentication, InvalidParameter, ParameterError, ServerError, BadGateway, BadRequest, remove_last_period
from utils import Endpoint
import requests
from utils.user_manager import UserManager, UserStorageFactory, UserState, DuplicateUser, UserNotFound, UserStorageTypes
from exceptions import InvalidState

# region --- Logging --- # TODO: Add internal logger to Server class
import logging
logging.basicConfig(filename='./logs/server.log', level=logging.DEBUG,
                    format='[%(asctime)s] (%(levelname)s) %(name)s.%(funcName)s: %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)
# endregion


# region --- Utils ---
# endregion


def get_parameters(data, *args):
    """
    Returns desired parameters from a collection with optional data validation.
    Validator functions return true iff associated data is valid.

    Parameters
    ----------
    data : list, tuple, dict
    arg : list, optional
        If `data` is a sequence, list of validator functions (or `None`).
    arg : str, optional
        If `data` is a dict, key of desired data.
    arg : 2-tuple, optional
        If `data` is a dict:
        arg[0] : str,
        arg[1] : func
    """
    if isinstance(data, list) or isinstance(data, tuple):
        if len(args == 0):
            return get_parameters_from_sequence(data)
        return get_parameters_from_sequence(data, args[0])
    if isinstance(data, dict):
        return get_parameters_from_dict(data, *args)
    raise NotImplementedError


def get_parameters_from_sequence(data, validators=[]):
    """
    Returns desired data from a list or or tuple with optional data validation.
    Validator functions return true iff associated data is valid.

    Parameters
    ----------
    data : list, tuple
    validators : list, tuple, optional
        Contains validator functions (or `None`) which return true iff associated data is acceptable.
        Must match order and length of `data`.
    """
    if len(validators) == 0:
        return (*data,)
    if len(data) != len(validators):
        raise ParameterError(
            f"Expected {len(validators)} parameters but received {len(data)}.")

    param_vals = ()
    for i in range(len(data)):
        param_val = data[i]
        validator = validators[i]
        if not validator:
            validator = lambda x: True

        if not validator(param_val):
            raise InvalidParameter(f"Parameter {i + 1} failed validation.")
        param_vals += (*param_vals, param_val)
    return param_vals


def get_parameters_from_dict(data, *args):
    """
    Returns desired data from a dict with optional data validation.
    Validator functions return true iff associated data is valid.

    Parameters
    ----------
    data : dict
    arg : str, optional
        Key of desired data
    arg : 2-tuple, optional
        arg[0] : str,
        arg[1] : func
    """
    param_vals = ()
    for i in range(len(args)):
        arg = args[i]
        validator = lambda x: True
        if type(arg) is tuple:
            param, validator = arg
        else:
            param = arg

        if param in data:
            param_val = data.get(param)
        else:
            raise ParameterError(f"Expected parameter '{param}' not received.")

        if not validator(param_val):
            raise InvalidParameter(f"Parameter '{param}' failed validation.")

        param_vals = (*param_vals, param_val)
    return param_vals


def is_type(type_):
    return lambda x: isinstance(x, type_)


@total_ordering
class ServerState(Enum):
    NEW = 'NEW'
    INITIALIZED = 'INITIALIZED'
    CLOSED = 'CLOSED'
    LIVE = 'LIVE'
    OPEN = 'OPEN'

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            arr = list(self.__class__)
            return arr.index(self) < arr.index(other)
        return NotImplemented
# region --- Server ---


class APIState(Enum):
    INIT = 'INIT'
    IDLE = 'IDLE'
    LIVE = 'LIVE'


AD_HOC = False
search_string = ('Ethernet 2', 'en11') if AD_HOC else ('Wi-Fi', 'en0')
for prop in psutil.net_if_addrs()[search_string[0 if platform.system() == 'Windows' else 1]]:
    if prop.family == 2:
        ip = prop.address


class ServerAPI:  # TODO: Potentially, subclass Thread since server is blocking

    DEFAULT_ENDPOINT = Endpoint(ip, 5000)

    app = Flask(__name__)
    http_server = None
    video_chat_server = None
    endpoint = None
    server = None
    state = APIState.INIT
    logger = logging.getLogger('ServerAPI')

    class VideoChatServerBuilder:
        def __init__(self):
            self.video_chat_server = ServerAPI.VideoChatServer()
            self.logger = logging.getLogger('VideoChatServerBuilder')

        def set_api_endpoint(self, endpoint: Endpoint = None):
            ep = SocketAPI.DEFAULT_ENDPOINT if not endpoint else endpoint
            self.video_chat_server.api_endpoint = Endpoint(*ep)  # Makes a copy of the endpoint

            self.logger.info(f"Server's API endpoint set to {endpoint}")

            return self

        def set_user_manager(self, type: UserStorageTypes = None):
            user_storage_type = UserStorageTypes.DICT if type is None else type
            # TODO: can this be a simpler pattern? i.e UserManager(storage=type())... but then where should errors be handled?
            self.video_chat_server.user_manager = UserManager(
                storage=UserStorageFactory().create_storage(user_storage_type))

            self.logger.info(f"Server will use {user_storage_type}-based storage to manage users")

            return self

        def set_websocket_endpoint(self, endpoint: Endpoint = None):
            ep = SocketAPI.DEFAULT_ENDPOINT if not endpoint else endpoint
            self.video_chat_server.websocket_endpoint = Endpoint(*ep)  # Makes a copy of the endpoint
            self.video_chat_server.socket_api_class.endpoint = Endpoint(*ep)  # Makes a copy of the endpoint

            self.logger.info(f"Setting Web Socket endpoint: {endpoint}")

            return self

        def build(self):
            if not (self.video_chat_server.server_state == ServerState.NEW):
                raise BaseException("Cannot re-build server")
            if self.video_chat_server.api_endpoint is None:
                raise BaseException("Must initialize API endpoint before buiding")
            if self.video_chat_server.websocket_endpoint is None:
                raise BaseException("Must initialize websocket endpoint before building")
            if self.video_chat_server.user_manager is None:
                raise BaseException("Must initialize User manager before building")
            # TODO: uncomment when we implement QBER properly
            # if self.video_chat_server.qber_manager is None:
            #     raise BaseException("Must initialize QBER manager before building")
            self.video_chat_server.set_server_state(ServerState.INITIALIZED)
            return self.video_chat_server

    class VideoChatServer:
        def __init__(self):
            self.logger = logging.getLogger('VideoChatServer')

            self.socket_api_class = SocketAPI
            self.server_state: ServerState = ServerState.NEW

            self.websocket_endpoint: Endpoint = None
            self.api_endpoint: Endpoint = None

            self.user_manager: UserManager = None
            # self.qber_manager = None

        def set_server_state(self, state: ServerState):
            if (state < self.server_state):
                return NotImplementedError("State cannot be set to a previous state")
            self.server_state = state
            self.logger.info(f"Socket's state set to {state}")

        def verify_user(self, user_id: str, sess_token: str):
            try:
                user = self.get_user_by_id(user_id)
                return user.sess_token == sess_token
            except UserNotFound:
                return False

        def add_user(self, endpoint):
            try:
                user_id, sess_token = self.user_manager.add_user(endpoint)
                self.logger.info(
                    f"User {user_id} added with sess_token '{sess_token}'.")
                return user_id, sess_token
            except DuplicateUser as e:
                self.logger.error(str(e))
                raise e

        def get_user_by_id(self, user_id):
            try:
                user_info = self.user_manager.get_user_by_id(user_id)
                self.logger.info(f"Retrieved user with ID {user_id}.")
                return user_info
            except UserNotFound as e:
                self.logger.error(str(e))
                raise e

        def remove_user(self, user_id):
            try:
                self.user_manager.remove_user(user_id)
                self.logger.info(f"User {user_id} removed successfully.")
            except UserNotFound as e:
                self.logger.error(str(e))
                raise e

        def set_user_state(self, user_id, state: UserState, peer=None):
            try:
                self.user_manager.set_user_state(user_id, state, peer)
                self.logger.info(f"Updated User {user_id} state: {state} ({peer}).")
            except (UserNotFound, InvalidState) as e:
                self.logger.error(str(e))
                raise e

        def contact_client(self, user_id, route, json):
            endpoint = self.get_user_by_id(user_id).api_endpoint(route)
            self.logger.info(f"Contacting Client API for User {user_id} at {endpoint}.")
            try:
                response = requests.post(str(endpoint), json=json)
            except Exception as e:
                self.logger.error(f"Unable to reach Client API for User {user_id} at endpoint {endpoint}.")
                # TODO: Figure out specifically what exception is raised so I can catch only that,
                # and then handle it instead of re-raising
                # (or maybe re-raise different exception and then caller can handle)
                raise e
            return response

        def start_websocket(self, users: Tuple[User, User]):
            self.logger.info("Starting WebSocket API.")
            if not self.websocket_endpoint:
                raise ServerError(
                    "Cannot start WebSocket API without defined endpoint.")

            self.websocket_instance = self.socket_api_class.init(self, users)
            self.websocket_instance.start()

        def handle_peer_connection(self, user_id: str, peer_id: str):
            if user_id == peer_id:
                raise BadRequest(f"Cannot intermediate connection between User {user_id} and self.")

            # TODO: Validate state(s)
            # if peer is not IDLE, reject
            try:
                requester = self.get_user_by_id(user_id)
            except UserNotFound:
                raise BadRequest(f"User {user_id} does not exist.")
            try:
                host = self.get_user_by_id(peer_id)
            except UserNotFound:
                raise BadRequest(f"User {peer_id} does not exist.")

            if host.state != UserState.IDLE:
                raise InvalidState(f"Cannot connect to peer User {peer_id}: peer must be IDLE.")
            if requester.state != UserState.IDLE:
                raise InvalidState(f"Cannot connect User {user_id} to peer: User must be IDLE.")

            self.logger.info(f"Contacting User {peer_id} to connect to User {user_id}.")

            self.start_websocket(users=(requester, host))

            try:
                response = self.contact_client(peer_id, '/peer_connection', json={
                    'sess_token': host.sess_token,
                    'peer_id': requester.id,
                    'socket_endpoint': tuple(self.websocket_endpoint),
                    'conn_token': self.socket_api_class.conn_token
                })
            except Exception:
                raise BadGateway(f"Unable to reach peer User {peer_id}.")
            print(f"Status code: {response.status_code}")
            if response.status_code != 200:
                f"Peer User {peer_id} refused connection request."
                raise BadGateway(
                    f"Peer User {peer_id} refused connection request.")
            self.logger.info(f"Peer User {peer_id} accepted connection request.")
            return self.websocket_endpoint, self.socket_api_class.conn_token

    @classmethod
    def init(cls, server: VideoChatServer):
        cls.logger.info(f"Attempting to initialize Server API with endpoint {server.api_endpoint}.")
        if cls.state == APIState.LIVE:
            raise ServerError("Cannot reconfigure API during server runtime.")
        cls.video_chat_server = server
        cls.endpoint = server.api_endpoint
        cls.state = APIState.IDLE

    @classmethod
    def start(cls):
        cls.logger.info(f"Starting Server API at {cls.endpoint}.")
        if cls.state == APIState.INIT:
            raise ServerError("Cannot start API before initialization.")
        if cls.state == APIState.LIVE:
            raise ServerError("Cannot start API: already running.")

        print(f"Serving Server API on {cls.endpoint}")
        cls.state = APIState.LIVE
        cls.http_server = WSGIServer(tuple(cls.endpoint), cls.app)
        cls.http_server.serve_forever()

    def HandleAuthentication(func: callable):
        """Decorator to handle commonly encountered exceptions in the API"""
        def wrapper(cls, *args, **kwargs):
            user_id, sess_token = get_parameters(
                request.json, 'user_id', 'sess_token')
            if not cls.video_chat_server.verify_user(user_id, sess_token):
                raise BadAuthentication(f"Authentication failed for user {user_id} with session token '{sess_token}'.")

            return func(cls, *args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper

    def HandleExceptions(endpoint_handler):
        """Decorator to handle commonly encountered exceptions in the API"""
        def handler_with_exceptions(*args, **kwargs):
            cls = ServerAPI
            try:
                return endpoint_handler(cls, *args, **kwargs)
            except BadAuthentication as e:
                cls.logger.info(f"Authentication failed for server at {endpoint_handler.__name__}:\n\t{str(e)}")
                return jsonify({"error_code": "403",
                                "error_message": "Forbidden",
                                "details": remove_last_period(e)}),
                403
            except BadRequest as e:
                cls.logger.info(str(e))
                return jsonify({"error_code": "400",
                                "error_message": "Bad Request",
                                "details": remove_last_period(e)}),
                400
            except ServerError as e:
                cls.logger.error(str(e))
                return jsonify({"error_code": "500",
                                "error_message": "Interal Server Error",
                                "details": remove_last_period(e)}), 500
            except BadGateway as e:
                cls.logger.info(str(e))
                return jsonify({"error_code": "502",
                                "error_message": "Bad Gateway",
                                "details": remove_last_period(e)}),
                502
        handler_with_exceptions.__name__ = endpoint_handler.__name__
        return handler_with_exceptions
    # endregion

    @classmethod
    def kill(cls):
        cls.logger.info("Killing Server API.")
        if cls.state != APIState.LIVE:
            raise ServerError(
                f"Cannot kill Server API when not {APIState.LIVE}.")
        cls.http_server.stop()
        cls.state = APIState.IDLE

    # region --- API Endpoints ---

    @app.route('/create_user', methods=['POST'])
    @HandleExceptions
    def create_user(cls):
        """
        Create and store a user with unique `user_id` and `sess_token` for authentication. Return both.

        Parameters
        ----------
        api_endpoint : tuple
        """
        cls.logger.info("Received request to create a user ID.")

        api_endpoint, = get_parameters(request.json, 'api_endpoint')
        print(api_endpoint)
        user_id, sess_token = cls.video_chat_server.add_user(Endpoint(*api_endpoint))

        return jsonify({'sess_token': sess_token, 'user_id': user_id}), 200

    # @app.route('/remove_user', methods=['DELETE'])
    # async def remove_user(user_id, token):
    #     cls.logger.info("Received request to remove a user ID.")
    #     if not server.verify_identity(user_id,token):
    #         return jsonify({"error_code": "403", "error_message": "Forbidden", "details": "Identity Mismatch"}), 403

    #     try:
    #         server.remove_user(user_id)
    #         return jsonify({"error": "Not Implemented"}), 501
    #     except Exception as e:
    #         cls.logger.error(f"An error occurred while removing user ID: {e}")
    #         return jsonify({"error_code": "500", "error_message": "Internal Server Error", "details": str(e)}), 500

    @app.route('/peer_connection', methods=['POST'])
    @HandleExceptions
    @HandleAuthentication
    def handle_peer_connection(cls):
        """
        Instruct peer to connect to user's provided socket endpoint and self-validate
        with `conn_token` received from requester.

        Request Parameters
        ------------------
        user_id : str
        peer_id : str
        socket_endpoint : tuple(str, int)
        conn_token : str
        """
        user_id, peer_id = get_parameters(request.json, 'user_id', 'peer_id')
        cls.logger.info(f"Received request from User {user_id} to connect with User {peer_id}.")

        endpoint, conn_token = cls.video_chat_server.handle_peer_connection(
            user_id, peer_id)

        return jsonify({'socket_endpoint': tuple(endpoint), 'conn_token': conn_token}), 200


class SocketAPI(Thread):
    DEFAULT_ENDPOINT = Endpoint(ip, 3000)  # TODO: Read from config, maybe?

    app = Flask(__name__)
    socketio = SocketIO(app)
    instance = None  # Make sure this guy gets cleared if the API d/cs or similar
    server = None
    endpoint = None
    state = ServerState.NEW
    namespaces = None

    conn_token = None
    users = {}

    # region --- Utils ---
    logger = logging.getLogger('SocketAPI')  # TODO: Magic string is gross

    @classmethod
    def has_all_users(cls):
        for user in cls.users:
            if not cls.users[user]:
                return False
        return True

    @classmethod
    def generate_conn_token(cls, users: Tuple[User, User]):
        return hashlib.sha256(bytes(a ^ b for a, b in zip(users[0].id.encode(), users[1].id.encode()))).hexdigest()

    @classmethod
    def generate_sess_token(cls, user_id):
        return hashlib.sha256(user_id.encode()).hexdigest()

    @classmethod
    def verify_conn_token(cls, conn_token):
        return conn_token == cls.conn_token

    @classmethod
    def verify_sess_token(cls, user_id, sess_token):
        if user_id not in cls.users:
            raise UserNotFound(f"User {user_id} not found.")
        return sess_token == cls.users[user_id]

    @classmethod
    def verify_connection(cls, auth):
        """
        Parameters
        ----------
        auth : tuple
            (user_id, conn_token)
        """
        user_id, conn_token = auth
        if user_id not in cls.users:
            return False
        if conn_token != cls.conn_token:
            return False
        return True

    def HandleAuthentication(endpoint_handler):
        """
        Decorator to handle authentication for existing users.
        Pass `cls` and `user_id` to handler function.

        NOTE: Assumes `cls` has been passed by @HandleExceptions
        NOTE: This should never be called explicitly

        Parameters
        ----------
        auth : (user_id, sess_token)
            user_id : str,
            sess_token : str
        """
        def handler_with_authentication(cls, auth, *args, **kwargs):
            user_id, sess_token = get_parameters(auth)
            try:
                if not cls.verify_sess_token(user_id, sess_token):
                    raise BadAuthentication(f"Authentication failed for User {user_id} with token '{sess_token}'.")
            except UserNotFound as e:
                raise BadAuthentication(f"Authentication failed for User {user_id} with token '{sess_token}': {str(e)}.")

            endpoint_handler(cls, user_id)
        return handler_with_authentication

    def HandleExceptions(endpoint_handler):
        """
        Decorator to handle commonly encountered exceptions.

        NOTE: This should never be called explicitly.
        """
        def handler_with_exceptions(*args, **kwargs):
            cls = SocketAPI
            return endpoint_handler(cls, *args, **kwargs)
            # try: return endpoint_handler(cls, *args, **kwargs)
            # except UnknownRequester as e:
            #     cls.logger.error(f"Unknown requester at {endpoint_handler.__name__}:\n\t{str(e)}")
            #     return jsonify({"error_code": "403", "error_message": "Forbidden", "details": str(e)}), 403
            # except ParameterError as e:
            #     cls.logger.error(str(e))
            #     return jsonify({"error_code": "400", "error_message": "Bad Request", "details": str(e)}), 400
        return handler_with_exceptions
    # endregion

    # region --- External 'Instance' Interface ---

    @classmethod
    def init(cls, server, users: Tuple[User, User]):
        """
        Parameters
        ----------
        server : VideoChatServer
        users : tuple (requester_id, host_id)
        """
        cls.logger.info(f"Initializing WebSocket API with endpoint {server.websocket_endpoint}.")
        if cls.state >= ServerState.LIVE:
            raise ServerError(
                "Cannot reconfigure WebSocket API during runtime.")

        cls.video_chat_server = server
        cls.endpoint = server.websocket_endpoint
        cls.conn_token = cls.generate_conn_token(users)
        cls.state = ServerState.INIT
        for user in users:
            cls.users[user.id] = User(*user)
        cls.instance = cls()
        return cls.instance

    def run(self):
        cls = SocketAPI
        cls.namespaces = generate_flask_namespace(cls)
        ns = sorted(list(cls.namespaces.keys()))
        for name in ns:
            cls.socketio.on_namespace(cls.namespaces[name])

        cls.logger.info("Starting WebSocket API.")
        if cls.state == ServerState.NEW:
            raise ServerError("Cannot start API before initialization.")
        if cls.state == ServerState.LIVE or cls.state == ServerState.OPEN:
            raise ServerError("Cannot start API: already running.")

        # cls.state = ServerState.LIVE # TODO: BE SURE TO UPDATE ON D/C OR SIMILAR
        # cls.socketio.run(cls.app, host=cls.endpoint.ip, port=cls.endpoint.port)

        while True:
            try:
                print(f"Serving WebSocket API at {cls.endpoint}")
                cls.logger.info(f"Serving WebSocket API at {cls.endpoint}")

                cls.state = ServerState.LIVE
                cls.socketio.run(cls.app, host=cls.endpoint.ip,
                                 port=cls.endpoint.port)
            except OSError:
                print(f"Listener endpoint {cls.endpoint} in use.")
                cls.logger.error(f"Endpoint {cls.endpoint} in use.")

                cls.state = ServerState.INIT
                cls.video_chat_server.set_websocket_endpoint(
                    Endpoint(cls.endpoint.ip, cls.endpoint.port + 1))
                continue
            cls.logger.info("WebSocket API terminated.")
            break

    @classmethod
    def kill(cls):
        cls.logger.info("Killing WebSocket API.")
        if not (cls.state == ServerState.LIVE or cls.state == ServerState.OPEN):
            raise ServerError(f"Cannot kill Socket API when not {ServerState.LIVE} or {ServerState.OPEN}.")
        # "This method must be called from a HTTP or SocketIO handler function."
        cls.socketio.stop()
        cls.state = ServerState.INIT
    # endregion

    # region --- API Endpoints ---

    @socketio.on('connect')  # TODO: Keep track of connection number.
    @HandleExceptions
    def on_connect(cls, auth):
        user_id, conn_token = auth
        cls.logger.info(f"Received Socket connection request from User {user_id} with connection token '{conn_token}'.")
        if cls.state != ServerState.LIVE:
            cls.logger.info(f"Cannot accept connection when already {ServerState.OPEN}.")
            # raise UnknownRequester( ... ) # TODO: Maybe different name?
            # or
            # raise ConnectionRefusedError( ... )
            return False
        if not cls.verify_connection(auth):
            cls.logger.info("Socket connection failed authentication.")
            # raise UnknownRequester( ... ) # TODO: Maybe different name?
            # or
            # raise ConnectionRefusedError( ... )
            return False

        sess_token = cls.generate_sess_token(user_id)
        cls.users[user_id] = sess_token
        cls.logger.info(f"Socket connection from User {user_id} accepted; yielding session token '{sess_token}'")
        emit('token', sess_token)

        # TODO: What is this block?
        # if cls.has_all_users():
        #     cls.logger.info("Socket API acquired all expected users.")
        #     cls.state = ServerState.OPEN

    @socketio.on('message')
    @HandleExceptions
    def on_message(cls, auth, msg):
        user_id, sess_token = auth
        user_id = user_id
        cls.logger.info(f"Received message from User {user_id}: '{msg}'")
        if not cls.verify_sess_token(*auth):
            cls.logger.info(f"Authentication failed for User {user_id} with token '{sess_token}' at on_message.")
            return

        send((user_id, msg), broadcast=True)

    @socketio.on('disconnect')
    @HandleExceptions
    def on_disconnect(cls):
        cls.logger.info("Client disconnected.")
        # Broadcast to all clients to disconnect
        # Close all connections (if that's a thing)
        # Kill Web Socket
        # State returns to INIT

    # endregion
# endregion
# endregion