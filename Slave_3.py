"""从站（带 GUI）

说明：
- 使用 `pymodbus` 提供 Modbus TCP 服务（监听本机 5020 端口）
- 提供一个简单 Tkinter GUI，显示指示灯和计数
- 当 coil[0] 为 1 时，从站每秒将保持寄存器 hr[0] 加 1

运行：
 1. 安装依赖：`pip install pymodbus`
 2. 运行本文件：`python Slave_3.py`
"""

from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.device import ModbusDeviceIdentification
import logging
import threading
import tkinter as tk
from tkinter import ttk
import time

logging.basicConfig()
log = logging.getLogger()
log.setLevel(logging.INFO)

UNIT_ID = 1

# 全局共享上下文，GUI 与服务器线程共享
_slave_storage = ModbusSlaveContext(
    co=ModbusSequentialDataBlock(0, [0] * 1),  # 仅需要 1 个线圈
    hr=ModbusSequentialDataBlock(0, [0] * 1),  # 仅需要 1 个保持寄存器
    zero_mode=True,
)
_server_context = ModbusServerContext(slaves=_slave_storage, single=True)


def run_server(host='0.0.0.0', port=5020):
    identity = ModbusDeviceIdentification()
    identity.VendorName = 'Example'
    identity.ProductCode = 'MB'
    identity.VendorUrl = 'http://example.local'
    identity.ProductName = 'Modbus Slave 3'
    identity.ModelName = 'ModbusSlave3'
    identity.MajorMinorRevision = '1.0'

    log.info(f"Starting Modbus TCP server on {host}:{port} (unit {UNIT_ID})")
    StartTcpServer(context=_server_context, identity=identity, address=(host, port))


class DeviceSimulator:
    """带 GUI 的设备模拟器：
    - 根据 `coil[0]` 控制运行/停止指示
    - 在运行时每秒将计数写入保持寄存器 0
    """

    def __init__(self, master):
        self.master = master
        self.master.title(f"模拟从站 (Unit {UNIT_ID})")
        self.master.geometry('320x240')
        self.master.resizable(False, False)

        header = ttk.Label(self.master, text='设备模拟器', font=(None, 14, 'bold'))
        header.pack(pady=8)

        self.indicator = tk.Label(self.master, text=' ', width=8, height=4, bg='lightgray', relief=tk.RIDGE)
        self.indicator.pack(pady=6)

        self.state_label = ttk.Label(self.master, text='状态: 停止')
        self.state_label.pack(pady=4)

        self.counter_label = ttk.Label(self.master, text='计数: 0', font=(None, 14))
        self.counter_label.pack(pady=8)

        btns = ttk.Frame(self.master)
        btns.pack(pady=6)
        ttk.Button(btns, text='启动(本地)', command=lambda: self._set_coil_local(1)).grid(row=0, column=0, padx=6)
        ttk.Button(btns, text='停止(本地)', command=lambda: self._set_coil_local(0)).grid(row=0, column=1, padx=6)

        self._count = 0
        self._last_tick = time.time()

        self._ui_loop()

    def _set_coil_local(self, val: int):
        ds = _server_context[UNIT_ID]
        ds.setValues(1, 0, [val])

    def _ui_loop(self):
        ds = _server_context[UNIT_ID]
        try:
            coil_val = ds.getValues(1, 0, count=1)[0]
        except Exception:
            coil_val = 0

        if coil_val:
            self.indicator.config(bg='#07c160')
            self.state_label.config(text='状态: 运行中')
            if time.time() - self._last_tick >= 1.0:
                self._count += 1
                self._last_tick = time.time()
                try:
                    ds.setValues(3, 0, [self._count])
                except Exception:
                    pass
        else:
            self.indicator.config(bg='lightgray')
            self.state_label.config(text='状态: 已停止')

        self.counter_label.config(text=f'计数: {self._count}')
        self.master.after(200, self._ui_loop)


def main():
    # 启动后台 Modbus 服务
    th = threading.Thread(target=run_server, daemon=True)
    th.start()

    root = tk.Tk()
    sim = DeviceSimulator(root)
    root.mainloop()


if __name__ == '__main__':
    main()
