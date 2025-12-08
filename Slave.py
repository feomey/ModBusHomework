import threading
import time
import tkinter as tk
from tkinter import ttk
from pymodbus.server.sync import StartSerialServer
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext

# 从站 (Slave) 模块说明
"""
Slave.py

这个模块提供一个简单的模拟从站：
- 在后台启动一个 `pymodbus` 的串口服务器 `StartSerialServer`，将 Modbus 存储区暴露到串口上。
- 通过 `DeviceSimulator` 提供一个本地 GUI：显示运行/停止状态、运行计数，并在 Coil 0 为 True 时每秒增加计数并写入保持寄存器 0。

设计要点：
- `context`：ModbusServerContext，包含 `ModbusSlaveContext`（coils 和 holding registers）。
- `_start_server()`：在独立线程中调用 `StartSerialServer(...)`，避免阻塞主 GUI 线程。
- `DeviceSimulator._tick()`：在主线程以 ~120ms 间隔读取 datastore 的 Coil 值并更新 UI，保证 GUI 与 Modbus 存储区同步。
"""

PORT = 'COM2'
SLAVE_ID = 1

# 新的存储区定义，功能等同于原来
store = ModbusSlaveContext(
    co=ModbusSequentialDataBlock(0, [0] * 10),
    hr=ModbusSequentialDataBlock(0, [0] * 10),
    zero_mode=True,
)
context = ModbusServerContext(slaves=store, single=True)


class DeviceSimulator:
    """
    简单的从站设备模拟器（GUI）：

    - 读取 context 中的 Coil(1) 地址 0 作为“运行/停止”标志。
    - 如果运行标志为 True，每秒将内部计数加1并写回保持寄存器 0（供 Master 读取）。
    - UI 使用 Canvas 作为指示器、一个大号计数显示和一个重置按钮。
    """

    def __init__(self, root):
        self.root = root
        self.root.title(f"模拟从站 — ID {SLAVE_ID}")
        self.root.geometry("380x260")
        self.root.resizable(False, False)

        container = ttk.Frame(root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Label(container, text="现场设备模拟器", font=("Segoe UI", 13, "bold"))
        header.pack(pady=(0, 8))

        body = ttk.Frame(container)
        body.pack(fill=tk.X)

        # 状态显示使用 Canvas
        self.indicator = tk.Canvas(body, width=100, height=100, highlightthickness=0)
        self.indicator.grid(row=0, column=0, rowspan=3, padx=(0, 12))
        self._oval = self.indicator.create_oval(8, 8, 92, 92, fill="#666666", outline="#222222", width=3)

        self.status_label = ttk.Label(body, text="状态: 停止", font=("Arial", 11))
        self.status_label.grid(row=0, column=1, sticky=tk.W)

        self.count_var = tk.StringVar(value="运行次数：0")
        self.count_label = ttk.Label(body, textvariable=self.count_var, font=("Courier New", 18), foreground="#004D40")
        self.count_label.grid(row=1, column=1, sticky=tk.W, pady=(6, 0))

        # 控制按钮
        ctrl = ttk.Frame(container)
        ctrl.pack(pady=(12, 0))
        ttk.Button(ctrl, text="重置计数", command=self._reset_count).grid(row=0, column=0, padx=6)

        # 内部计数与时间记录
        self._run_count = 0
        self._last = time.time()

        # 启动定时更新（主线程）
        self._tick()

    def _reset_count(self):
        """本地按钮：重置计数（不会改变 Coil）"""
        self._run_count = 0

    def _tick(self):
        """周期性从 `context` 读取 Coil(1) 的地址 0 并更新 UI / 写回保持寄存器。

        - 以 120ms 间隔轮询 datastore（足够响应 UI 控制），
        - 若 Coil 为 True，则每满 1 秒增加一次运行计数并写入保持寄存器 0。
        """
        store_ref = context[SLAVE_ID]
        # 读取 Coil 0
        run_flag = store_ref.getValues(1, 0, count=1)[0]

        if run_flag:
            # 运行中样式
            self.indicator.itemconfig(self._oval, fill="#00C853")
            self.status_label.config(text="状态: 运行中", foreground="#00A152")
            # 每秒计数
            if time.time() - self._last >= 1.0:
                self._run_count += 1
                self._last = time.time()
                # 写回保持寄存器 0
                store_ref.setValues(3, 0, [self._run_count])
        else:
            self.indicator.itemconfig(self._oval, fill="#8E8E8E")
            self.status_label.config(text="状态: 已停止", foreground="#666666")

        self.count_var.set(f"运行次数：{self._run_count}")
        self.root.after(120, self._tick)


def _start_server():
    """在后台线程中直接调用 `StartSerialServer` 启动 Modbus 串口服务器。

    该函数会阻塞调用线程（因此我们在守护线程里运行它），
    使得主线程可以继续运行 tkinter GUI。
    """
    StartSerialServer(context=context, port=PORT, baudrate=9600, bytesize=8, parity='N', stopbits=1)


if __name__ == '__main__':
    # 启动 Modbus 服务在背景线程
    t = threading.Thread(target=_start_server, daemon=True)
    t.start()

    root = tk.Tk()
    app = DeviceSimulator(root)
    root.mainloop()