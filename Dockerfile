FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建数据目录（用于持久化 config / attachments / logs）
RUN mkdir -p /data && chmod 777 /data

# 数据目录挂载点
VOLUME /data

# 设置环境变量
ENV HOST=0.0.0.0
ENV PORT=8765
ENV RESUMEMAILER_DATA=/data

EXPOSE 8765

CMD ["python", "main.py"]
