FROM timescale/timescaledb:2.31.0-pg18

COPY psqlrc /root/.psqlrc
COPY postgresql.conf /etc/postgresql/postgresql.conf

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
