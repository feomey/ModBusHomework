import math
import struct
import threading
import time
import tkinter as tk
from tkinter import ttk
import serial

# 简易 Modbus RTU 从站（仅 01/03/05），不依赖 pymodbus。
# 串口参数 9600 8N1，默认 COM2，从站地址 1。

SERIAL_PORT = 'COM2'
UNIT_ID = 1
BAUDRATE = 9600
BYTESIZE = 8
PARITY = 'N'
STOPBITS = 1
TIMEOUT = 0.05

# 数据存储
COILS = [0] * 16
HOLDING = [0] * 16
LOCK = threading.Lock()


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


def pack_coils(start: int, count: int) -> bytes:
    bits = COILS[start:start + count]
    byte_count = math.ceil(count / 8)
    out = bytearray(byte_count)
    for i, bit in enumerate(bits):
        if bit:
            out[i // 8] |= (1 << (i % 8))
    return bytes(out)


def handle_request(req: bytes) -> bytes | None:
    # req: addr func ... crc
    if len(req) < 8:
        return None
    addr, func = req[0], req[1]
    if addr != UNIT_ID:
        return None
    # CRC check
    if crc16_modbus(req[:-2]) != struct.unpack('<H', req[-2:])[0]:
        return None

    if func == 0x05 and len(req) == 8:
        coil_addr = struct.unpack('>H', req[2:4])[0]
        value = struct.unpack('>H', req[4:6])[0]
        with LOCK:
            if 0 <= coil_addr < len(COILS):
                COILS[coil_addr] = 1 if value == 0xFF00 else 0
        resp = req[:-2]  # echo
        return append_crc(resp)

    if func == 0x01 and len(req) == 8:
        start, qty = struct.unpack('>H H', req[2:6])
        with LOCK:
            if start + qty <= len(COILS):
                data_bytes = pack_coils(start, qty)
        byte_count = len(data_bytes)
        resp = struct.pack('>B B B', UNIT_ID, 0x01, byte_count) + data_bytes
        return append_crc(resp)

    if func == 0x03 and len(req) == 8:
        start, qty = struct.unpack('>H H', req[2:6])
        with LOCK:
            regs = HOLDING[start:start + qty]
        data = b''.join(struct.pack('>H', r & 0xFFFF) for r in regs)
        resp = struct.pack('>B B B', UNIT_ID, 0x03, len(data)) + data
        return append_crc(resp)

    # Unsupported -> exception response
    resp = struct.pack('>B B B', UNIT_ID, func | 0x80, 0x01)
    return append_crc(resp)


def serial_worker(stop_event: threading.Event):
    try:
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUDRATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=TIMEOUT,
        )
    except Exception:
        return

    buffer = bytearray()
    while not stop_event.is_set():
        try:
            chunk = ser.read(64)
            if chunk:
                buffer.extend(chunk)
                # process fixed-length 8-byte requests (01/03/05)
                while len(buffer) >= 8:
                    frame = bytes(buffer[:8])
                    buffer = buffer[8:]
                    resp = handle_request(frame)
                    if resp:
                        ser.write(resp)
        except Exception:
            pass
    try:
        ser.close()
    except Exception:
        pass


class SlaveUI:
    def __init__(self, master, stop_event: threading.Event):
        self.master = master
        self.stop_event = stop_event
        self.master.title('Modbus 从站 (01/03/05)')
        self.master.geometry('430x300')
        self.master.resizable(False, False)

        self._count = 0
        self._last_tick = time.time()

        ttk.Label(master, text=f'串口 {SERIAL_PORT}, 从站 {UNIT_ID}', font=(None, 11, 'bold')).pack(pady=6)
        self.indicator = tk.Label(master, text=' ', width=10, height=4, bg='lightgray', relief=tk.RIDGE)
        self.indicator.pack(pady=6)
        self.state_label = ttk.Label(master, text='状态: 停止')
        self.state_label.pack()
        self.count_label = ttk.Label(master, text='HR0 计数: 0', font=(None, 12))
        self.count_label.pack(pady=4)

        btns = ttk.Frame(master)
        btns.pack(pady=6)
        ttk.Button(btns, text='本地开启 (Coil0=1)', command=lambda: self.set_coil(1)).grid(row=0, column=0, padx=6)
        ttk.Button(btns, text='本地关闭 (Coil0=0)', command=lambda: self.set_coil(0)).grid(row=0, column=1, padx=6)

        self.coils_view = ttk.Label(master, text='线圈[0:8]: []')
        self.hr_view = ttk.Label(master, text='保持寄存器[0:4]: []')
        self.coils_view.pack(pady=2)
        self.hr_view.pack(pady=2)

        self.master.after(150, self.ui_loop)
        self.master.protocol('WM_DELETE_WINDOW', self.on_close)

    def set_coil(self, val: int):
        with LOCK:
            COILS[0] = 1 if val else 0

    def ui_loop(self):
        with LOCK:
            coil0 = COILS[0]
        if coil0:
            self.indicator.config(bg='#07c160')
            self.state_label.config(text='状态: 运行')
            if time.time() - self._last_tick >= 1.0:
                self._count += 1
                self._last_tick = time.time()
                with LOCK:
                    HOLDING[0] = self._count
        else:
            self.indicator.config(bg='lightgray')
            self.state_label.config(text='状态: 停止')

        with LOCK:
            coils_snapshot = COILS[:8]
            hrs_snapshot = HOLDING[:4]
        self.coils_view.config(text=f'线圈[0:8]: {coils_snapshot}')
        self.hr_view.config(text=f'保持寄存器[0:4]: {hrs_snapshot}')
        self.count_label.config(text=f'HR0 计数: {hrs_snapshot[0]}')

        self.master.after(150, self.ui_loop)

    def on_close(self):
        self.stop_event.set()
        self.master.destroy()


def main():
    stop_event = threading.Event()
    worker = threading.Thread(target=serial_worker, args=(stop_event,), daemon=True)
    worker.start()

    root = tk.Tk()
    app = SlaveUI(root, stop_event)
    root.mainloop()


if __name__ == '__main__':
    main()
