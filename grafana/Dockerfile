FROM grafana/grafana-oss:12.4.3

COPY datasources/postgres.yaml "$GF_PATHS_PROVISIONING/datasources"

# Touch support for the time series panels (https://github.com/grafana/grafana/issues/8799): serve the script as a
# static file and load it on every page. Fails the build if a Grafana update changes the page template.
USER root
COPY grafana-touch.js "$GF_PATHS_HOME/public/"
RUN sed -i 's|</head>|<script nonce="[[.Nonce]]" src="public/grafana-touch.js" defer></script></head>|' \
        "$GF_PATHS_HOME/public/views/index.html" \
    && grep -q grafana-touch.js "$GF_PATHS_HOME/public/views/index.html"
USER grafana
