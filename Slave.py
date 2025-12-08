import threading
import time
import tkinter as tk
from tkinter import ttk
from pymodbus.server.sync import StartSerialServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext


# 保持端口和从站 ID 不变以兼容现有 Master
SERIAL_PORT = 'COM2'
UNIT_ID = 1


# 共享的数据区：Coils 用于开关，Holding Registers 用于数值计数
_slave_storage = ModbusSlaveContext(
    co=ModbusSequentialDataBlock(0, [0] * 10),
    hr=ModbusSequentialDataBlock(0, [0] * 10),
    zero_mode=True,
)
_server_context = ModbusServerContext(slaves=_slave_storage, single=True)


class DeviceSimulator:
    """设备模拟器窗口，展示指示灯并驱动本地计数写回到保持寄存器。

    实现等价于原本的 SlaveApp，但使用不同命名与布局。
    """

    def __init__(self, master):
        self.master = master
        self.master.title(f"模拟从站 (Unit {UNIT_ID})")
        self.master.geometry('360x260')
        self.master.resizable(False, False)

        header = ttk.Label(self.master, text='设备模拟器', font=(None, 14, 'bold'))
        header.pack(pady=8)

        # 使用 Label 做彩色指示（背景色变化）
        self.indicator = tk.Label(self.master, text=' ', width=8, height=4, bg='lightgray', relief=tk.RIDGE)
        self.indicator.pack(pady=6)

        self.state_label = ttk.Label(self.master, text='状态: 停止')
        self.state_label.pack(pady=4)

        self.counter_label = ttk.Label(self.master, text='计数: 0', font=(None, 14))
        self.counter_label.pack(pady=8)

        # 调试按钮：在 GUI 中直接修改 datastore 的 Coil 值
        btns = ttk.Frame(self.master)
        btns.pack(pady=6)
        ttk.Button(btns, text='启动(本地)', command=lambda: self._set_coil_local(1)).grid(row=0, column=0, padx=6)
        ttk.Button(btns, text='停止(本地)', command=lambda: self._set_coil_local(0)).grid(row=0, column=1, padx=6)

        # 内部计数与时间追踪
        self._count = 0
        self._last_tick = time.time()

        # 启动 UI 更新循环
        self._ui_loop()

    def _set_coil_local(self, val: int):
        """直接在本地 datastore 中设置 Coil（用于调试/模拟主站写入）。"""
        ds = _server_context[UNIT_ID]
        ds.setValues(1, 0, [val])

    def _ui_loop(self):
        """定期从共享上下文读取 Coil，更新指示和计数。"""
        ds = _server_context[UNIT_ID]
        try:
            coil_val = ds.getValues(1, 0, count=1)[0]
        except Exception:
            coil_val = 0

        if coil_val:
            # 设备运行中
            self.indicator.config(bg='#07c160')
            self.state_label.config(text='状态: 运行中')
            # 每秒计数并写入 HR0
            if time.time() - self._last_tick >= 1.0:
                self._count += 1
                self._last_tick = time.time()
                try:
                    ds.setValues(3, 0, [self._count])
                except Exception:
                    pass
        else:
            # 停止
            self.indicator.config(bg='lightgray')
            self.state_label.config(text='状态: 已停止')

        self.counter_label.config(text=f'计数: {self._count}')

        # 继续循环（短周期保证界面流畅）
        self.master.after(120, self._ui_loop)


def _start_server():
    """在后台线程启动串口 Modbus 服务器（共享 _server_context）。"""
    StartSerialServer(context=_server_context, port=SERIAL_PORT, baudrate=9600, bytesize=8, parity='N', stopbits=1)


def main():
    # 启动后台 Modbus 服务
    th = threading.Thread(target=_start_server, daemon=True)
    th.start()

    root = tk.Tk()
    sim = DeviceSimulator(root)
    root.mainloop()


if __name__ == '__main__':
    main()