
from enum import Enum
from functools import total_ordering
from typing import Callable, Optional, Union

from exceptions import ClientErrors


class Endpoint:
    def __init__(self, ip: str, port: int, route: Optional[str] = None):
        self.ip = ip[8 if ip.startswith('https://') else 7 if ip.startswith('http://') else 0:]
        self.port = port

        if not route or route == '/':
            self.route = None
        else:
            self.route = route[1 if route.startswith('/') else 0:]

    def __call__(self, route: Optional[str] = None):
        if not route:
            return self
        endpoint = Endpoint(*self)
        endpoint.route = route
        return Endpoint(*endpoint)  # Re-instantiating fixes slashes in `route`

    def _to_string(self):
        ip = self.ip if self.ip else 'localhost'
        port = f":{self.port}" if self.port else ''
        route = f"/{self.route}" if self.route else ''
        return f"http://{ip}{port}{route}"

    def __str__(self):
        return self._to_string()

    def __repr__(self):
        return self._to_string()

    def __unicode__(self):
        return self._to_string()

    def __iter__(self):
        yield self.ip if self.ip else 'localhost'
        if self.port:
            yield self.port
        if self.route:
            yield self.route


def remove_last_period(text: str):
    return text[0:-1] if text[-1] == "." else text


def display_message(user_id, msg):
    print(f"({user_id}): {msg}")


def get_parameters(data: Union[list, tuple, dict], *args: Union[list, str, tuple[str, Callable], None]):
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
    arg : tuple(str, func), optional
        If `data` is a dict
    """

    if isinstance(data, list) or isinstance(data, tuple):
        validators = args if len(args == 0) else args[0]
        if len(validators) == 0:
            return (*data,)
        if len(data) != len(validators):
            raise ClientErrors.PARAMETERERROR(
                f"Expected {len(validators)} parameters but received {len(data)}.")

        param_vals = ()
        for param, validator in zip(data, validators):
            if not validator:
                validator = lambda x: not not x

            if not validator(param):
                raise ClientErrors.INVALIDPARAMETER(
                    "Parameter failed validation.")
            param_vals += (*param_vals, param)
        return param_vals
    if isinstance(data, dict):
        param_vals = ()
        for arg in args:
            if isinstance(arg, tuple):
                param, validator = arg
            else:
                param = arg
                # Truthy/Falsy coersion to bool
                validator = lambda x: not not x

            if param in data:
                param_val = data.get(param)
            else:
                raise ClientErrors.PARAMETERERROR(f"Expected parameter '{param}' not received.")

            if not validator(param_val):
                raise ClientErrors.INVALIDPARAMETER(
                    f"Parameter '{param}' failed validation.")

            param_vals = (*param_vals, param_val)
        return param_vals


@total_ordering
class APIState(Enum):
    NEW = 'NEW'
    INITIALIZED = 'INITIALIZED'
    LIVE = 'LIVE'

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            arr = list(self.__class__)
            return arr.index(self) < arr.index(other)
        return NotImplemented


@total_ordering
class ClientState(Enum):
    NEW = 'NEW'  # Uninitialized
    INITIALIZED = 'INITIALIZED'  # Initialized
    CONNECTING = 'CONNECTING'
    LIVE = 'LIVE'  # Connected to server
    CONNECTED = 'CONNECTED'  # Connected to peer

    def __lt__(cls, other):
        if cls.__class__ is other.__class__:
            arr = list(cls.__class__)
            return arr.index(cls) < arr.index(other)
        return NotImplemented
