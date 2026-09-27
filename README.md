# RLCD AI Lab Dashboard

**把本机 AI 额度和任务进度，放到桌面上的一块小屏幕。**

面向 Waveshare ESP32-S3-RLCD-4.2 的 400 × 300 黑白看板，支持 Codex、GLM Coding Plan 和 Qoder。默认监控运行服务的这台 Windows 电脑，也可添加局域网或外网设备。

![虚拟额度、虚拟任务与 Codex 宠物](docs/monitor-demo.png)

> 图片中的金额、额度、日期、环境读数和任务均为演示数据，不对应真实账户或设备。截图展示当前部署的 Codex 宠物外观；仓库不附带官方宠物素材文件。

## 一屏看清

| 区域 | 内容 |
| --- | --- |
| Codex | 5h 与长周期剩余额度、重置日期；适用时显示 ∞ |
| GLM | Coding Plan 额度、进度条、高峰/非高峰提示 |
| Qoder | 套餐与附加包的 **剩余 / 总额**、套餐到期日、夜惠提示 |
| 订阅 | 金额、币种，以及按月/年自动滚动的预计续费日期 |
| 本机任务 | 执行、等待确认/输入、本轮完成、中断及离线状态 |
| 可选设备 | 接入局域网或外网电脑，与本机一起显示 |
| 环境 | 时间、可选天气、板载温湿度和电量 |

固定单屏、静音，无弹窗遮挡。屏幕约 3 秒取图，网页任务每 30 秒核对，额度每 5 分钟采集；超过 15 分钟未更新会显示过期状态。

## 工作方式

```text
本机 Codex / Qoder 任务 + 账户额度 → 看板服务 → ESP32-S3 屏幕
                                      ↑
可选：其他 Windows → 局域网 / 私有网络 / HTTPS
```

本机采集随看板服务启动，无需额外下载代理或配置网络地址。本机额度仅采集一次，任务标记为“本机”。可选远程采集程序只上报状态元数据，支持持久化、去重与断网重传；15 秒心跳，60 秒无心跳标记离线。完整任务列表在网页查看。

## Windows 快速开始

需要 Python 3.11+。在仓库根目录运行：

```powershell
py -3 -m venv work/rlcd_companion/server/.venv
work/rlcd_companion/server/.venv/Scripts/python.exe -m pip install -r work/rlcd_companion/server/requirements.txt
Copy-Item work/rlcd_companion/server/config.example.yaml work/rlcd_companion/server/config.yaml
```

使用 Qoder 时额外安装：

```powershell
work/rlcd_companion/server/.venv/Scripts/python.exe -m pip install -r work/rlcd_companion/server/requirements-qoder.txt
```

双击 **start-dashboard.cmd**，打开 <http://127.0.0.1:8787/>。

服务会自动准备本机任务采集与 Hooks。首次启动后，在 Codex 客户端审核并信任 Hooks，重启 Qoder；不绕过客户端信任设置。无需安装远程采集包。

- **Codex**：先在本机官方客户端登录，采集程序只读账户额度。
- **GLM**：在配置页输入个人 Coding Plan Key。
- **Qoder**：选择令牌所属的 qoder.cn 或 qoder.com，再填入 Personal Access Token，两站令牌不能混用。
- **订阅**：填写金额和一次续费基准日期，默认按月/年自动滚动下一期；也可关闭自动滚动，手动维护。
- **天气**：公开配置不包含实际坐标。需要时仅在本机 `config.yaml` 填写。

停止和诊断分别使用 **stop-dashboard.cmd**、**diagnose-dashboard.cmd**。开发板烧录与连接见 [Windows 部署说明](docs/windows-monitor.md)。

## 电脑 USB 断连后息屏

在网页“屏幕息屏设置”中选择自动息屏开关和等待时间，默认 **5 分钟**，设为 **0** 可在断连确认后立即息屏；关闭开关可保持常亮。需要刷入支持此功能的固件，网页会显示固件上报状态。

- 通过电脑 USB 的 SOF 信号判断连接，不依赖是否打开串口；电脑休眠也可能触发，不能用来判断独立充电器是否通电。
- 断连持续 3 秒才开始计时；启动时保留至少 10 秒缓冲，防止枚举过程误触发。
- 息屏时关闭显示、Wi-Fi 和功放，CPU 降至 80 MHz，保留 USB 检测。它不是物理断电，也不是 MCU 深度睡眠，不承诺特定待机电流。
- 重新连接电脑 USB 或按板上 KEY/BOOT 键恢复显示。按键唤醒后，本次断连期间不再自动息屏，直到下一次连接并断开 USB。
- 配置随取图下发并保存在设备中，离线重启后仍有效；已息屏时请先唤醒，再修改设置。拔线后继续计时需要安装电池。

