FROM nginx:1.19.6-alpine

RUN apk add --no-cache openssl

RUN mkdir -p /etc/nginx/ssl/certs \
    && chmod -R 755 /etc/nginx/ssl

COPY docker-entrypoint-auto-reload.sh /
ENTRYPOINT ["/docker-entrypoint-auto-reload.sh"]
CMD ["nginx", "-g", "daemon off;"]

COPY dhparam /etc/nginx/ssl
COPY default.conf.template /etc/nginx/templates/
