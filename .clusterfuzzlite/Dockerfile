# ClusterFuzzLite build environment for the fuzz/ harnesses.
#
# ClusterFuzzLite is the per-repository form of OSS-Fuzz: it builds the
# harnesses in fuzz/ against libFuzzer via atheris and runs them on pull
# requests (a short batch) and on a schedule (a longer one). See
# .github/workflows/fuzz.yml for the two cadences.
#
# Base image pinned by digest, exactly as the other four Dockerfiles in this
# repository are: an unpinned base makes the build non-reproducible and is
# itself an OpenSSF Scorecard Pinned-Dependencies finding, so adding fuzzing
# with a floating base would trade one finding for another.
#   source: gcr.io/v2/oss-fuzz-base/base-builder-python/manifests/latest,
#           docker-content-digest header, fetched 2026-07-28.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:093721649cdd0d15c1e97eb905ed94079c09ffc8b3341c5dc42957b92f1b388f

# $SRC is the OSS-Fuzz convention for the checkout root.
COPY . $SRC/cortex
WORKDIR $SRC/cortex
COPY .clusterfuzzlite/build.sh $SRC/build.sh
