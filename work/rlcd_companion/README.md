# RLCD 桌面小伙伴

这是微雪 ESP32-S3-RLCD-4.2 桌面信息屏的第一版工程。

第一版采用这个架构：

```text
Mac 本地服务负责取数和渲染画面
ESP32 负责联网拉取位图并显示
```

## 先运行 Mac 端预览

```bash
work/rlcd_companion/scripts/run_server.sh
```

浏览器打开：

```text
http://127.0.0.1:8787/preview.png
```

ESP32 后续会拉取：

```text
http://你的Mac局域网IP:8787/frame.bin
```

## 启用真实飞书数据

默认是示例数据，方便先调屏幕。确认飞书 CLI 已登录后，用下面命令启动真实数据模式：

```bash
cd work/rlcd_companion/server
source .venv/bin/activate
RLCD_FEISHU_ENABLED=1 uvicorn app:app --host 0.0.0.0 --port 8787
```

当前实现会：

- 查询今天剩余日程。
- 查询未完成待办数量。
- 查询天气。
- 对飞书和天气做缓存，避免每次刷新屏幕都请求外部接口。

先检查飞书 CLI：

```bash
/opt/homebrew/bin/lark-cli doctor
```

## 更新 AI Coding 状态

```bash
work/rlcd_companion/scripts/rlcd-ai coding 正在生成固件草稿
```

可用状态：

- `idle`：空闲
- `coding`：编程中
- `done`：编程完成
- `needs_confirm`：需要确认
- `interrupted`：中断或失败

常用命令：

```bash
work/rlcd_companion/scripts/rlcd-ai done 固件草稿已生成
work/rlcd_companion/scripts/rlcd-ai needs_confirm 测试失败，需要你确认
work/rlcd_companion/scripts/rlcd-ai interrupted 烧录被中断
work/rlcd_companion/scripts/rlcd-ai ack
work/rlcd_companion/scripts/rlcd-ai state
```

如果服务不在本机，传入 `--server`：

```bash
work/rlcd_companion/scripts/rlcd-ai --server http://192.0.2.10:8787 done 任务已完成
```

## Codex/脚本自动接入

任务生命周期上报：

```bash
work/rlcd_companion/scripts/rlcd-task start 正在处理任务
work/rlcd_companion/scripts/rlcd-task done 任务已完成
work/rlcd_companion/scripts/rlcd-task confirm 需要你确认
work/rlcd_companion/scripts/rlcd-task fail 任务中断，需要处理
```

包裹任意命令，按退出码自动上报：

```bash
work/rlcd_companion/scripts/rlcd-run 跑测试 -- pytest -q
```

`rlcd-run` 会：

- 命令开始前显示 `coding`。
- 命令退出码为 `0` 时显示 `done`。
- 命令退出码非 `0` 时显示 `needs_confirm`，并保留原命令退出码。

## 编译和烧录 ESP32

当前工程已经配置好本地 `arduino-cli`。先写入固件配置：

```bash
work/rlcd_companion/scripts/write_firmware_config.sh
```

它会询问 Wi-Fi 名称、Wi-Fi 密码，并自动读取 Mac 局域网 IP。

注意：ESP32-S3 只支持 2.4GHz Wi-Fi，不能连接名称里常见的 `5G` 频段网络。

如果需要同时支持家里 Wi-Fi 和手机热点：

```bash
WIFI_SSID='家里2.4G Wi-Fi 名称' \
WIFI_PASSWORD='家里 Wi-Fi 密码' \
HOTSPOT_SSID_CONTAINS='PhoneHotspot' \
HOTSPOT_PASSWORD='手机热点密码' \
work/rlcd_companion/scripts/write_firmware_config.sh
```

如果 Mac 和 ESP32 不在同一个网络，例如公司里 Mac 连 5G 办公网、ESP32 连手机热点，需要让 ESP32 请求公网中转地址：

```bash
FRAME_BASE_URL='http://你的服务器IP或域名/rlcd/换成你的长token' \
WIFI_SSID='家里2.4G Wi-Fi 名称' \
WIFI_PASSWORD='家里 Wi-Fi 密码' \
HOTSPOT_SSID_CONTAINS='PhoneHotspot' \
HOTSPOT_PASSWORD='手机热点密码' \
work/rlcd_companion/scripts/write_firmware_config.sh
```

Mac 侧公网中转脚本：

```bash
RLCD_TUNNEL_HOST='你的服务器 IP 或域名' \
RLCD_TUNNEL_USER='服务器用户名' \
work/rlcd_companion/scripts/run_tunnel.sh
```

编译：

```bash
work/rlcd_companion/scripts/compile_firmware.sh
```

烧录：

```bash
work/rlcd_companion/scripts/flash_firmware.sh
```

当前检测到的 ESP32 串口是：

```text
/dev/cu.usbmodem2101
```
