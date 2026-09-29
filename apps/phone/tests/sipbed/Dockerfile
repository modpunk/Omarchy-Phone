# Throwaway SIP test bed for the baresip backend: Asterisk (PJSIP) + two baresip endpoints in one
# container. Everything talks over the container's own 127.0.0.1; only the two baresip ctrl_tcp
# ports are published, to the host's 127.0.0.1. Test accounts only, no real SIP credentials.
FROM alpine:3.22 AS build
RUN apk add --no-cache build-base cmake git openssl-dev zlib-dev linux-headers
ARG RE_VERSION=v4.11.0
ARG BARESIP_VERSION=v4.11.0
RUN git clone --depth 1 -b "$RE_VERSION" https://github.com/baresip/re /src/re \
 && cmake -S /src/re -B /src/re/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
 && cmake --build /src/re/build -j"$(nproc)" \
 && cmake --install /src/re/build \
 && DESTDIR=/out cmake --install /src/re/build
RUN git clone --depth 1 -b "$BARESIP_VERSION" https://github.com/baresip/baresip /src/baresip \
 && cmake -S /src/baresip -B /src/baresip/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
      -DMODULES="account;menu;ctrl_tcp;g711;ausine;aufile" \
 && cmake --build /src/baresip/build -j"$(nproc)" \
 && DESTDIR=/out cmake --install /src/baresip/build \
 && rm -rf /out/usr/include /out/usr/lib/pkgconfig /out/usr/lib/cmake /out/usr/lib/*.a

FROM alpine:3.22
RUN apk add --no-cache asterisk openssl zlib
COPY --from=build /out/ /
COPY asterisk/ /etc/asterisk/
COPY baresip/ /sipbed/
COPY entrypoint.sh /sipbed/entrypoint.sh
RUN mkdir -p /sipbed/out && chmod +x /sipbed/entrypoint.sh
EXPOSE 4444 4445
ENTRYPOINT ["/sipbed/entrypoint.sh"]
