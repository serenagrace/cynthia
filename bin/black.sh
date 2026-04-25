#!/bin/bash
black $(git rev-parse --show-toplevel) --target-version py311
