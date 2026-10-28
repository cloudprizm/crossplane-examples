#!/usr/bin/env bash
# Trening LoRA na Macu (MLX). Użycie: ./train.sh configs/my-repo.yaml [iters]
set -euo pipefail
CFG=$1; ITERS=${2:-600}
REPO=$(python -c "import yaml;print(yaml.safe_load(open('$CFG'))['repo'].replace('/','__'))")
MODEL=$(python -c "import yaml;print(yaml.safe_load(open('$CFG'))['base_model'])")
DATA=data/$REPO; ADAPT=adapters/$REPO

python -m mlx_lm.lora --model "$MODEL" --train --data "$DATA" \
  --adapter-path "$ADAPT" --iters "$ITERS" --batch-size 1 \
  --num-layers 16 --max-seq-length 8192 --learning-rate 1e-5 \
  --grad-checkpoint --steps-per-eval 100 --save-every 200

python -m mlx_lm.fuse --model "$MODEL" --adapter-path "$ADAPT" --save-path "models/$REPO"
echo "Gotowy model: models/$REPO"
