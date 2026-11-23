#!/bin/sh
# JupyterLab on the notebooks of the image. With EGMS_NOTEBOOK_TOKEN set, that is
# the token; without, Jupyter makes a random one and prints it in the logs.
set -eu
if [ -n "${EGMS_NOTEBOOK_TOKEN:-}" ]; then
    exec jupyter lab --ip=0.0.0.0 --port=8889 --no-browser \
        --ServerApp.root_dir=/app/notebooks --IdentityProvider.token="$EGMS_NOTEBOOK_TOKEN"
fi
exec jupyter lab --ip=0.0.0.0 --port=8889 --no-browser --ServerApp.root_dir=/app/notebooks
