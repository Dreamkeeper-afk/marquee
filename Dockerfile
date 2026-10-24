FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY marquee ./marquee
ENV HOST=0.0.0.0 PORT=8484 DATA_DIR=/data
VOLUME /data
EXPOSE 8484
CMD ["python", "-m", "marquee"]
