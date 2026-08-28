#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Rețele Electrice Collector"
exec python3 /app/run.py
