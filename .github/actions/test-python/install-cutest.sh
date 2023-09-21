#!/usr/bin/env bash

set -e
set -x

# Download CUTEst and its dependencies
mkdir "$GITHUB_WORKSPACE/cutest"
git clone --depth 1 --branch v2.1.24 https://github.com/ralna/ARCHDefs.git "$GITHUB_WORKSPACE/cutest/archdefs"
git clone --depth 1 --branch v2.0.6 https://github.com/ralna/SIFDecode.git "$GITHUB_WORKSPACE/cutest/sifdecode"
git clone --depth 1 --branch v2.0.17 https://github.com/ralna/CUTEst.git "$GITHUB_WORKSPACE/cutest/cutest"
git clone --depth 1 --branch v0.5 https://bitbucket.org/optrove/sif.git "$GITHUB_WORKSPACE/cutest/mastsif"

# Set the environment variables
export ARCHDEFS="$GITHUB_WORKSPACE/cutest/archdefs"
export SIFDECODE="$GITHUB_WORKSPACE/cutest/sifdecode"
export CUTEST="$GITHUB_WORKSPACE/cutest/cutest"
export MASTSIF="$GITHUB_WORKSPACE/cutest/mastsif"
export MYARCH=pc64.lnx.gfo
{
  echo "ARCHDEFS=$ARCHDEFS"
  echo "SIFDECODE=$SIFDECODE"
  echo "CUTEST=$CUTEST"
  echo "MASTSIF=$MASTSIF"
  echo "MYARCH=$MYARCH"
} >> "$GITHUB_ENV"

# Build and install CUTEst
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/jfowkes/pycutest/master/.install_cutest.sh)"