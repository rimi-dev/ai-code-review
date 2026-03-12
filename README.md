# AI Code Review Bot

멀티 LLM(Claude, OpenAI, Gemini)을 활용한 GitHub PR 자동 코드 리뷰 봇

## 아키텍처

```
GitHub PR Webhook → Spring Boot API → Redis Stream Queue → Review Worker
                                                              ├── Claude API
                                                              ├── OpenAI API
                                                              └── Gemini API
                                                                    ↓
                                                            GitHub PR Comment
```

## 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Kotlin 2.3.10 |
| 프레임워크 | Spring Boot 4.0.3 + WebFlux |
| DB | MongoDB 8.0 |
| 큐 | Redis 7 Stream |
| 회복성 | Resilience4j Circuit Breaker |
| 모니터링 | Prometheus + Grafana |
| 컨테이너 | Docker + Kubernetes |

## 실행 방법

```bash
# 인프라 기동
cd infra && docker compose up -d

# 애플리케이션 실행
cd review-bot && ./gradlew bootRun
```
