import struct
import threading
import time
import tkinter as tk
from tkinter import ttk
import serial


# 串口参数按 9600 8N1，默认 COM1，从站地址 1。

DEFAULT_PORT = 'COM1'
DEFAULT_SLAVE_ID = 1
BAUDRATE = 9600
BYTESIZE = 8
PARITY = 'N'
STOPBITS = 1
TIMEOUT = 1


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            lsb = crc & 0x0001
            crc >>= 1
            if lsb:
                crc ^= 0xA001
    return crc & 0xFFFF


def append_crc(frame: bytes) -> bytes:
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)


class ModbusMaster:
    def __init__(self, port: str, slave_id: int):
        self.port = port
        self.slave_id = slave_id
        self.ser = None
        self.lock = threading.Lock()

    def connect(self) -> bool:
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=BAUDRATE,
                bytesize=BYTESIZE,
                parity=PARITY,
                stopbits=STOPBITS,
                timeout=TIMEOUT,
            )
            return True
        except Exception:
            self.ser = None
            return False

    def close(self):
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass

    def _transact(self, frame_wo_crc: bytes, expected_min_len: int = 5) -> bytes | None:
        if not self.ser:
            return None
        packet = append_crc(frame_wo_crc)
        with self.lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write(packet)
                self.ser.flush()
                time.sleep(0.05)
                resp = self.ser.read(256)
            except Exception:
                return None
        if len(resp) < expected_min_len:
            return None
        # CRC check
        body, recv_crc = resp[:-2], resp[-2:]
        if crc16_modbus(body) != struct.unpack('<H', recv_crc)[0]:
            return None
        return resp

    def write_coil(self, address: int, value: bool) -> bool:
        val_word = 0xFF00 if value else 0x0000
        frame = struct.pack('>B B H H', self.slave_id, 0x05, address, val_word)
        resp = self._transact(frame, expected_min_len=8)
        return bool(resp)

    def read_coils(self, address: int, count: int) -> list[int] | None:
        frame = struct.pack('>B B H H', self.slave_id, 0x01, address, count)
        resp = self._transact(frame, expected_min_len=5)
        if not resp:
            return None
        # resp: addr, func, bytecount, data..., crc
        if resp[1] & 0x80:
            return None
        byte_count = resp[2]
        data_bytes = resp[3:3 + byte_count]
        bits = []
        for b in data_bytes:
            for i in range(8):
                bits.append((b >> i) & 0x01)
                if len(bits) >= count:
                    return bits
        return bits

    def read_holding(self, address: int, count: int) -> list[int] | None:
        frame = struct.pack('>B B H H', self.slave_id, 0x03, address, count)
        resp = self._transact(frame, expected_min_len=5)
        if not resp:
            return None
        if resp[1] & 0x80:
            return None
        byte_count = resp[2]
        data_bytes = resp[3:3 + byte_count]
        regs = []
        for i in range(0, len(data_bytes), 2):
            if i + 1 < len(data_bytes):
                regs.append(struct.unpack('>H', data_bytes[i:i + 2])[0])
        if len(regs) < count:
            return None
        return regs


class MasterUI:
    def __init__(self, master):
        self.master = master
        self.master.title('Modbus 主站 (01/03/05)')
        self.master.geometry('520x320')
        self.master.resizable(False, False)

        self.mb = None
        self.connected = False

        conn = ttk.LabelFrame(master, text='连接')
        conn.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(conn, text='串口').grid(row=0, column=0, padx=4, pady=4)
        self.port_var = tk.StringVar(value=DEFAULT_PORT)
        ttk.Entry(conn, textvariable=self.port_var, width=10).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(conn, text='从站ID').grid(row=0, column=2, padx=4, pady=4)
        self.slave_var = tk.IntVar(value=DEFAULT_SLAVE_ID)
        ttk.Entry(conn, textvariable=self.slave_var, width=5).grid(row=0, column=3, padx=4, pady=4)
        ttk.Button(conn, text='连接', command=self.connect).grid(row=0, column=4, padx=6, pady=4)
        self.status = ttk.Label(conn, text='未连接', foreground='red')
        self.status.grid(row=0, column=5, padx=6, pady=4)

        act = ttk.LabelFrame(master, text='操作')
        act.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(act, text='写线圈0=1 (05)', command=lambda: self.do_write(True)).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(act, text='写线圈0=0 (05)', command=lambda: self.do_write(False)).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(act, text='读线圈(01)', command=self.do_read_coils).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(act, text='读HR0(03)', command=self.do_read_hr).grid(row=0, column=3, padx=6, pady=6)

        self.coil_label = ttk.Label(act, text='线圈: []')
        self.hr_label = ttk.Label(act, text='HR0: -')
        self.coil_label.grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
        self.hr_label.grid(row=1, column=2, columnspan=2, sticky=tk.W, padx=6, pady=4)

        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(master, text='每秒自动读取 HR0', variable=self.auto_var, command=self.toggle_auto).pack(anchor=tk.W, padx=12)

        self.master.protocol('WM_DELETE_WINDOW', self.on_close)

    def connect(self):
        mb = ModbusMaster(self.port_var.get().strip(), self.slave_var.get())
        self.connected = mb.connect()
        self.mb = mb if self.connected else None
        self.status.config(text='已连接' if self.connected else '未连接', foreground='green' if self.connected else 'red')

    def do_write(self, val: bool):
        if not self.mb:
            self.status.config(text='未连接', foreground='red')
            return
        ok = self.mb.write_coil(0, val)
        self.status.config(text='写成功' if ok else '写失败', foreground='green' if ok else 'red')

    def do_read_coils(self):
        if not self.mb:
            return
        bits = self.mb.read_coils(0, 8)
        self.coil_label.config(text=f'线圈: {bits}' if bits is not None else '线圈: 读取失败')

    def do_read_hr(self):
        if not self.mb:
            return
        regs = self.mb.read_holding(0, 1)
        if regs is None:
            self.hr_label.config(text='HR0: 读取失败')
        else:
            self.hr_label.config(text=f'HR0: {regs[0]}')

    def toggle_auto(self):
        if self.auto_var.get():
            self.master.after(1000, self._auto_poll)

    def _auto_poll(self):
        if self.auto_var.get():
            self.do_read_hr()
            self.master.after(1000, self._auto_poll)

    def on_close(self):
        try:
            if self.mb:
                self.mb.close()
        except Exception:
            pass
        self.master.destroy()


def main():
    root = tk.Tk()
    app = MasterUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
