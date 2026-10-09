ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app
COPY app /app
COPY run.sh /run.sh
RUN chmod 0555 /run.sh /app/run.py

EXPOSE 8098
CMD ["/run.sh"]
