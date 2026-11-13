FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HW3_SCRIPTS=/opt/hw3
WORKDIR /app
COPY HW5/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY HW3/scripts/common.py HW3/scripts/aggregates.py HW3/scripts/mapreduce.py /opt/hw3/
COPY HW5/app/ /app/
USER 10001:10001
ENTRYPOINT ["python", "/app/job.py"]
