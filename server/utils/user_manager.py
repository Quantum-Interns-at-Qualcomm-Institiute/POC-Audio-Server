# from __future__ import annotations

# region --- Logging ---
import hashlib
from random import choice
from string import ascii_letters, digits
from abc import ABC, abstractmethod
from .user import User
from .user import UserState
from custom_logging import logger
# endregion


# region --- Utils ---


class DuplicateUser(Exception):
    pass


class UserNotFound(Exception):
    pass


class InvalidState(Exception):
    pass
# endregion


# region --- Storage ---


class UserStorageInterface(ABC):

    @abstractmethod
    def add_user(self, user_id, user_info):
        pass

    @abstractmethod
    def update_user(self, user_id, user_info):
        pass

    @abstractmethod
    def get_user(self, user_id):
        pass

    @abstractmethod
    def remove_user(self, user_id):
        pass

    @abstractmethod
    def has_user(self, user_id):
        pass


class DictUserStorage(UserStorageInterface):

    def __init__(self):
        self.users = {}

    def add_user(self, user_id, user_info):
        if user_id in self.users:
            raise DuplicateUser(f"Cannot add user {
                                user_id}: User already exists.")
        self.users[user_id] = user_info

    def update_user(self, user_id, user_info):
        if user_id not in self.users:
            raise UserNotFound(f"Cannot update user {
                               user_id}: User does not exist.")
        self.users[user_id] = user_info

    def get_user(self, user_id):
        if user_id not in self.users:
            raise UserNotFound(f"Cannot get user {
                               user_id}: User does not exist.")
        return self.users.get(user_id, None)

    def remove_user(self, user_id):
        if user_id not in self.users:
            raise UserNotFound(f"Cannot remove user {
                               user_id}: User does not exist.")
        del self.users[user_id]

    def has_user(self, user_id):
        return user_id in self.users


class UserStorageFactory:
    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def create_storage(self, storage_type: str, **kwargs) -> UserStorageInterface:
        if storage_type == 'DICT':
            return DictUserStorage()
        else:
            raise ValueError(f"Invalid storage type: {storage_type}")
# endregion


# region --- User Manager ---


class UserManager:

    def __init__(self, storage: UserStorageInterface):
        self.storage = storage

    # I would personally just generate a completely random string every time, but we do this in Andy's interest of having perfect reproducibility during testing
    def generate_user_id(self):
        # logger.debug(f"Generating User ID for user with API Endpoint {endpoint}.")
        # hash_object = hashlib.sha256(endpoint.encode())
        # user_id = hash_object.hexdigest()[:5]

        # while self.storage.has_user(user_id):
        #     hash_object = hashlib.sha256(hash_object.hexdigest().encode())
        #     user_id = hash_object.hexdigest()[:5]

        return ''.join(choice(ascii_letters + digits) for _ in range(5)).lower()

    # See note for generate_user_id(); the particular choice of seed here is a bit AIDS, though.
    # Also note uniqueness is not strictly necessary for tokens, so I've omitted it.
    def generate_token(self, user_id):
        logger.debug(f"Generating token for User {user_id}.")
        hash_object = hashlib.sha256(user_id.encode())
        token = hash_object.hexdigest()

        return token

    def add_user(self):
        user_id = self.generate_user_id()
        # user_info = User(endpoint)
        try:
            self.storage.add_user(user_id, None)
            logger.debug(f"Added User {user_id}'.")
            return user_id
        except DuplicateUser as e:
            logger.error(str(e))
            raise e

    def set_user_state(self, user_id, state: UserState, peer=None):
        if (state == UserState.IDLE) ^ (peer == None):
            raise InvalidState(f"Cannot set state {state} ({peer}) for User {
                               user_id}: Invalid state.")

        try:
            user_info = self.storage.get_user(user_id)
            user_info.state = state
            user_info.peer = peer
            self.storage.update_user(user_id, user_info)
            logger.debug(f"Updated User {user_id} state: {
                state} ({peer}).")
        except UserNotFound as e:
            logger.error(str(e))
            raise e

    def get_user(self, user_id) -> User:
        try:
            user_info = self.storage.get_user(user_id)
            logger.debug(f"Retrieved user info for User {user_id}.")
            return User(*user_info)
        except UserNotFound as e:
            logger.error(str(e))
            raise e

    def remove_user(self, user_id):
        try:
            self.storage.remove_user(user_id)
            logger.debug(f"Removed User {user_id}.")
        except UserNotFound as e:
            logger.error(str(e))
# endregion
