"""Local-only Wi-Fi configuration dialog; never prints credentials."""
import json
from pathlib import Path
import socket
import tkinter as tk
from tkinter import messagebox
from urllib.parse import urlparse

root = tk.Tk()
root.title('RLCD 本机 Wi-Fi 配置')
root.geometry('550x300')
root.attributes('-topmost', True)
tk.Label(root, text='填写开发板使用的 2.4GHz Wi-Fi；电脑应处于同一局域网。').pack(pady=12)
fields = []
for label, secret in [('Wi-Fi 名称', False), ('Wi-Fi 密码', True), ('电脑服务地址', False)]:
    row = tk.Frame(root)
    row.pack(fill='x', padx=20, pady=8)
    tk.Label(row, text=label, width=14, anchor='w').pack(side='left')
    entry = tk.Entry(row, show='*' if secret else '', width=43)
    entry.pack(side='left')
    fields.append(entry)
try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(('192.0.2.1', 80))
        ip = sock.getsockname()[0]
except OSError:
    ip = '192.0.2.10'
fields[2].insert(0, f'http://{ip}:8787')
tk.Label(root, text='密码仅保存到本机 config.h，不会发送到聊天。').pack(pady=8)

def save():
    ssid, password, base = [entry.get() for entry in fields]
    base = base.strip().rstrip('/')
    parsed = urlparse(base)
    if not ssid or parsed.scheme != 'http' or not parsed.hostname:
        messagebox.showerror('请检查', '请填写 Wi-Fi 名称及 http://电脑IP:8787 服务地址。')
        return
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    content = '#pragma once\n'
    content += f'#define WIFI_SSID {quote(ssid)}\n#define WIFI_PASSWORD {quote(password)}\n'
    content += 'static const WifiNetworkConfig WIFI_NETWORKS[] = {{WIFI_SSID, WIFI_PASSWORD, false}};\n'
    content += '#define WIFI_NETWORK_COUNT (sizeof(WIFI_NETWORKS) / sizeof(WIFI_NETWORKS[0]))\n'
    content += f'#define FRAME_URL {quote(base + "/frame.bin")}\n#define ACK_URL {quote(base + "/ack")}\n'
    content += '#define FRAME_REFRESH_MS 3000\n#define PET_ANIMATION_MS 700\n'
    target = Path(__file__).resolve().parents[1] / 'firmware/rlcd_client/config.h'
    target.write_text(content, encoding='utf-8')
    messagebox.showinfo('已保存', '配置已写入本机，可以继续编译烧录。')
    root.destroy()

tk.Button(root, text='保存配置', command=save, width=18).pack(pady=8)
root.mainloop()
