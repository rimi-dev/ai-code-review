# AI Code Review Bot

GitHub Pull Request가 생성되면 멀티 LLM(Claude, OpenAI, Gemini)을 활용하여 자동으로 코드 리뷰를 수행하는 봇입니다. GitHub App Webhook을 통해 PR 이벤트를 수신하고, Redis Stream 기반 비동기 큐로 리뷰를 처리한 뒤 결과를 PR 코멘트로 게시합니다.

## 주요 기능

- **멀티 LLM 코드 리뷰** -- Claude, OpenAI, Gemini 3개 프로바이더를 동시 지원하며 자동 fallback 전환
- **GitHub App 통합** -- Webhook 기반 PR 이벤트 자동 감지 및 HMAC-SHA256 서명 검증
- **비동기 리뷰 큐** -- Redis Stream을 활용한 안정적인 리뷰 요청 큐잉 및 처리
- **Circuit Breaker** -- Resilience4j 기반 LLM 프로바이더 장애 격리 및 자동 복구
- **리포지토리별 설정** -- 리포지토리 단위 리뷰 규칙, 모델 선호도, 파일 제외 패턴 설정
- **리뷰 통계** -- 프로바이더별, 카테고리별 리뷰 통계 및 평균 레이턴시 조회
- **모니터링** -- Prometheus 메트릭 수집 + Grafana 대시보드 시각화 + Alertmanager 알림
- **실패 리뷰 재시도** -- 실패한 리뷰를 수동으로 재큐잉하여 재처리

## 아키텍처

```
GitHub PR ──> Webhook ──> Review Bot (Spring WebFlux)
                              |
                              v
                    +---------+---------+
                    |   Redis Stream    |
                    |   (Review Queue)  |
                    +---------+---------+
                              |
                              v
                    +---------+---------+
                    |  Review Worker    |
                    |                   |
                    |  +-- Claude API   |
                    |  +-- OpenAI API   |
                    |  +-- Gemini API   |
                    +---------+---------+
                              |
              +---------------+---------------+
              |               |               |
              v               v               v
     GitHub PR Comment   MongoDB (저장)   Prometheus (메트릭)
                                              |
                                              v
                                      Grafana (시각화)
```

## 기술 스택

| 구분 | 기술 | 버전 |
|------|------|------|
| Language | Kotlin | 2.3.10 |
| Framework | Spring Boot + WebFlux | 4.0.3 |
| JDK | Eclipse Temurin | 21 |
| Database | MongoDB | 8.0 |
| Queue | Redis Stream | 7 (Alpine) |
| Resilience | Resilience4j Circuit Breaker | 2.3.0 |
| Monitoring | Prometheus + Grafana + Alertmanager | latest |
| Logging | kotlin-logging (SLF4J) | 7.0.3 |
| Testing | JUnit 5 + MockK + Testcontainers + WireMock | - |
| Build | Gradle (Kotlin DSL) | 8.14 |
| Container | Docker + Kubernetes | - |
| Coroutines | kotlinx-coroutines | 1.10.1 |

## 지원 LLM Provider

| Provider | 기본 모델 | Fallback 대상 | 기본 상태 |
|----------|-----------|---------------|-----------|
| **Claude** (Anthropic) | `claude-sonnet-4-20250514` | OpenAI | Enabled |
| **OpenAI** | `gpt-4o` | Gemini | Enabled |
| **Gemini** (Google) | `gemini-2.0-flash` | - | Disabled |

- **Fallback Chain**: Claude -> OpenAI -> Gemini 순서로 자동 전환
- 각 프로바이더에 독립적인 Circuit Breaker가 적용되어, 특정 프로바이더 장애 시 자동으로 다음 프로바이더로 전환됩니다.
- `LLM_DEFAULT_PROVIDER` 환경 변수로 기본 프로바이더를 변경할 수 있습니다. (기본값: `claude`)
- 리포지토리별로 `modelPreference`를 설정하여 리포지토리 단위로 프로바이더를 지정할 수 있습니다.

## 프로젝트 구조

