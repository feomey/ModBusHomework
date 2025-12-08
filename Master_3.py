"""主站（带 GUI）

提供三个按钮：
- 写单个线圈 (FC05) — 将 slave 的 coil[0] 置为 1
- 读线圈 (FC01) — 读取 coil[0] 并在界面显示 1/0
- 读保持寄存器 (FC03) — 读取 hr[0] 并在界面显示数值

运行前请确保 `Slave_3.py` 在本机运行并监听 `127.0.0.1:5020`。
"""

import tkinter as tk
from tkinter import ttk
from pymodbus.client.sync import ModbusTcpClient
import threading


class MasterGUI:
    def __init__(self, master, host='127.0.0.1', port=5020, unit=1):
        self.master = master
        self.host = host
        self.port = port
        self.unit = unit

        self.master.title('Modbus 主站')
        self.master.geometry('480x320')
        self.master.resizable(False, False)

        header = ttk.Label(master, text='Modbus 主站', font=(None, 14, 'bold'))
        header.pack(pady=8)

        status_frame = ttk.Frame(master)
        status_frame.pack(pady=4)
        self.conn_label = ttk.Label(status_frame, text='未连接', foreground='red')
        self.conn_label.pack()

        btns = ttk.Frame(master)
        btns.pack(pady=8)

        ttk.Button(btns, text='写单个线圈 (写1)', command=self.write_coil).grid(row=0, column=0, padx=6)
        ttk.Button(btns, text='写单个线圈 (写0)', command=self.write_coil_zero).grid(row=0, column=1, padx=6)
        ttk.Button(btns, text='读线圈', command=self.read_coil).grid(row=0, column=2, padx=6)
        ttk.Button(btns, text='读保持寄存器', command=self.read_register).grid(row=0, column=3, padx=6)

        out_frame = ttk.Frame(master)
        out_frame.pack(pady=10)

        self.coil_label = ttk.Label(out_frame, text='Coil[0]: N/A', font=(None, 12))
        self.coil_label.pack(pady=4)
        self.reg_label = ttk.Label(out_frame, text='HR[0]: N/A', font=(None, 12))
        self.reg_label.pack(pady=4)

        # 建立 Modbus 连接（后台线程以避免阻塞 UI）
        self.client = ModbusTcpClient(self.host, port=self.port)
        self._connect_in_background()

    def _connect_in_background(self):
        def _c():
            ok = self.client.connect()
            self.master.after(0, lambda: self._update_conn_label(ok))

        threading.Thread(target=_c, daemon=True).start()

    def _update_conn_label(self, ok: bool):
        if ok:
            self.conn_label.config(text=f'已连接 {self.host}:{self.port}', foreground='green')
        else:
            self.conn_label.config(text='连接失败', foreground='red')

    def write_coil(self):
        try:
            r = self.client.write_coil(0, True, unit=self.unit)
            if r.isError():
                self.coil_label.config(text='写入 Coil[0] = 1：失败')
            else:
                
                self.coil_label.config(text='写入 Coil[0] = 1：成功')
        except Exception as e:
            self.coil_label.config(text='写入 Coil[0] = 1：错误')

    def write_coil_zero(self):
        try:
            r = self.client.write_coil(0, False, unit=self.unit)
            if r.isError():
                self.coil_label.config(text='写入 Coil[0] = 0：失败')
            else:
                
                self.coil_label.config(text='写入 Coil[0] = 0：成功')
        except Exception:
            self.coil_label.config(text='写入 Coil[0] = 0：错误')

    def read_coil(self):
        try:
            r = self.client.read_coils(0, 1, unit=self.unit)
            if r.isError():
                self.coil_label.config(text='Coil[0]: 读失败')
            else:
                val = 1 if r.bits[0] else 0
                self.coil_label.config(text=f'Coil[0]: {val}')
        except Exception:
            self.coil_label.config(text='Coil[0]: 错误')

    def read_register(self):
        try:
            r = self.client.read_holding_registers(0, 1, unit=self.unit)
            if r.isError():
                self.reg_label.config(text='HR[0]: 读失败')
            else:
                self.reg_label.config(text=f'HR[0]: {r.registers[0]}')
        except Exception:
            self.reg_label.config(text='HR[0]: 错误')


def main():
    root = tk.Tk()
    app = MasterGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
