
---

## Docker 部署

```bash
# 在线拉取
docker run -d --name secreq -p 8000:8000 \
  -v secreq-data:/app/data -v secreq-output:/app/output \
  {{IMAGE}}:{{VERSION_NUM}}

# 离线导入(下载下方附件 secreq-image-*.tar.gz 后)
docker load -i secreq-image-{{VERSION}}.tar.gz
```

启动后访问 http://localhost:8000, 演示账号见 README。
