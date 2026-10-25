#!/bin/sh
# 混入配樂並輸出成片。用法：sh finish.sh [無聲渲染檔] [輸出檔]
# 起點 87.5s 與 build_film.py 的 MUSIC_IN 一致（重拍對標題、收尾重音對片尾卡）。
set -eu
cd "$(dirname "$0")"
IN=${1:-renders/silent.mp4}
OUT=${2:-renders/VetLoop-intro.mp4}
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
ffmpeg -y -loglevel error -i "$IN" -ss 87.5 -i film/assets/music-src.mp3 \
  -filter_complex "[1:a]atrim=0:${DUR},asetpts=PTS-STARTPTS,afade=t=in:d=1.2,afade=t=out:st=$(echo "$DUR - 2" | bc):d=2,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart "$OUT"
echo "$OUT"
