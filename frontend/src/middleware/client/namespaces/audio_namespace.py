import asyncio
import logging
from threading import Thread
import pyaudio
from .base_namespaces import AVClientNamespace

logging.basicConfig(filename='./src/middleware/logs/client.log',
                    level=logging.INFO,
                    format='[%(asctime)s] (%(levelname)s) %(name)s.%(funcName)s: %(message)s',
                    datefmt='%H:%M:%S')


class AudioClientNamespace(AVClientNamespace):

    def on_connect(self):
        super().on_connect()
        audio = pyaudio.PyAudio()
        self.stream = audio.open(format=pyaudio.paInt16, channels=1,
                                 rate=self.av_controller.sample_rate, output=True,
                                 frames_per_buffer=self.av_controller.frames_per_buffer)
        self.stream.start_stream()

        async def send_audio():
            await asyncio.sleep(2)
            audio = pyaudio.PyAudio()
            stream = audio.open(format=pyaudio.paInt16, channels=1,
                                rate=self.av_controller.sample_rate, input=True,
                                frames_per_buffer=self.av_controller.frames_per_buffer)

            while True:
                key_idx, key = self.av_controller.keys[-self.av_controller.key_buffer_size]

                data = stream.read(self.av_controller.frames_per_buffer,
                                   exception_on_overflow=False)

                if self.av_controller.encryption is not None:
                    data = self.av_controller.encryption.encrypt(data, key)
                self.send(key_idx.to_bytes(4, 'big') + data)
                await asyncio.sleep(self.av_controller.audio_wait)

        Thread(target=asyncio.run, args=(send_audio(),)).start()

    def on_message(self, user_id, msg):
        super().on_message(user_id, msg)

        async def handle_message():
            if user_id == self.client_socket.user_id:
                return

            key_idx = int.from_bytes(msg[:4], 'big')
            key = self.av_controller.keys[key_idx][1]
            data = msg[4:]

            data = self.av_controller.encryption.decrypt(data, key)
            self.stream.write(
                data, num_frames=self.av_controller.frames_per_buffer,
                exception_on_underflow=False)

        asyncio.run(handle_message())
