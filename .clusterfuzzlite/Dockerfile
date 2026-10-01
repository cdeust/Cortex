# ClusterFuzzLite build environment for the fuzz/ harnesses.
#
# ClusterFuzzLite is the per-repository form of OSS-Fuzz: it builds the
# harnesses in fuzz/ against libFuzzer via atheris and runs them on pull
# requests (a short batch) and on a schedule (a longer one). See
# .github/workflows/fuzz.yml for the two cadences.
#
# source: ADR-0795





FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:093721649cdd0d15c1e97eb905ed94079c09ffc8b3341c5dc42957b92f1b388f

# $SRC is the OSS-Fuzz convention for the checkout root.
COPY --from=ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 /uv /usr/local/bin/uv
COPY . $SRC/cortex
WORKDIR $SRC/cortex
COPY .clusterfuzzlite/build.sh $SRC/build.sh
