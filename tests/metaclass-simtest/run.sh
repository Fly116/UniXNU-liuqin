#!/bin/sh
set -e
cd "$(dirname "$0")"
g++ -std=c++17 -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. sim.cpp -o sim
ASAN_OPTIONS=detect_leaks=0 ./sim