检测方式与休眠限制参考 [Espressif USB Serial/JTAG 文档](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-guides/usb-serial-jtag-console.html)；屏幕采用 ST7305 Display OFF / Sleep IN 指令。

## 可选：添加局域网或外网设备

展开网页中的“添加远程设备（可选）”，填写目标设备能访问的看板地址，下载配对包，复制到目标 Windows 并运行 `install.cmd`。

- 同一局域网：填写看板电脑的局域网地址。
- 不同网络：可用 ZeroTier 等私有网络，也支持已部署的 HTTPS 反向代理地址。
- 安装包配置的是**看板服务地址**，不是被监控电脑的地址；远程电脑主动上报。

按客户端要求审核 Codex Hooks，重启 Qoder，再运行 `diagnose.cmd` 检查。监控程序不会批准操作、回答问题或控制 AI 任务。“本轮完成”只表示当前回复结束，不代表整个项目完成。

配对包包含专用上报令牌，应私下传输，不可公开。看板电脑需要保持开机和服务运行。

## 数据含义

- 缺失额度显示未知，不当作零；未返回重置时间的 5h 窗口显示使用提示。
- Codex 以接口实际窗口为准。当前实现对 Pro 缺少独立 5h 窗口时显示 ∞，不表示所有 Pro 账户永久无限额。
- Qoder 套餐到期日与额度重置时间分开处理，不推测附加包到期日。
- 续费基准日期按账单填写一次。短月取月底，之后恢复原始日号（如 1 月 31 日 → 2 月 28 日 → 3 月 31 日）；年付同样保留闰年规则。当天仍显示当天，次日滚动到下一期。这里只计算预计日期，不确认实际扣款，也不将套餐到期日当作续费日。
- 费用和息屏设置保存后直接生效，不额外触发额度查询；更换账户后不会写入旧账户尚未完成的查询结果。设置文件写入失败时保留原有内存配置。
- GLM 高峰与 Qoder 夜惠按 UTC+8 和活动规则显示；夜惠仅适用于官方指定模型。规则可能变化，见 `monitor_periods.py`。
- 同一账户在不同电脑使用相同账户标识，保留最新快照，不累加余额。

## 隐私与配置

公开仓库仅包含源代码、模板和演示图。真实凭据、Wi-Fi 配置、账户快照、任务数据库、日志、配对包及固件备份均应保留在本机，并已加入忽略规则。

远程上报使用 Bearer 鉴权，配置接口只允许本机访问。外网建议通过私有网络连接；使用 HTTPS 反向代理时仅转发 `/api/ingest/`，不要开放设置、配对、预览与其他接口。不要直接映射明文 HTTP 端口到公网。文档中的 `192.0.2.x` 为文档专用示例地址，不是部署地址。

## 开发与测试

```text
work/rlcd_companion/server/              服务、采集器、渲染与测试
work/rlcd_companion/agent/               本机与可选远程采集、Hooks
work/rlcd_companion/firmware/rlcd_client/ Arduino 固件
work/rlcd_companion/scripts/             启动、诊断与部署工具
work/vendor/                            硬件库及其许可文件
```

```powershell
cd work/rlcd_companion/server
.venv/Scripts/python.exe -m pytest -q
```

`/preview.png` 为屏幕预览，`/frame.bin` 固定 15,000 字节。GitHub Actions 自动运行测试；真实账户、客户端 Hooks 和硬件仍需部署后核验。

## 来源与许可

本项目独立维护，额度与任务界面面向本看板设计。

- [原始硬件项目](https://github.com/ljzqp/waveshare-esp32-s3-rlcd-4.2-ai-dashboard)：复用的固件、基础服务与备用像素宠物来源。
- [InfoHub](https://github.com/iwascy/InfoHub)：采集器架构参考，未复制其代码。
- 微雪开发包及第三方库保留各自许可；Codex 名称和截图中的宠物外观属于相应权利人。

新增独立模块采用 MIT 许可，范围见 [LICENSE-ADDITIONS.md](LICENSE-ADDITIONS.md)。复用代码不被此许可重新授权；来源记录见 [原始项目说明](docs/UPSTREAM-README.md)。
