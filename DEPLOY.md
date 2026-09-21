# Docker 部署

问数平台和 Wren HTTP 分别版本管理、一起部署。平台仓库保存 Compose。两个仓库
位于相邻目录时，Wren HTTP 默认直接从 `../WrenAI` 构建，不会重新下载源码。
版本对应关系：

| 服务 | 仓库 | 版本 |
| --- | --- | --- |
| 问数平台 | `llx9826/ai-query-question-understanding` | `0.1.0` |
| Wren HTTP | `llx9826/WrenAI` | `wren-http-v0.1.0` |

这种方式保留两个服务和两个仓库的边界，同时让同一份 Compose 可重复构建整套系统。

## 1. 在 Linux 安装 Docker

Ubuntu 22.04/24.04 使用 Docker 官方 APT 仓库：

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

cat <<EOF | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

如果希望当前用户不加 `sudo` 运行 Docker：

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker version
docker compose version
```

CentOS Stream 9/10 使用 Docker 官方 RPM 仓库：

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

## 2. 配置

复制示例文件：

```bash
cp .env.example .env
```

填写 `.env` 中的三个独立随机 Token 和百炼 API Key。真实密钥不会进入镜像或 Git。
管理端默认监听 `30001`，Wren 运维接口默认只监听宿主机 `127.0.0.1:30002`；
两者都避开 `38080`。

相邻目录应为：

```text
query-question/
├── ai-query-question-understanding/
└── WrenAI/
```

对应配置为：

```text
WREN_HTTP_BUILD_CONTEXT=../WrenAI
```

如果服务器只克隆问数平台，再改为远程固定 tag：

```text
WREN_HTTP_BUILD_CONTEXT=https://github.com/llx9826/WrenAI.git#wren-http-v0.1.0
```

## 3. 启动

```bash
docker compose build
docker compose up -d
docker compose ps
```

打开 `http://<服务器地址>:30001/`。Wren 健康检查可在部署主机执行：

```bash
curl --fail http://127.0.0.1:30002/health
```

Compose 使用四个命名卷：控制库、AgentScope 会话、Excel/Wren 发布数据和 Wren
注册配置。Wren 只共享发布数据卷，不接触平台控制库。删除容器不会删除这些卷。

## 4. 停止与升级

```bash
docker compose down
```

升级时先修改 `.env` 中的镜像版本和 `WREN_HTTP_BUILD_CONTEXT` tag，再执行
`docker compose build` 和 `docker compose up -d`。不要使用 `docker compose down -v`，
除非明确要永久删除全部发布、会话和控制数据。

## 5. 部署验收

1. `docker compose ps` 中两个服务均为 healthy/running。
2. 打开管理端，上传一个真实 Excel 并看到活动 publication。
3. 创建会话连续问两轮，结果包含 publication、SQL、来源和工具轨迹。
4. 移除该 Excel 后新版本不可再查询，回滚后无需重传即可恢复。
5. 执行 `docker compose restart` 后会话和活动发布仍可读取。
