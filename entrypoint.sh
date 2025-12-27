#!/bin/sh

# 检查是否设置了加密密钥
if [ -z "$AI_ROUTER_ENCRYPTION_KEY" ]; then
    echo ""
    echo "=========================================="
    echo "  首次启动，请设置加密密钥"
    echo "=========================================="
    echo ""
    echo "生成的密钥："
    python scripts/gen_fernet_key.py
    echo ""
    echo "请将上述密钥添加到 docker-compose.yml："
    echo ""
    echo "  environment:"
    echo "    - AI_ROUTER_ENCRYPTION_KEY=<上面的密钥>"
    echo ""
    echo "然后重启容器：docker-compose up -d"
    echo "=========================================="
    exit 1
fi

# 初始化数据库并启动
python scripts/init_db.py && exec python main.py
