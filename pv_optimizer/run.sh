#!/usr/bin/with-contenv bashio

bashio::log.info "Starting PV Optimizer with Supervisor environment"
exec python3 /app/run.py
