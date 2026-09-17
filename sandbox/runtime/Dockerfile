# Arena Sandbox Python Runtime
# 基于官方 Python 3.11 slim 镜像
# Digest: sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

# 设置工作目录
WORKDIR /workspace

# 运行时不需要额外依赖，保持最小化
# 候选代码将通过 stdin 或临时文件传入

# 默认命令（将被执行时覆盖）
CMD ["python3"]
