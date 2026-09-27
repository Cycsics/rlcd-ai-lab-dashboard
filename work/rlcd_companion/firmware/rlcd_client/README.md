# ESP32 固件说明

这个目录是 ESP32-S3-RLCD-4.2 的 Arduino 固件。

## 使用前必须做的事

1. 确认 Mac 本地服务已经启动：

   ```bash
   cd work/rlcd_companion/server
   source .venv/bin/activate
   uvicorn app:app --host 0.0.0.0 --port 8787
   ```

2. 查看 Mac 局域网 IP：

   ```bash
   ipconfig getifaddr en0
   ```

3. 写入配置文件：

   ```bash
   work/rlcd_companion/scripts/write_firmware_config.sh
   ```

4. 如果要手工编辑，配置内容是：

   ```cpp
   #define WIFI_SSID "你的 Wi-Fi 名称"
   #define WIFI_PASSWORD "你的 Wi-Fi 密码"
   #define FRAME_URL "http://你的Mac局域网IP:8787/frame.bin"
   #define ACK_URL "http://你的Mac局域网IP:8787/ack"
   ```

   注意：ESP32-S3 只支持 2.4GHz Wi-Fi，不能连接 5GHz Wi-Fi。

## 编译和烧录

本工程已经准备好本地 `arduino-cli`：

```bash
work/rlcd_companion/scripts/compile_firmware.sh
work/rlcd_companion/scripts/flash_firmware.sh
```

如果你的串口不是 `/dev/cu.usbmodem2101`，用 `PORT` 指定：

```bash
PORT=/dev/cu.usbmodemXXXX work/rlcd_companion/scripts/flash_firmware.sh
```

## 功能

- 启动后连接 Wi-Fi。
- 每隔几秒请求 Mac 的 `/frame.bin`。
- 每次 HTTP 拉图设置连接和读取超时，并关闭连接复用；连续 3 次拉图失败后会主动断开、重扫并重连 Wi-Fi，避免断网恢复后一直停留在旧画面。
- 把 15000 字节的黑白位图画到屏幕。
- 读取电池电量，并通过 `battery=xx` 传给 Mac。
- 读取板载 SHTC3 温湿度，并通过 `temp=xx&humidity=xx` 传给 Mac。
- 接收 `X-RLCD-Sound-Cue`，通过 ES8311 + 扬声器播放会议和 AI 完成提示音。
- 按 `KEY(GPIO18)` 或 `BOOT(GPIO0)` 时调用 `/ack` 确认提醒；不要用 `RESET` 确认。

## 板载传感器与声音

温湿度：

- 传感器：SHTC3。
- I2C：`SDA GPIO13`、`SCL GPIO14`。
- 固件最多每 10 秒读取一次；读取失败时继续使用上一次成功值。

声音：

- Codec：ES8311。
- I2S：`MCLK GPIO16`、`BCLK GPIO9`、`WS GPIO45`、`DOUT GPIO8`。
- PA：`GPIO46`。
- 声音由固件本地生成，不需要 Mac 传音频文件。
- 当前办公室音量档：ES8311 DAC 音量寄存器 `0xB8`，提示音振幅整体乘 `70%`。如果后续还觉得响，优先继续下调 `cute_audio.cpp` 里的 `AUDIO_CUE_GAIN_PERCENT`。
