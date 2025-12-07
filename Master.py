import tkinter as tk
import threading
import queue
import time
import traceback
from pymodbus.client.sync import ModbusSerialClient

PORT = 'COM1'
SLAVE_ID = 1

class MasterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("主站控制面板")
        self.root.geometry("320x240")

        self.client = ModbusSerialClient(
            port=PORT, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=2
        )
        # 尝试连接并保存连接状态
        self._connected = self.client.connect()
        if not self._connected:
            print("串口连接失败！")

        # 背景线程用的队列与停止事件，避免在 GUI 主线程做阻塞 I/O
        self._data_q = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        # 失败计数与自动重连阈值
        self._consec_failures = 0
        self._reconnect_threshold = 5
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        tk.Label(root, text="控制面板", font=("宋体", 12, "bold")).pack(pady=10)

        self.lbl_remote_count = tk.Label(root, text="从站运行次数: 0", font=("宋体", 16), fg="purple")
        self.lbl_remote_count.pack(pady=10)

        # 连接状态标签
        self.lbl_conn = tk.Label(root, text=("连接状态: 已连接" if self._connected else "连接状态: 未连接"), font=("Arial", 10))
        self.lbl_conn.pack(pady=2)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)


        tk.Button(btn_frame, text="启动设备", bg="green", fg="white", width=10,
                  command=lambda: self.send_cmd(True)).pack(side=tk.LEFT, padx=5)

        tk.Button(btn_frame, text="停止设备", bg="red", fg="white", width=10,
                  command=lambda: self.send_cmd(False)).pack(side=tk.LEFT, padx=5)

        self.update_data()

    def send_cmd(self, state):
        try:
            self.client.write_coil(0, state, slave=SLAVE_ID)
        except Exception as e:
            print(f"发送错误: {e}")

    def _reader_loop(self):
        """后台线程：循环读取保持寄存器，把最新结果放入队列供 GUI 非阻塞读取"""
        while not self._stop_event.is_set():
            try:
                rr = self.client.read_holding_registers(0, 1, slave=SLAVE_ID)
                if rr is None:
                    val, err = None, 'timeout'
                elif hasattr(rr, 'isError') and rr.isError():
                    val, err = None, f'modbus_error:{repr(rr)}'
                elif hasattr(rr, 'registers') and rr.registers:
                    val, err = rr.registers[0], None
                else:
                    val, err = None, f'unknown:{repr(rr)}'

                # 保证队列只保留最新一条数据
                try:
                    while not self._data_q.empty():
                        self._data_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._data_q.put((val, err), block=False)
                except queue.Full:
                    pass
                # 根据读取结果维护失败计数与自动重连
                if val is not None:
                    self._consec_failures = 0
                else:
                    self._consec_failures += 1
                    if self._consec_failures >= self._reconnect_threshold:
                        # 尝试重连
                        try:
                            print("连续读取失败，尝试重连串口...")
                            try:
                                self.client.close()
                            except Exception:
                                pass
                            time.sleep(0.5)
                            ok = False
                            try:
                                ok = self.client.connect()
                            except Exception as e:
                                print("重连时异常:", e)
                            if ok:
                                print("重连成功")
                                self._consec_failures = 0
                                try:
                                    # 通知 GUI 已重连
                                    self._data_q.put((None, 'connected'), block=False)
                                except queue.Full:
                                    pass
                            else:
                                print("重连失败")
                                try:
                                    self._data_q.put((None, 'disconnected'), block=False)
                                except queue.Full:
                                    pass
                        except Exception as e:
                            print("重连异常:", e)
            except Exception as e:
                try:
                    while not self._data_q.empty():
                        self._data_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._data_q.put((None, f'exception:{e}'), block=False)
                except queue.Full:
                    pass
                traceback.print_exc()

            time.sleep(0.1)

    def update_data(self):
        try:
            # 非阻塞地从队列获取最新读取结果
            val, err = None, None
            try:
                val, err = self._data_q.get_nowait()
            except queue.Empty:
                val, err = None, None

            # 根据 queue 的 err 更新连接状态与数值显示
            if err == 'connected':
                self.lbl_conn.config(text="连接状态: 已连接")
            elif err == 'disconnected':
                self.lbl_conn.config(text="连接状态: 未连接")
            elif err is None and val is not None:
                # 正常响应
                self.lbl_conn.config(text="连接状态: 已连接")
                self.lbl_remote_count.config(text=f"从站运行次数: {val}")
            else:
                # 尚无可用新数据，保持当前显示
                pass
        except Exception as e:
            print("update_data 异常:", e)
            traceback.print_exc()
        finally:
            self.root.after(500, self.update_data)

    def on_close(self):
        # 停止后台线程并关闭串口
        try:
            self._stop_event.set()
        except Exception:
            pass
        try:
            if hasattr(self, '_reader_thread') and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            self.client.close()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MasterApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()