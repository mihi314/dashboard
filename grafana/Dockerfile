FROM grafana/grafana-oss:12.4.3

COPY datasources/postgres.yaml "$GF_PATHS_PROVISIONING/datasources"

# Touch support for the time series panels (https://github.com/grafana/grafana/issues/8799): serve the script as a
# static file and load it on every page. Fails the build if a Grafana update changes the page template. Browsers may
# cache static files for an hour, so the URL carries a hash of the script to make them load a new version right away.
USER root
COPY grafana-touch.js "$GF_PATHS_HOME/public/"
RUN version=$(sha256sum "$GF_PATHS_HOME/public/grafana-touch.js" | cut -c1-8) \
    && sed -i "s|</head>|<script nonce=\"[[.Nonce]]\" src=\"public/grafana-touch.js?v=$version\" defer></script></head>|" \
        "$GF_PATHS_HOME/public/views/index.html" \
    && grep -q grafana-touch.js "$GF_PATHS_HOME/public/views/index.html"
USER grafana
