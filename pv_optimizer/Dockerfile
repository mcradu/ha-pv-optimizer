ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app
COPY app /app
RUN chmod 0555 /app/run.py

EXPOSE 8099
CMD ["python3", "/app/run.py"]
