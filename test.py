import asyncio
import logging
from threading import Thread
import cv2
import ffmpeg
from PIL import Image
import numpy as np

video_shape = (640, 480, 3)
frame_rate = 15

def encrypt(data: bytes):
    return data
decrypt = encrypt





# Producer produces encryted image data
inpipe = ffmpeg.input(
    'pipe:',
    format='rawvideo',
    pix_fmt='bgr24',
    s='{}x{}'.format(
        video_shape[0], video_shape[1]),
    r=frame_rate,
)

producer_output = ffmpeg.output(
    inpipe, 'pipe:', vcodec='libx264', f='ismv',
    preset='ultrafast', tune='zerolatency')

cap = cv2.VideoCapture(0)

def produce():
    _, image = cap.read()
    image = cv2.resize(
        image, (video_shape[0], video_shape[1]))
    data = image.tobytes()

    data = producer_output.run(
        input=data, capture_stdout=True, quiet=True)[0]

    data = encrypt(data)

    return data






# Consumer displays decrypted image data
inpipe1 = ffmpeg.input('pipe:')
consumer_output = ffmpeg.output(inpipe1, 'pipe:', format='rawvideo', pix_fmt='rgb24')

def consume(data):
        data = decrypt(data)

        # Data is now an ISMV format file in memory
        data = consumer_output.run(input=data, capture_stdout=True,
                                quiet=True)[0]
        
        image = np.zeros((video_shape[1], video_shape[0], video_shape[2]), dtype=np.uint8)
        for i in range(video_shape[1]):
             for j in range(video_shape[0]):
                  for k in range(video_shape[2]):
                       image[i][j][k] = data[k + j * video_shape[2] + i * video_shape[2] * video_shape[0]]

        image = Image.fromarray(image)
        # image = Image.frombytes(mode="RGB", size=(video_shape[0], video_shape[1]), data=image)
        data = image.tobytes()
        image.show("Output")


for i in range(5):
    data = produce()
    
    # --------- send data -----------

    consume(data)



