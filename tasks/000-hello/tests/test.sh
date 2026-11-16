#!/bin/bash
set -e

pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA && echo 1 > /logs/verifier/reward.txt || echo 0 > /logs/verifier/reward.txt
