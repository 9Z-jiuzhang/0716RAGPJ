# 前端静态站点镜像：把 frontend 打进镜像并保证目录可遍历，避免云端解压丢 +x 导致 /assets 403 白屏
FROM nginx:1.25-alpine

COPY docker/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/ /usr/share/nginx/html/
COPY docker/web/docker-entrypoint.sh /docker-entrypoint-web.sh

RUN sed -i 's/\r$//' /docker-entrypoint-web.sh \
    && chmod 755 /docker-entrypoint-web.sh \
    && find /usr/share/nginx/html -type d -exec chmod 755 {} \; \
    && find /usr/share/nginx/html -type f -exec chmod 644 {} \;

EXPOSE 9082

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:9082/assets/js/router.js >/dev/null || exit 1

ENTRYPOINT ["/bin/sh", "/docker-entrypoint-web.sh"]
CMD ["nginx", "-g", "daemon off;"]
