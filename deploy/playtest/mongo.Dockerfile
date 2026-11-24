FROM mongo:7.0.48

RUN mkdir -m 0755 /opt/playtest
COPY --chmod=0444 mongo-init.js /docker-entrypoint-initdb.d/10-playtest.js
COPY --chmod=0444 maintenance.js /opt/playtest/maintenance.js
USER mongodb
