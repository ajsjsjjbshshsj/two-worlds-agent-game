FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236

RUN mkdir -m 0755 /etc/twoworlds
COPY --chmod=0444 nginx/*.conf /etc/twoworlds/
COPY --chmod=0444 playtest/gateway.conf.template playtest/gateway.sh /etc/twoworlds/
USER nginx
ENTRYPOINT ["sh", "/etc/twoworlds/gateway.sh"]
