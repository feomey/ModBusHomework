import threading
import time
import tkinter as tk
from pymodbus.server.sync import StartSerialServer
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext

PORT = 'COM2'
SLAVE_ID = 1

# 定义全局的数据存储区
# Co: 0=灯的状态, Holding Registers: 0=运行次数
store = ModbusSlaveContext(
    co=ModbusSequentialDataBlock(0, [0] * 10),
    hr=ModbusSequentialDataBlock(0, [0] * 10),
    zero_mode=True
)
context = ModbusServerContext(slaves=store, single=True)


class SlaveApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"从站设备 (ID: {SLAVE_ID})")
        self.root.geometry("320x240")

        
        tk.Label(root, text="现场设备模拟器", font=("宋体", 12, "bold")).pack(pady=10)

        
        self.canvas = tk.Canvas(root, width=80, height=80)
        self.canvas.pack()
        
        self.light = self.canvas.create_oval(10, 10, 70, 70, fill="gray", outline="black", width=2)

        self.lbl_status = tk.Label(root, text="设备状态: 停止", font=("宋体", 10), fg="gray")
        self.lbl_status.pack(pady=5)

        self.lbl_count = tk.Label(root, text="当前运行次数: 0", font=("宋体", 14))
        self.lbl_count.pack(pady=10)

        
        self.run_count = 0
        self.last_time = time.time()

        
        self.update_loop()

    def update_loop(self):
        """主线程定时任务：检查 Modbus 数据并更新界面"""

        # 获取当前的线圈状态 (Coil 0)
        slave_store = context[SLAVE_ID]
        is_running = slave_store.getValues(1, 0, count=1)[0]  # 1=Coils, 0=Address

        # --- 更新界面显示 ---
        if is_running:
            self.canvas.itemconfig(self.light, fill="#00FF00")  # 绿灯
            self.lbl_status.config(text="设备状态: 运行中", fg="green")

            # --- 模拟业务逻辑：如果运行中，每秒计数+1 ---
            if time.time() - self.last_time >= 1.0:
                self.run_count += 1
                self.last_time = time.time()
                # 将新计数写入保持寄存器 (Holding Register 0)
                slave_store.setValues(3, 0, [self.run_count])  # 3=Holding Reg

        else:
            self.canvas.itemconfig(self.light, fill="gray")  # 灭灯
            self.lbl_status.config(text="设备状态: 已停止", fg="gray")

        # 更新计数显示
        self.lbl_count.config(text=f"当前运行次数: {self.run_count}")

        # 100ms 后再次刷新
        self.root.after(100, self.update_loop)


def start_modbus_server():
    """在后台线程启动 Modbus 服务器"""
    StartSerialServer(
        context=context,
        port=PORT,
        baudrate=9600,
        bytesize=8,
        parity='N',
        stopbits=1
    )


if __name__ == "__main__":
    t = threading.Thread(target=start_modbus_server, daemon=True)
    t.start()

    root = tk.Tk()
    app = SlaveApp(root)
    root.mainloop()