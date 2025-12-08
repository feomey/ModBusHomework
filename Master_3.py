import tkinter as tk
from tkinter import ttk
import threading
import queue
import time
from pymodbus.client.sync import ModbusSerialClient

try:
    from Master import PORT as PORT_DEFAULT
except Exception:
    PORT_DEFAULT = 'COM1'
try:
    from Master import SLAVE_ID as SLAVE_ID
except Exception:
    SLAVE_ID = 1


class MasterApp:
    """简洁的 Modbus ASCII 主站 GUI（支持 FC01/FC05/FC03 的演示）

    设计要点：
    - 用户可选择串口并 Connect/Disconnect。
    - 使用后台线程周期性读取保持寄存器（FC03），将最新值通过 `queue` 传回主线程更新 UI。
    - 写线圈（FC05）由按钮触发；读线圈（FC01）由从站响应（在本示例中由 Slave 模拟）。
    - 所有对 `client` 的访问均由 `self.lock` 保护，避免并发导致帧错乱。
    """

    def __init__(self, root):
        self.root = root
        self.root.title('Modbus 主站')
        self.root.geometry('420x220')

        self.client = None
        self.lock = threading.Lock()
        self.reader_thread = None
        self.stop_reader = threading.Event()
        self.data_q = queue.Queue(maxsize=1)
        

        self._build_ui()
        self._after_id = None
        self._poll_ui()

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(frm)
        top.pack(fill=tk.X, pady=(0,8))

        ttk.Label(top, text='串口：').pack(side=tk.LEFT)
        # 使用来自 `Master.py` 的默认端口，不提供手动选择
        self.port_var = tk.StringVar(value=PORT_DEFAULT)
        ttk.Label(top, textvariable=self.port_var).pack(side=tk.LEFT, padx=6)

        self.connect_btn = ttk.Button(top, text='连接', command=self.connect)
        self.connect_btn.pack(side=tk.LEFT, padx=6)
        self.disconnect_btn = ttk.Button(top, text='断开', command=self.disconnect)
        self.disconnect_btn.pack(side=tk.LEFT)

        status = ttk.Frame(frm)
        status.pack(fill=tk.X)
        ttk.Label(status, text='状态：').pack(side=tk.LEFT)
        self.status_lbl = ttk.Label(status, text='未连接', foreground='red')
        self.status_lbl.pack(side=tk.LEFT, padx=(6,0))

        middle = ttk.Frame(frm)
        middle.pack(fill=tk.X, pady=10)
        ttk.Label(middle, text='保持寄存器 0：').pack(side=tk.LEFT)
        self.hr_var = tk.StringVar(value='-')
        ttk.Label(middle, textvariable=self.hr_var, font=('Consolas', 16)).pack(side=tk.LEFT, padx=(8,0))

        # Coil 显示与读取按钮
        ttk.Label(middle, text='  Coil0：').pack(side=tk.LEFT, padx=(12,0))
        self.coil_var = tk.StringVar(value='-')
        ttk.Label(middle, textvariable=self.coil_var, font=('Consolas', 14)).pack(side=tk.LEFT, padx=(4,0))
        self.read_btn = ttk.Button(middle, text='读取线圈', command=self.read_coil_once)
        self.read_btn.pack(side=tk.LEFT, padx=(8,0))

        btns = ttk.Frame(frm)
        btns.pack()
        self.start_btn = ttk.Button(btns, text='启动（写线圈0=开）', command=lambda: self.write_coil(True))
        self.stop_btn = ttk.Button(btns, text='停止（写线圈0=关）', command=lambda: self.write_coil(False))
        self.start_btn.grid(row=0, column=0, padx=8)
        self.stop_btn.grid(row=0, column=1, padx=8)

        footer = ttk.Frame(frm)
        footer.pack(fill=tk.X, pady=(10,0))
        self.log_var = tk.StringVar(value='就绪')
        ttk.Label(footer, textvariable=self.log_var).pack(side=tk.LEFT)

        # 禁用写按钮直到连接
        self._set_connected(False)

    def _set_connected(self, ok: bool):
        if ok:
            self.status_lbl.config(text='已连接', foreground='green')
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.NORMAL)
            # 启用手动读取线圈按钮
            try:
                self.read_btn.config(state=tk.NORMAL)
            except Exception:
                pass
        else:
            self.status_lbl.config(text='未连接', foreground='red')
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.DISABLED)
            try:
                self.read_btn.config(state=tk.DISABLED)
            except Exception:
                pass

    def connect(self):
        port = self.port_var.get()
        try:
            # 建立 ASCII 模式客户端
            self.client = ModbusSerialClient(method='ascii', port=port, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=3)
            ok = self.client.connect()
            if not ok:
                self.log_var.set(f'连接失败：{port}')
                self._set_connected(False)
                return
            self.log_var.set(f'已连接：{port}')
            self._set_connected(True)

            # 启动后台读取线程
            self.stop_reader.clear()
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()
        except Exception as e:
            self.log_var.set(f'连接错误：{e}')
            self._set_connected(False)

    def disconnect(self):
        try:
            self.stop_reader.set()
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=1.0)
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
            self.client = None
        finally:
            self._set_connected(False)
            self.log_var.set('已断开')

    def _reader_loop(self):
        while not self.stop_reader.is_set():
            try:
                with self.lock:
                    if self.client:
                        rr = self.client.read_holding_registers(0, 1, slave=SLAVE_ID)
                    else:
                        rr = None
                if rr and not getattr(rr, 'isError', lambda: False)():
                    val = rr.registers[0] if hasattr(rr, 'registers') and rr.registers else None
                else:
                    val = None
                try:
                    # 保证队列只保留最新值
                    while not self.data_q.empty():
                        self.data_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.data_q.put_nowait(val)
                except queue.Full:
                    pass
                # 不再在后台循环中自动读取线圈，线圈读取由 UI 按钮触发
            except Exception:
                # 忽略单次错误，继续轮询
                pass
            time.sleep(0.5)

    def write_coil(self, state: bool):
        """在后台线程写单个线圈（FC05），避免阻塞 GUI。"""
        if not self.client:
            self.log_var.set('未连接')
            return

        # 禁用写按钮避免并发写操作
        try:
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.DISABLED)
        except Exception:
            pass

        def _worker():
            err = None
            res = None
            try:
                with self.lock:
                    res = self.client.write_coil(0, state, slave=SLAVE_ID)
                if res is None:
                    err = 'no response or timeout'
                elif hasattr(res, 'isError') and res.isError():
                    err = f'modbus_error: {repr(res)}'
            except Exception as e:
                err = repr(e)

            def _finish():
                if err is not None:
                    self.log_var.set(f'写入失败: {err}')
                else:
                    self.log_var.set('已发送：启动' if state else '已发送：停止')
                # 恢复按钮状态（如果仍然连接）
                try:
                    self._set_connected(self.client is not None)
                except Exception:
                    try:
                        self.start_btn.config(state=(tk.NORMAL if self.client else tk.DISABLED))
                        self.stop_btn.config(state=(tk.NORMAL if self.client else tk.DISABLED))
                        self.read_btn.config(state=(tk.NORMAL if self.client else tk.DISABLED))
                    except Exception:
                        pass

            try:
                self.root.after(0, _finish)
            except Exception:
                _finish()

        threading.Thread(target=_worker, daemon=True).start()

    def read_coil_once(self):
        """由 UI 按钮触发：在后台线程中发送 FC01 并异步更新显示，避免阻塞 GUI。"""
        if not self.client:
            self.log_var.set('未连接')
            return

        # 禁用按钮避免重复点击
        try:
            self.read_btn.config(state=tk.DISABLED)
        except Exception:
            pass
        self.log_var.set('读取 Coil0...')

        def _worker():
            err = None
            val = None
            rr = None
            try:
                with self.lock:
                    rr = self.client.read_coils(0, 1, slave=SLAVE_ID)
                if rr is None:
                    err = 'timeout or no response'
                elif hasattr(rr, 'isError') and rr.isError():
                    err = f'modbus_error: {repr(rr)}'
                elif hasattr(rr, 'bits'):
                    try:
                        val = bool(rr.bits[0])
                    except Exception:
                        val = None
                else:
                    err = f'unexpected response: {repr(rr)}'
            except Exception as e:
                err = repr(e)

            def _update():
                if err is not None:
                    self.log_var.set(f'读取 Coil0 失败: {err}')
                else:
                    self.coil_var.set(str(int(bool(val))) if val is not None else '-')
                    self.log_var.set('读取 Coil0 成功')
                try:
                    self.read_btn.config(state=(tk.NORMAL if self.client else tk.DISABLED))
                except Exception:
                    pass

            try:
                self.root.after(0, _update)
            except Exception:
                _update()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _poll_ui(self):
        # 读取最新值并更新 UI
        try:
            val = None
            try:
                val = self.data_q.get_nowait()
            except queue.Empty:
                val = None
            if val is not None:
                self.hr_var.set(str(val))
            # Coil 的读取由按钮触发，不在此处自动更新
        except Exception:
            pass
        finally:
            self._after_id = self.root.after(700, self._poll_ui)

    def close(self):
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
        self.disconnect()


def main():
    root = tk.Tk()
    app = MasterApp(root)
    root.protocol('WM_DELETE_WINDOW', lambda: (app.close(), root.destroy()))
    root.mainloop()


if __name__ == '__main__':
    main()
