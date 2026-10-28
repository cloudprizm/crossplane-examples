#!/usr/bin/env bash
# Serwowanie modelu dla zespołu na EC2 z GPU 24 GB (g5.xlarge / g6.xlarge), Deep Learning AMI.
# vLLM zamiast Ollamy: continuous batching = wiele zapytań naraz, API zgodne z OpenAI.
#   export VLLM_API_KEY=... HF_TOKEN=...
#   ./serving/vllm.sh                          # Qwen2.5-Coder-7B AWQ
#   MODEL=Qwen/Qwen2.5-Coder-14B-Instruct-AWQ MAX_LEN=16384 ./serving/vllm.sh
set -euo pipefail
MODEL=${MODEL:-Qwen/Qwen2.5-Coder-7B-Instruct-AWQ}
MAX_LEN=${MAX_LEN:-32768}

docker run -d --name vllm --restart unless-stopped --gpus all --ipc=host -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e HF_TOKEN="${HF_TOKEN:-}" \
  vllm/vllm-openai:latest \
  --model "$MODEL" \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 32 \
  --enable-prefix-caching \
  --api-key "$VLLM_API_KEY"
# Adaptery LoRA per repo (format PEFT, nie MLX):
#   --enable-lora --max-lora-rank 16 --lora-modules crossplane-infra=/adapters/infra

echo "Logi: docker logs -f vllm  (szukaj 'Maximum concurrency')"
echo "Klient: export LLM_URL=http://<host>:8000/v1 LLM_MODEL=$MODEL LLM_API_KEY=\$VLLM_API_KEY"