```
ai-code-review/
├── README.md
├── infra/
│   ├── docker-compose.yml
│   └── prometheus/
│       └── prometheus.yml
└── review-bot/
    ├── Dockerfile
    ├── build.gradle.kts
    ├── settings.gradle.kts
    ├── gradlew / gradlew.bat
    └── src/main/kotlin/com/reviewer/
        ├── AiCodeReviewApplication.kt
        ├── api/
        │   ├── dto/                          # Request/Response DTO
        │   │   ├── ModelHealthResponse.kt
        │   │   ├── RepositoryRequest.kt
        │   │   ├── RepositoryResponse.kt
        │   │   ├── ReviewResponse.kt
        │   │   └── ReviewStatsResponse.kt
        │   ├── exception/                    # 전역 예외 처리
        │   │   ├── ApiException.kt
        │   │   └── GlobalExceptionHandler.kt
        │   ├── model/
        │   │   └── ModelHealthController.kt  # LLM 모델 상태 확인
        │   ├── repository/
        │   │   └── RepositoryController.kt   # 리포지토리 CRUD
        │   ├── review/
        │   │   └── ReviewController.kt       # 리뷰 조회/재시도
        │   ├── statistics/
        │   │   └── StatisticsController.kt   # 리뷰 통계
        │   └── webhook/
        │       ├── WebhookController.kt      # GitHub Webhook 수신
        │       └── WebhookService.kt
        ├── config/
        │   ├── JacksonConfig.kt
        │   ├── MongoConfig.kt
        │   ├── RedisConfig.kt
        │   ├── Resilience4jConfig.kt
        │   ├── WebClientConfig.kt
        │   ├── WebFluxConfig.kt
        │   └── properties/                   # 설정 프로퍼티
        │       ├── GitHubProperties.kt
        │       ├── LlmProperties.kt
        │       ├── RedisStreamProperties.kt
        │       └── ReviewProperties.kt
        ├── domain/
        │   ├── model/
        │   │   ├── RegisteredRepository.kt   # 등록 리포지토리 도메인
        │   │   └── ReviewRequest.kt          # 리뷰 요청 도메인
        │   ├── repository/
        │   │   ├── RegisteredRepositoryRepository.kt
        │   │   └── ReviewRequestRepository.kt
        │   └── service/
        │       ├── DiffService.kt            # PR diff 파싱
        │       ├── ReviewResponseParser.kt   # LLM 응답 파싱
        │       └── ReviewService.kt          # 리뷰 핵심 로직
        └── infrastructure/
            ├── git/
            │   ├── GitHubApiClient.kt        # GitHub REST API 클라이언트
            │   ├── GitHubAppTokenProvider.kt  # GitHub App 인증 토큰
            │   ├── WebhookSignatureVerifier.kt
            │   └── dto/
            │       └── GitHubDtos.kt
            ├── llm/
            │   ├── ClaudeReviewClient.kt     # Anthropic Claude API
            │   ├── GeminiClient.kt           # Google Gemini API
            │   ├── OpenAiClient.kt           # OpenAI API
            │   ├── ReviewLlmClient.kt        # LLM 클라이언트 인터페이스
            │   ├── ReviewLlmClientFactory.kt # LLM 팩토리 + Circuit Breaker
            │   ├── ReviewPromptBuilder.kt    # 리뷰 프롬프트 생성
            │   └── dto/
            │       └── LlmDtos.kt
            ├── metrics/
            │   └── ReviewMetrics.kt          # Prometheus 커스텀 메트릭
            └── queue/
                ├── ReviewMessage.kt          # 큐 메시지 모델
                ├── ReviewQueueConsumer.kt    # Redis Stream 컨슈머
                └── ReviewQueueProducer.kt    # Redis Stream 프로듀서
```

## 환경 변수

| 변수명 | 설명 | 기본값 | 필수 |
|--------|------|--------|------|
| `CLAUDE_API_KEY` | Anthropic Claude API Key | - | Yes (Claude 사용 시) |
| `OPENAI_API_KEY` | OpenAI API Key | - | Yes (OpenAI 사용 시) |
| `GEMINI_API_KEY` | Google Gemini API Key | - | No |
| `GITHUB_APP_ID` | GitHub App ID | - | Yes |
| `GITHUB_PRIVATE_KEY_PATH` | GitHub App Private Key 파일 경로 | - | Yes |
| `GITHUB_WEBHOOK_SECRET` | GitHub Webhook Secret | - | Yes |
| `MONGODB_URI` | MongoDB 접속 URI | `mongodb://localhost:27017/ai-code-review` | No |
| `REDIS_HOST` | Redis 호스트 | `localhost` | No |
| `REDIS_PORT` | Redis 포트 | `6379` | No |
| `LLM_DEFAULT_PROVIDER` | 기본 LLM 프로바이더 | `claude` | No |
| `LLM_MAX_TOKENS` | LLM 최대 응답 토큰 수 | `4096` | No |
| `CLAUDE_MODEL` | Claude 모델명 | `claude-sonnet-4-20250514` | No |
| `OPENAI_MODEL` | OpenAI 모델명 | `gpt-4o` | No |
| `GEMINI_MODEL` | Gemini 모델명 | `gemini-2.0-flash` | No |
| `REVIEW_MAX_DIFF_LINES` | 리뷰 대상 최대 diff 라인 수 | `3000` | No |
| `REVIEW_MAX_FILES` | 리뷰 대상 최대 파일 수 | `50` | No |
| `REDIS_STREAM_KEY` | Redis Stream 키 | `review-requests` | No |
| `REDIS_CONSUMER_GROUP` | Redis Consumer Group 이름 | `review-workers` | No |

## API Endpoints

### Webhook

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/v1/webhooks/github` | GitHub Webhook 이벤트 수신 (PR opened/synchronize) |

### Repositories

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/repositories` | 등록된 리포지토리 목록 조회 |
| `POST` | `/api/v1/repositories` | 리포지토리 등록 |
| `GET` | `/api/v1/repositories/{id}` | 리포지토리 상세 조회 |
| `PUT` | `/api/v1/repositories/{id}` | 리포지토리 설정 수정 |
| `DELETE` | `/api/v1/repositories/{id}` | 리포지토리 삭제 |
| `PUT` | `/api/v1/repositories/{id}/rules` | 리포지토리 리뷰 규칙 수정 |

