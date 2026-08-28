ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt
COPY app /app
COPY run.sh /run.sh
RUN chmod 0555 /app/run.py /run.sh

EXPOSE 8098
CMD ["/run.sh"]
