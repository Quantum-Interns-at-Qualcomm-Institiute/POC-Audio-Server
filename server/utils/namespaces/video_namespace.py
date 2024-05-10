import asyncio
import logging
from threading import Thread
import cv2
import ffmpeg
import numpy as np

from .base_namespaces import AVClientNamespace
logging.basicConfig(filename='./logs/server.log', level=logging.DEBUG,
                    format='[%(asctime)s] (%(levelname)s) %(name)s.%(funcName)s: %(message)s',
                    datefmt='%H:%M:%S')


class VideoClientNamespace(AVClientNamespace):

    def on_connect(self):
        super().on_connect()
        inpipe = ffmpeg.input('pipe:')
        self.output = ffmpeg.output(
            inpipe, 'pipe:', format='rawvideo', pix_fmt='rgb24')

        async def send_video():
            await asyncio.sleep(2)
            cap = cv2.VideoCapture(0)

            # doesn't work
            # cam.set(cv2.CAP_PROP_FRAME_WIDTH, video_shape[1])
            # cam.set(cv2.CAP_PROP_FRAME_HEIGHT, video_shape[0])

            inpipe = ffmpeg.input(
                'pipe:',
                format='rawvideo',
                pix_fmt='rgb24',
                s='{}x{}'.format(
                    self.av.video_shape[1], self.av.video_shape[0]),
                r=self.av.frame_rate,
            )

            output = ffmpeg.output(
                inpipe, 'pipe:', vcodec='libx264', f='ismv', preset='ultrafast', tune='zerolatency')

            while True:
                cur_key_idx, key = self.av.key

                result, image = cap.read()
                image = cv2.resize(
                    image, (self.av.video_shape[1], self.av.video_shape[0]))
                data = image.tobytes()

                data = output.run(
                    input=data, capture_stdout=True, quiet=True)[0]

                data = self.av.encryption.encrypt(data, key)

                self.send(cur_key_idx.to_bytes(4, 'big') + data)

                await asyncio.sleep(1 / self.av.frame_rate / 5)

        Thread(target=asyncio.run, args=(send_video(),)).start()

    def on_message(self, user_id, msg):
        super().on_message(user_id, msg)

        async def handle_message():
            if user_id == self.cls.user_id:
                return

            cur_key_idx, key = self.av.key

            key_idx = int.from_bytes(msg[:4], 'big')
            if (key_idx != cur_key_idx):
                return
            data = msg[4:]

            data = self.av.encryption.decrypt(data, key)

            data = self.output.run(
                input=data, capture_stdout=True, quiet=True)[0]

            data = np.frombuffer(data, dtype=np.uint8).reshape(
                self.av.video_shape)

            self.cls.video[user_id] = data

        asyncio.run(handle_message())