### Reviews

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/reviews` | 리뷰 목록 조회 (`?repository=`, `?status=` 필터 지원) |
| `GET` | `/api/v1/reviews/{id}` | 리뷰 상세 조회 |
| `POST` | `/api/v1/reviews/{id}/retry` | 실패한 리뷰 재시도 |

### Statistics

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/statistics` | 리뷰 통계 조회 (프로바이더별, 카테고리별, 평균 레이턴시) |

### Model Health

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/models/health` | LLM 프로바이더 상태 및 Circuit Breaker 상태 확인 |

## 로컬 개발 환경 설정

### Prerequisites

- JDK 21+
- Docker & Docker Compose
- GitHub App 생성 및 설정 완료

### 1. 프로젝트 클론

```bash
git clone https://github.com/your-org/ai-code-review.git
cd ai-code-review
```

### 2. 환경 변수 설정

```bash
export CLAUDE_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GITHUB_APP_ID="123456"
export GITHUB_PRIVATE_KEY_PATH="/path/to/private-key.pem"
export GITHUB_WEBHOOK_SECRET="your-webhook-secret"
```

### 3. 인프라 기동 (MongoDB, Redis)

```bash
cd infra && docker compose up -d mongodb redis
```

### 4. 애플리케이션 빌드 및 실행

```bash
cd review-bot
./gradlew bootRun
```

애플리케이션이 `http://localhost:8080` 에서 실행됩니다.

### 5. 상태 확인

```bash
# Health check
curl http://localhost:8080/actuator/health

# LLM 프로바이더 상태 확인
curl http://localhost:8080/api/v1/models/health
```

## Docker Compose 실행

모든 서비스를 한 번에 기동합니다 (MongoDB, Redis, Review Bot, Prometheus, Grafana, Alertmanager).

```bash
cd infra && docker compose up -d
```

실행되는 서비스:

| 서비스 | 포트 | 설명 |
|--------|------|------|
| review-bot | 8080 | AI Code Review Bot API |
| mongodb | 27017 | MongoDB 데이터베이스 |
| redis | 6379 | Redis (Review Queue) |
| prometheus | 9090 | 메트릭 수집 |
| grafana | 3000 | 모니터링 대시보드 |
| alertmanager | 9093 | 알림 관리 |

서비스 중지:

```bash
cd infra && docker compose down
```

## Kubernetes 배포

```bash
# 네임스페이스 생성
kubectl create namespace ai-code-review

# Secret 생성 (API 키 및 GitHub 설정)
kubectl create secret generic review-bot-secrets \
  --namespace ai-code-review \
  --from-literal=CLAUDE_API_KEY="sk-ant-..." \
  --from-literal=OPENAI_API_KEY="sk-..." \
  --from-literal=GITHUB_APP_ID="123456" \
  --from-literal=GITHUB_WEBHOOK_SECRET="your-secret" \
  --from-file=GITHUB_PRIVATE_KEY_PATH=./private-key.pem

# Kubernetes 리소스 배포
kubectl apply -f infra/k8s/ --namespace ai-code-review

# 배포 상태 확인
kubectl get pods --namespace ai-code-review
```

## 모니터링

### Prometheus 메트릭

메트릭 엔드포인트: `http://localhost:8080/actuator/prometheus`

| 메트릭 | 타입 | 태그 | 설명 |
|--------|------|------|------|
| `review_total` | Counter | `provider`, `status` | 전체 리뷰 처리 수 |
| `review_duration_ms` | Timer | - | 리뷰 처리 소요 시간 |
| `review_tokens_total` | Counter | `provider`, `direction` | LLM 토큰 사용량 |
| `review_cost_usd` | Counter | `provider` | LLM 비용 (USD) |
| `review_fallback_total` | Counter | - | Fallback 발생 횟수 |
| `review_comments_total` | Counter | `category`, `severity` | 리뷰 코멘트 수 |
| `model_circuit_state` | Gauge | `provider` | Circuit Breaker 상태 (0=CLOSED, 1=HALF_OPEN, 2=OPEN) |
| `webhook_received_total` | Counter | - | 수신된 Webhook 수 |
| `queue_depth` | Gauge | - | 현재 리뷰 큐 대기 수 |

### Grafana 대시보드

Grafana 접속: `http://localhost:3000` (기본 계정: `admin` / `admin`)

Prometheus 데이터 소스가 자동 프로비저닝되며, 사전 구성된 대시보드에서 다음 항목을 확인할 수 있습니다:

- 리뷰 처리량 및 성공/실패 비율
- 프로바이더별 토큰 사용량 및 비용
- 리뷰 처리 레이턴시 분포
- Circuit Breaker 상태 추이
- 큐 대기 깊이 추이
- Webhook 수신 빈도

### Alertmanager

Alertmanager 접속: `http://localhost:9093`

Prometheus alert rules(`infra/prometheus/alert-rules.yml`)에 정의된 알림을 관리합니다.

## License

MIT License
