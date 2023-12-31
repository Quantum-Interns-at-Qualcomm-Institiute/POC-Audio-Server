from abc import ABC, abstractmethod
from bitarray import bitarray
import os
import string
import logging
import secrets
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

# Initialize logging
logging.basicConfig(filename='encryption.log', level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Encryption Schemes
class EncryptionScheme(ABC):
    @abstractmethod
    def encrypt(self, data, key):
        """Encrypt the data using the provided key."""
        pass

    @abstractmethod
    def decrypt(self, data, key):
        """Decrypt the data using the provided key."""
        pass
    
    @abstractmethod
    def get_name(self):
        """Returns the Encryption Scheme's name."""
        pass

class XOREncryption(EncryptionScheme):
    
    def __init__(self):
        self.name = "XOR"

    # data and key are bit arrays with same length
    def encrypt(self, data, key):
        result = bitarray()
        for bit1, bit2 in zip(data, key):
            result.append(bit1 ^ bit2)
        return result
    
    # data and key are bit arrays with same length
    def decrypt(self, data, key):
        result = bitarray()
        for bit1, bit2 in zip(data, key):
            result.append(bit1 ^ bit2)
        return result
    
    def get_name(self):
        return self.name

class DebugEncryption(EncryptionScheme):
    def __init__(self):
        self.name = "Debug"
        
    def encrypt(self, data, key):
        return data
    
    def decrypt(self, data, key):
        return data
    
    def get_name(self):
        return self.name
    

class AESEncryption(EncryptionScheme):
    def __init__(self, bits=128):
        self.bits = bits
        self.name = f"AES-{bits}"
        
    # data and key are bit arrays
    # using AES-CBC
    def encrypt(self, data, key):
        data = data.tobytes()
        key = key.tobytes()
        cipher = AES.new(key, AES.MODE_CBC)
        cipheredData = cipher.encrypt(pad(data, AES.block_size))
        result_data = bitarray()
        result_data.frombytes(cipheredData)
        result_iv = bitarray()
        result_iv.frombytes(cipher.iv)
        return result_iv + result_data
    
    # data and key are bit arrays
    # data contains iv and encrypted data
    def decrypt(self, data, key):
        key = key.tobytes()
        iv = data[:128] #iv always has 128 bits
        cipheredData = data[128:]
        iv = iv.tobytes()
        cipheredData = cipheredData.tobytes()
        cipher = AES.new(key, AES.MODE_CBC, iv=iv)
        originalData = unpad(cipher.decrypt(cipheredData), AES.block_size)
        result = bitarray()
        result.frombytes(originalData)
        return result
    
    def get_name(self):
        return self.name

class EncryptionFactory:
    def create_encryption_scheme(self, type) -> EncryptionScheme:
        if type == "AES":
            return AESEncryption()
        elif type == "XOR":
            return XOREncryption()
        elif type == "DEBUG":
            return DebugEncryption()
        else:
            raise ValueError("Invalid encryption scheme type")

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
# Key Generation

class KeyGenerator(ABC):
    
    @abstractmethod
    def generate_key(self, *args, **kwargs):
        """Generate a key, either randomly or preset."""
        pass

    @abstractmethod
    def get_key(self):
        """Return the generated key."""
        pass
    
class DebugKeyGenerator(KeyGenerator):
    def __init__(self):
            self.key: bitarray = bitarray()
            self.key_length = 0
            
    def speficied_keylength(self, length):
        self.key_length = length
        # Default debug key is alternating 1 and 0
        self.key = bitarray([i % 2 for i in range(self.key_length)])
        
    def specified_key(self, key):
        bit_array = bitarray()
        if type(key) == bitarray:
            bit_array = key
            logger.log(f"Now using key ${key}")
        elif type(key) == string:
            encoded_bytes = key.encode('utf-8')
            bit_array.frombytes(encoded_bytes)
        else:
            logger.error("")
            raise ValueError("Error, only bitarray or string allowed")
        self.key = bit_array
        self.length = len(key)
        
    def generate_key(self, key = None, key_length = 0):
        if key is not None:
            self.specified_key(self, key)
            
        elif key_length != 0:
            self.speficied_keylength(key_length)
        
        else:
            raise ValueError("Invalid parameters")
        
    def get_key(self):
        return self.key
    
class RandomKeyGenerator(KeyGenerator):
    def __init__(self, key_length = 0):
        self.key_length = key_length
        self.key: bitarray = None
        
    def generate_key(self, key_length = 0):
        if key_length:
            self.key_length = key_length
        elif self.key_length < 1:
            logger.error(f"Try to make key of length {key_length}")
            raise ValueError("Error, please make key length nonzero")
        self.key = bitarray([int(b) for b in format(int.from_bytes(os.urandom((self.key_length + 7) // 8), 'big'), f'0{self.key_length}b')[:self.key_length]])

    def get_key(self):
        return self.key

class KeyGeneratorFactory:

    def create_key_generator(self, type) -> KeyGenerator:
        if type == "DEBUG":
            return DebugKeyGenerator()
        elif type == "RANDOM":
            return RandomKeyGenerator()
        else:
            raise ValueError("Invalid encryption scheme type")

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class KeyExchange(ABC):

    @abstractmethod
    def get_key(self):
        """Generate a key for exchange."""
        pass
    
    @abstractmethod
    def send_key(self):
        """Send the generated key."""
        pass
        
