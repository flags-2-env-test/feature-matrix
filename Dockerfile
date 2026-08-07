# Base pinned by digest for the same reason the language fixtures pin theirs: a
# floating tag makes a red run ambiguous between "the library changed" and "the
# toolchain changed".
FROM debian:12-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241

WORKDIR /app

# bash for the harness, build-essential/make for the C core, and coreutils for
# timeout(1), which is what keeps the fifo case from hanging the build if the
# non-blocking open ever regresses.
RUN apt-get update \
 && apt-get install -y --no-install-recommends bash build-essential make ca-certificates coreutils \
 && rm -rf /var/lib/apt/lists/*

COPY .vendor/.zed/oresoftware/flags-2-env ./.vendor/.zed/oresoftware/flags-2-env

# Upstream tracks prebuilt macOS artifacts under build/; clean before building
# or the Linux link step consumes a Mach-O object.
RUN make -C .vendor/.zed/oresoftware/flags-2-env clean \
 && make -C .vendor/.zed/oresoftware/flags-2-env cli

COPY .cli-flags.toml EXPECTED.md run.sh ./
COPY scenarios ./scenarios

ENV FLAGS2ENV_CLI=/app/.vendor/.zed/oresoftware/flags-2-env/build/flags2env
ENV FIXTURE_ROOT=/app

ENTRYPOINT ["/app/run.sh"]
