# Docker 部署指南

## 部署步骤

### 1. 创建 docker-compose.yml

```yaml
services:
  ai-router:
    image: yorag/ai-router-lite:latest
    container_name: ai-router-lite
    ports:
      - "8000:8000"
    environment:
      - AI_ROUTER_ENCRYPTION_KEY=
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

### 2. 首次启动获取密钥

```bash
docker-compose up
```

容器会生成密钥并打印到日志，然后退出。复制密钥。

### 3. 配置密钥并启动

将密钥填入 docker-compose.yml：

```yaml
environment:
  - AI_ROUTER_ENCRYPTION_KEY=你复制的密钥
```

重启：

```bash
docker-compose up -d
```

### 4. 访问

- API：`http://localhost:8000`
- 管理面板：`http://localhost:8000/admin`

首次访问管理面板需设置管理员密码。

---

## 常用命令

```bash
# 查看日志
docker-compose logs -f

# 停止
docker-compose down

# 重启
docker-compose restart

# 更新镜像
docker-compose pull && docker-compose up -d

# 重置管理员密码
docker exec -it ai-router-lite python scripts/reset_admin.py
```

---

## 注意事项

- `AI_ROUTER_ENCRYPTION_KEY` 必须保持一致，否则无法解密已存储的 API 密钥
- `data/` 目录包含数据库，请定期备份
