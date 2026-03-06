# AI Code Review Bot

GitHub PR이 생성되면 자체 학습 모델이 자동으로 코드 리뷰를 수행하는 End-to-End 시스템

## Architecture

```
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│  Part A. ML Pipeline (Python)   │    │  Part B. Review Bot (Kotlin)    │
│                                 │    │                                 │
│  GitHub API → 데이터 수집        │    │  GitHub Webhook → Spring Boot   │
│  → 전처리 → QLoRA Fine-tuning   │    │  → Redis Queue → Review Worker  │
│  → 평가 → vLLM 서빙             │    │  → vLLM / Claude → GitHub API   │
└─────────────────────────────────┘    └─────────────────────────────────┘
                    │                                    │
                    └──── MongoDB (shared) ──────────────┘
```

## Tech Stack

| Part | Stack |
|------|-------|
| ML Pipeline | Python 3.12+, HuggingFace Transformers, PEFT, TRL, vLLM, MLflow |
| Review Bot | Kotlin 2.3.10, Spring Boot 4.0.3, WebFlux, MongoDB, Redis Stream |
| Model | DeepSeek-Coder-V2-Lite (16B) + QLoRA Fine-tuning |
| Fallback | Claude API (Resilience4j Circuit Breaker) |
| Infra | Docker, Kubernetes, Prometheus, Grafana |

## Project Structure

```
ai-code-review/
├── ml-pipeline/          # Part A: ML Pipeline (Python)
│   ├── data/             # 데이터 수집 & 전처리
│   ├── training/         # QLoRA Fine-tuning
│   ├── evaluation/       # 모델 평가
│   └── serving/          # vLLM 추론 서버
├── review-bot/           # Part B: Review Bot (Kotlin)
│   └── src/main/kotlin/  # Spring Boot 애플리케이션
├── infra/                # Docker Compose, Prometheus, Grafana
└── README.md
```

## Getting Started

```bash
# 전체 시스템 실행
docker compose -f infra/docker-compose.yml up -d

# ML Pipeline (Python)
cd ml-pipeline && uv sync && uv run python -m data.collector.pr_collector

# Review Bot (Kotlin)
cd review-bot && ./gradlew bootRun
```
