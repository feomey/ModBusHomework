import tkinter as tk
from tkinter import ttk
from pymodbus.client.sync import ModbusSerialClient

# 保持默认端口与从站ID不变，便于与现有 Slave.py 协同工作
DEFAULT_PORT = 'COM1'
DEFAULT_SLAVE = 1


class ControlPanel:

    def __init__(self, master, port: str = DEFAULT_PORT, slave_id: int = DEFAULT_SLAVE):
        self.master = master
        self.port = port
        self.slave_id = slave_id

        self.master.title("主站 - 控制与监视")
        self.master.geometry("380x240")
        self.master.resizable(False, False)

        # 建立 Modbus 客户端连接
        self.client_mod = ModbusSerialClient(port=self.port, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=1)
        try:
            self.is_connected = self.client_mod.connect()
        except Exception:
            self.is_connected = False

        # 左侧为控制区，右侧为显示区
        main = ttk.Frame(self.master, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        control_frame = ttk.LabelFrame(main, text="控制区")
        control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        status_frame = ttk.LabelFrame(main, text="状态区")
        status_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 控制按钮
        self.start_btn = ttk.Button(control_frame, text="启动", width=12, command=lambda: self._write_coil(True))
        self.start_btn.pack(pady=(10, 6))
        self.stop_btn = ttk.Button(control_frame, text="停止", width=12, command=lambda: self._write_coil(False))
        self.stop_btn.pack(pady=6)
        self.poll_btn = ttk.Button(control_frame, text="手动读取", width=12, command=self._read_register_once)
        self.poll_btn.pack(pady=6)

        # 状态信息显示
        self.port_label = ttk.Label(status_frame, text=f"串口: {self.port}")
        self.port_label.pack(anchor=tk.W, pady=(10, 2), padx=6)
        conn_text = "已连接" if self.is_connected else "未连接"
        conn_color = "green" if self.is_connected else "red"
        self.conn_label = ttk.Label(status_frame, text=conn_text, foreground=conn_color)
        self.conn_label.pack(anchor=tk.W, padx=6)

        self.count_label = ttk.Label(status_frame, text="运行次数: 0", font=("Arial", 16), foreground="blue")
        self.count_label.pack(pady=18)

        # 关闭事件
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

        # 周期任务：每秒查询一次保持寄存器并刷新显示
        self._schedule_poll()

    def _write_coil(self, value: bool):
        """向 Coil 0 写入 True/False（启动/停止）。"""
        if not self.is_connected:
            print("未连接 Modbus：写入被跳过")
            return
        try:
            self.client_mod.write_coil(0, value, slave=self.slave_id)
        except Exception as ex:
            print("写入 Coil 失败：", ex)

    def _read_register_once(self):
        """立即读取保持寄存器 0 并更新界面（手动触发）。"""
        if not self.is_connected:
            return
        try:
            reply = self.client_mod.read_holding_registers(0, 1, slave=self.slave_id)
            if reply and not reply.isError():
                self.count_label.config(text=f"运行次数: {reply.registers[0]}")
        except Exception as ex:
            print("读取寄存器错误：", ex)

    def _poll_once(self):
        """周期性读取（内部使用）。"""
        if self.is_connected:
            try:
                r = self.client_mod.read_holding_registers(0, 1, slave=self.slave_id)
                if r and not r.isError():
                    self.count_label.config(text=f"运行次数: {r.registers[0]}")
            except Exception:
                # 忽略瞬时异常
                pass

    def _schedule_poll(self):
        self._poll_once()
        self.master.after(1000, self._schedule_poll)

    def _on_close(self):
        try:
            if self.client_mod:
                self.client_mod.close()
        except Exception:
            pass
        self.master.destroy()


def main():
    root = tk.Tk()
    app = ControlPanel(root)
    root.mainloop()


if __name__ == '__main__':
    main()