FROM timescale/timescaledb:2.9.2-pg15

COPY psqlrc /root/.psqlrc
COPY postgresql.conf /etc/postgresql/postgresql.conf

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
