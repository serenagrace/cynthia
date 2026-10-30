#!/bin/bash
root=$(git rev-parse --show-toplevel)
isort "$root"
black "$root" --target-version py311
