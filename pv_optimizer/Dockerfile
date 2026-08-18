ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app
COPY app /app
COPY run.sh /run.sh
RUN chmod 0555 /app/run.py /run.sh

EXPOSE 8099
CMD ["/run.sh"]
