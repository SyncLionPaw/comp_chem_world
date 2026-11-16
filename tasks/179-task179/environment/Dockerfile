FROM comp-chem-world-base
# Pin the local Harbor terminal runtime tools to Ubuntu Noble package versions.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tmux=3.4-1ubuntu0.2 asciinema=2.4.0-1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Preserve the frozen verifier’s isolated Python-only chroot. The candidate
# interpreter and stdlib are copied into an image-owned, non-writable root.
RUN set -eu; root=/opt/ccb-python-rootfs; \
    mkdir -p "$root/usr/bin" "$root/usr/lib/python3.12" "$root/usr/lib/python3.12/lib-dynload" "$root/work"; \
    cp -L /usr/bin/python3.12 "$root/usr/bin/python3"; \
    cp -a /usr/lib/python3.12/. "$root/usr/lib/python3.12/"; \
    for obj in /usr/bin/python3.12 /usr/lib/python3.12/lib-dynload/*.so; do \
      ldd "$obj" 2>/dev/null | awk '{for (i=1;i<=NF;i++) if (substr($i,1,1)=="/") print $i}' | while read -r lib; do \
        [ -f "$lib" ] || continue; dest="$root$lib"; mkdir -p "$(dirname "$dest")"; cp -L "$lib" "$dest"; \
      done; \
    done; chmod -R a-w "$root"; chmod 0777 "$root/work"
ENV CCB_PYTHON_ROOTFS=/opt/ccb-python-rootfs
