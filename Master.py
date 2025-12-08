import tkinter as tk
from tkinter import ttk
import threading
import queue
import time
import traceback
from pymodbus.client.sync import ModbusSerialClient

# CONFIG
PORT = 'COM1'
SLAVE_ID = 1


"""
Master.py

这是主站 (Master) 的图形界面与 Modbus 轮询逻辑。

设计要点（高层）
- 使用 `pymodbus` 的 `ModbusSerialClient`（ASCII 模式）通过串口与从站通信。
- 所有阻塞 I/O 操作都在后台线程 `_background_reader` 中完成，避免阻塞 tkinter 主循环。
- 后台线程把最新的读取结果放到一个容量为 1 的 `Queue`（`self._q`）中，主线程通过 `_poll_ui` 定期取出并更新 UI。
- 为避免串口并发访问导致帧错乱，所有访问 `self.client` 的操作都被 `self._client_lock` 锁保护。
- 在连续失败一定次数后，会尝试自动重连并把状态通过队列传回 UI（'reconnected' / 'disconnected'）。

注：本文件已去掉过多的控制台调试打印，UI 会通过状态/日志区展示关键状态。
"""


class MasterWindow:
    """
    主窗口类：

    职责：
    - 初始化 Modbus 客户端并尝试连接。
    - 启动后台线程持续读取从站保持寄存器（寄存器 0），把最新值放入队列。
    - 提供 Start/Stop 按钮（写 Coil 0）和状态/日志显示。

    重要内部结构：
    - `self.client`：pymodbus 串口客户端（ASCII）。
    - `self._client_lock`：线程锁，保护所有对 `self.client` 的访问。
    - `self._q`：队列，用于后台线程 -> UI 的单向通信（只保留最新一项）。
    - `self._stop`：事件，用于安全停止后台线程。
    - `self._thread`：后台线程引用。
    - `self._failures` / `self._reconnect_after`：简单的失败计数与重连阈值。
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Master — 控制面板")
        self.root.geometry("380x220")
        self.root.resizable(False, False)

        # Modbus 客户端（显式使用 ASCII 格式，并稍长的超时以减少间歇性超时）
        self.client = ModbusSerialClient(method='ascii', port=PORT, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=3)
        # 立即尝试连接，连接结果用于 UI 初始显示
        self._connected = self.client.connect()

        # 串口访问锁，确保写与读不会并发发生导致帧混乱
        self._client_lock = threading.Lock()

        # 后台读写所需结构
        # 使用 maxsize=1 保证队列中只保留最新的读取结果（生产者覆盖旧值）
        self._q = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._failures = 0
        self._reconnect_after = 5

        # 启动后台读取线程（守护线程，随主程序退出）
        self._thread = threading.Thread(target=self._background_reader, daemon=True)
        self._thread.start()

        # 初始化 UI 并开始轮询队列更新 UI
        self._build_ui()
        self._poll_ui()

    def _build_ui(self):

        header = ttk.Frame(self.root, padding=(10, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, text="设备远程控制", font=("Calibri", 14, "bold")).pack(side=tk.LEFT)

        status_frame = ttk.Frame(self.root, padding=(10, 6))
        status_frame.pack(fill=tk.X)
        ttk.Label(status_frame, text="端口:").pack(side=tk.LEFT)
        ttk.Label(status_frame, text=PORT, foreground="#3333AA").pack(side=tk.LEFT, padx=(4, 20))
        self._status_label = ttk.Label(status_frame, text=("已连接" if self._connected else "未连接"), foreground=("green" if self._connected else "red"))
        self._status_label.pack(side=tk.LEFT)

        main = ttk.Frame(self.root, padding=(20, 10))
        main.pack(fill=tk.BOTH, expand=True)
        self._value_var = tk.StringVar(value="从站运行次数: 0")
        lbl = ttk.Label(main, textvariable=self._value_var, font=("Consolas", 24), foreground="#5E2A7E")
        lbl.pack(pady=6)

        btns = ttk.Frame(main)
        btns.pack(pady=6)
        start = ttk.Button(btns, text="Start", command=lambda: self._send(True))
        stop = ttk.Button(btns, text="Stop", command=lambda: self._send(False))
        start.grid(row=0, column=0, padx=8)
        stop.grid(row=0, column=1, padx=8)


        footer = ttk.Frame(self.root, padding=(10, 6))
        footer.pack(fill=tk.X)
        self._log_var = tk.StringVar(value="就绪")
        ttk.Label(footer, textvariable=self._log_var, font=("Arial", 9)).pack(side=tk.LEFT)

    def _send(self, state: bool):
        try:
            with self._client_lock:
                self.client.write_coil(0, state, slave=SLAVE_ID)
            self._log_var.set(f"已发送: {'启动' if state else '停止'}")
        except Exception as err:
            self._log_var.set(f"发送失败: {err}")
            # 错误记录显示在 UI 中，控制台保持简洁

    def _background_reader(self):
        """后台线程：循环读取保持寄存器并把结果放入队列。包含简单的失败计数与自动重连。"""
        while not self._stop.is_set():
            try:
                with self._client_lock:
                    resp = self.client.read_holding_registers(0, 1, slave=SLAVE_ID)
                if resp is None:
                    val, err = None, 'timeout'
                elif hasattr(resp, 'isError') and resp.isError():
                    val, err = None, f'modbus_error:{repr(resp)}'
                elif hasattr(resp, 'registers') and resp.registers:
                    val, err = resp.registers[0], None
                else:
                    val, err = None, f'unknown:{repr(resp)}'

                # 只保留最新
                try:
                    while not self._q.empty():
                        self._q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._q.put_nowait((val, err))
                except queue.Full:
                    pass

                # 失败计数和自动重连
                if val is not None:
                    self._failures = 0
                else:
                    self._failures += 1
                    if self._failures >= self._reconnect_after:
                        try:
                            try:
                                self.client.close()
                            except Exception:
                                pass
                            time.sleep(0.4)
                            ok = False
                            try:
                                with self._client_lock:
                                    ok = self.client.connect()
                            except Exception:
                                # 重连时静默处理错误
                                ok = False
                            if ok:
                                self._failures = 0
                                try:
                                    self._q.put_nowait((None, 'reconnected'))
                                except queue.Full:
                                    pass
                            else:
                                try:
                                    self._q.put_nowait((None, 'disconnected'))
                                except queue.Full:
                                    pass
                        except Exception:
                            # 重连内部异常静默处理
                            pass
                
            except Exception as e:
                # 简化处理：记录异常到队列用于 UI 更新，其他内部保持静默
                s = repr(e)
                try:
                    self._q.put_nowait((None, f'exception:{s}'))
                except Exception:
                    pass
            # 放宽轮询间隔以减轻虚拟串口压力
            time.sleep(0.5)

    def _poll_ui(self):
        """主线程周期性检查队列并更新界面。"""
        try:
            try:
                val, err = self._q.get_nowait()
            except queue.Empty:
                val, err = None, None

            if err == 'reconnected':
                self._status_label.config(text="已连接", foreground="green")
                self._log_var.set("重连成功")
            elif err == 'disconnected':
                self._status_label.config(text="未连接", foreground="red")
                self._log_var.set("重连失败")
            elif err is not None:
                # 其它错误：超时 / modbus_error / exception
                self._status_label.config(text="通信异常", foreground="orange")
                self._log_var.set(str(err))
            elif val is not None:
                # 正常取到数值
                self._status_label.config(text="已连接", foreground="green")
                self._value_var.set(f"从站运行次数: {val}")

        except Exception as exc:
            # UI 更新异常静默处理（不输出到控制台）
            pass
        finally:
            self.root.after(700, self._poll_ui)

    def close(self):
        # 停止后台线程并安全关闭 Modbus 客户端
        try:
            self._stop.set()
        except Exception:
            pass
        try:
            if self._thread.is_alive():
                self._thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            self.client.close()
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = MasterWindow(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.close(), root.destroy()))
    root.mainloop()


if __name__ == '__main__':
    main()