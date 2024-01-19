import cv2
from ultralytics import YOLO
import DJIdecoder
from DJIdecoder import libh264decoder
import threading
import time
import numpy as np
import signal
from PIL import Image as PImage
import cv2
import robot_network
from robot_network import robot_connection
import enum
import queue

# 加载预训练的 YOLOv8 模型
model = YOLO('../runs/best.pt')


class RobotLiveview(object):
    USB_DIRECT_IP = '192.168.42.2'

    def __init__(self, connection_type):
        self.connection = robot_connection.RobotConnection()
        self.connection_type = connection_type

        self.video_decoder = libh264decoder.H264Decoder()
        libh264decoder.disable_logging()

        self.video_decoder_thread = threading.Thread(target=self._video_decoder_task)
        self.video_decoder_msg_queue = queue.Queue(64)
        self.video_display_thread = threading.Thread(target=self._video_display_task)

        self.command_ack_list = []

        self.is_shutdown = True

    def open(self):
        self.connection.update_robot_ip(RobotLiveview.USB_DIRECT_IP)
        self.is_shutdown = not self.connection.open()

    def close(self):
        self.is_shutdown = True
        self.video_decoder_thread.join()
        self.video_display_thread.join()
        self.connection.close()

    def display(self):
        self.command('command')
        time.sleep(1)
        self.command('stream on')

        self.video_decoder_thread.start()
        self.video_display_thread.start()

        print('display!')

    def command(self, msg):
        # TODO: TO MAKE SendSync()
        #       CHECK THE ACK AND SEQ
        self.connection.send_data(msg)

    def _h264_decode(self, packet_data):
        res_frame_list = []
        frames = self.video_decoder.decode(packet_data)
        for framedata in frames:
            (frame, w, h, ls) = framedata
            if frame is not None:
                frame = np.frombuffer(frame, dtype=np.ubyte, count=len(frame))
                frame = (frame.reshape((h, int(ls / 3), 3)))
                frame = frame[:, :w, :]
                res_frame_list.append(frame)

        return res_frame_list

    def _video_decoder_task(self):
        package_data = b''

        self.connection.start_video_recv()

        while not self.is_shutdown:
            buff = self.connection.recv_video_data()
            if buff:
                package_data += buff
                if len(buff) != 1460:
                    for frame in self._h264_decode(package_data):
                        try:
                            self.video_decoder_msg_queue.put(frame, timeout=2)
                        except Exception as e:
                            if self.is_shutdown:
                                break
                            print('video decoder queue full')
                            continue
                    package_data = b''

        self.connection.stop_video_recv()

    def _video_display_task(self):
        while not self.is_shutdown:
            try:
                frame = self.video_decoder_msg_queue.get(timeout=2)
            except Exception as e:
                if self.is_shutdown:
                    cap.release()
                    cv2.destroyAllWindows()
                    break
                print('video decoder queue empty')
                continue
            image = PImage.fromarray(frame)
            # img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

            # 在该帧上运行YOLOv8推理
            results = model(image)

            # 在帧上可视化结果
            annotated_frame = results[0].plot()

            # 显示带注释的帧
            cv2.imshow("YOLOv8", annotated_frame)
            # cv2.imshow("Liveview", img)
            cv2.waitKey(1)


def test():
    robot = RobotLiveview(3)

    def exit(signum, frame):
        robot.close()

    signal.signal(signal.SIGINT, exit)
    signal.signal(signal.SIGTERM, exit)

    robot.open()
    robot.display()


if __name__ == '__main__':
    test()
