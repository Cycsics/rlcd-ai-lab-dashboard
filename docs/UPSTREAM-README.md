# Waveshare ESP32-S3-RLCD-4.2 AI Dashboard

也叫 **RLCD 桌面小伙伴**。这是一个基于微雪 ESP32-S3-RLCD-4.2 的桌面信息屏项目，用一块 4.2 寸全反射 RLCD 显示日程、天气、室内温湿度、音乐状态，以及 Codex / AI Coding 任务提醒。

这个仓库面向两类朋友：

- 想低成本复刻一个桌面小屏。
- 想了解“Mac 取数渲染 + ESP32 拉图显示”这种实现方式。

## 推荐方式：让 Agent 帮你安装

如果你会使用 Codex、WorkBuddy，或其他能读取 GitHub 仓库的 AI Agent，建议先让 Agent 接管安装和排查。这个项目已经内置两个 Skill：

```text
skills/rlcd-desk-companion   # 从 0 到 1 安装联调
skills/rlcd-flash            # 专门处理编译、烧录、串口和 frame.bin 验证
```

### 方式 A：导入整个仓库

把这个仓库导入 Codex / WorkBuddy / 其他 Agent：

```text
https://github.com/ljzqp/waveshare-esp32-s3-rlcd-4.2-ai-dashboard
```

然后把这段话发给 Agent：

```text
请帮我复刻这个 ESP32-S3-RLCD-4.2 桌面小伙伴。

先阅读 README.md、docs/getting-started.md 和 skills/rlcd-desk-companion/SKILL.md。
到编译、烧录、串口诊断时再阅读 skills/rlcd-flash/SKILL.md。
按 Skill 的流程一步步执行：环境检查、启动 Mac 预览、写入 Wi-Fi 配置、编译固件、烧录开发板、验证屏幕是否请求 frame.bin。

不要让我把 Wi-Fi 密码、飞书密钥或公网 token 发到聊天里。需要输入敏感信息时，请运行项目脚本，让我在本机终端输入。
```

### 方式 B：只导入 Skill

如果你的 Agent 支持导入 Skill / 工作流 / 知识库，把这两个目录作为安装助手导入：

```text
skills/rlcd-desk-companion
skills/rlcd-flash
```

Codex 本地可以这样安装：

```bash
git clone https://github.com/ljzqp/waveshare-esp32-s3-rlcd-4.2-ai-dashboard.git
cd waveshare-esp32-s3-rlcd-4.2-ai-dashboard
mkdir -p ~/.codex/skills
cp -R skills/rlcd-desk-companion ~/.codex/skills/
cp -R skills/rlcd-flash ~/.codex/skills/
```

然后重启 Codex，让它重新加载 Skill。

## 你会做出什么

当前实现包含这些能力：

- 今日节奏条：把一天压缩成时间轴，标出会议、空档和当前时间。
- 飞书日程：展示今天剩余会议；周末无日程时可展示下周一日程。
- 会议提醒：提前 15 分钟、5 分钟、到点提醒，并在提醒页显示会议室。
- AI Coding 状态：显示空闲、编程中、完成、需要确认、中断等状态。
- 天气与环境：显示天气、室内温湿度、电量。
- 音乐状态：AI 空闲时显示当前播放音乐。
- 本地动画与提示音：小伙伴动画在 ESP32 本地刷新，会议和 AI 完成时播放短提示音。

## 手动复刻

不使用 Agent 也可以手动安装。按这个顺序看：

1. [购买清单](docs/buying-list.md)
2. [从 0 到 1 复刻教程](docs/getting-started.md)
3. [常见问题 Q&A](docs/qa.md)
4. [用 Codex / Agent 辅助安装](docs/codex-skill-install.md)

最小启动流程：

```bash
git clone https://github.com/ljzqp/waveshare-esp32-s3-rlcd-4.2-ai-dashboard.git
cd waveshare-esp32-s3-rlcd-4.2-ai-dashboard
work/rlcd_companion/scripts/doctor.sh
RLCD_FEISHU_ENABLED=0 work/rlcd_companion/scripts/run_server.sh
```

浏览器打开：

```text
http://127.0.0.1:8787/preview.png
```

如果能看到 400 x 300 的黑白预览图，再继续写 Wi-Fi 配置、编译和烧录。

已经接好开发板后，也可以让 Agent 使用烧录 Skill：

```bash
skills/rlcd-flash/scripts/rlcd_flash.sh full
```

## 核心原理

本项目采用“Mac 负责取数和画图，ESP32 负责拉图显示”的架构：

```text
飞书 / 天气 / 音乐 / Codex 状态
            ↓
      Mac 本地服务
            ↓  /frame.bin  400x300 黑白位图
        ESP32-S3-RLCD-4.2
            ↓
          桌面屏
```

这样做的好处是硬件端保持简单。中文字体、飞书授权、天气接口、音乐状态、AI Coding 状态都在 Mac 端处理；ESP32 只需要联网拉取 1-bit 位图并显示。

关键接口：

```text
GET  /preview.png   浏览器预览图
GET  /frame.bin     ESP32 拉取的 400x300 黑白位图，固定 15000 字节
POST /codex/status  Codex / Agent 任务状态上报
POST /ack           开发板按键确认提醒
GET  /state         当前聚合状态
```

## 项目结构

```text
work/rlcd_companion/
├── server/                 # Mac 本地服务：取数、提醒判断、渲染画面
├── firmware/rlcd_client/   # ESP32-S3-RLCD-4.2 Arduino 固件
└── scripts/                # 启动、诊断、烧录、AI 状态上报脚本

docs/
├── buying-list.md          # 购买清单
├── getting-started.md      # 小白复刻教程
├── qa.md                   # 常见问题
└── codex-skill-install.md  # Codex / Agent 辅助安装方式

skills/rlcd-desk-companion/
└── SKILL.md                # 给 Codex / Agent 使用的安装联调 Skill

skills/rlcd-flash/
├── SKILL.md                # 给 Codex / Agent 使用的烧录联调 Skill
├── scripts/rlcd_flash.sh   # 编译、烧录、启动服务、验证闭环的一键脚本
└── references/             # 烧录和联网故障处理
```

## 当前边界

- 当前主要面向 macOS。
- ESP32-S3 只能连接 2.4GHz Wi-Fi，不能连接 5GHz Wi-Fi。
- 飞书功能依赖本机 `lark-cli` 用户授权。
- 公司网络与手机热点不在同一网络时，需要公网服务器做反向隧道，或改回同一局域网。

## 安全提醒

不要把这些文件提交到公开仓库、Issue、评论区或聊天记录：

- `work/rlcd_companion/firmware/rlcd_client/config.h`
- `work/rlcd_companion/server/config.yaml`
- 任何 `.log`、`.err.log`
- 任何包含 Wi-Fi 密码、飞书凭据、公网 token 的文件

仓库已经提供 `.gitignore`，但你 fork 或改造时仍然要自己检查一次。
