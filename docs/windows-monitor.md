# Windows 固件与部署

先按根目录 README 建立 Python 环境。电脑须保持运行；服务默认端口 8787。配置、令牌、SQLite 均排除在 Git 之外。

## 固件

从 Arduino 官方发行页安装 Arduino CLI，将 `arduino-cli.exe` 放到 `work/tools/bin/`，然后安装 ESP32 平台：

```powershell
work/tools/bin/arduino-cli.exe core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
work/tools/bin/arduino-cli.exe core install esp32:esp32@3.3.12 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

创建 `work/tools/arduino/arduino-cli.yaml`，内容为：

```yaml
board_manager:
  additional_urls:
    - https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

双击 `configure-wifi.cmd` 输入 2.4 GHz Wi-Fi 和电脑服务地址，USB 连接开发板后运行：

```powershell
./work/rlcd_companion/scripts/firmware_windows.ps1 -Action ports
./work/rlcd_companion/scripts/firmware_windows.ps1 -Action compile
./work/rlcd_companion/scripts/firmware_windows.ps1 -Action upload -Port COM3
```

串口按实际情况修改。脚本使用 ESP32-S3、16 MB Flash、OPI PSRAM、USB CDC。首次升级前自行备份原固件。生成的 `config.h`、二进制和设备备份可能含 Wi-Fi 密码，不能公开。

## 验收

确认 400×300 预览、15,000 字节帧、温湿度回传和静音。实验室两款客户端分别检查开始、等待确认、恢复、完成、取消。断开 ZeroTier 60 秒应显示离线；屏幕失联 30 秒应显示中断。恢复后自动同步。对照官方账户核对额度。

自动测试不能替代真实账户、客户端和硬件验收。不要把服务直接暴露到公网；允许可信局域网/ZeroTier 设备访问 TCP 8787 即可。
