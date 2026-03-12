# AI Code Review Bot

GitHub Pull Request가 생성되면 멀티 LLM(Claude, OpenAI, Gemini)을 활용하여 자동으로 코드 리뷰를 수행하는 봇입니다. GitHub App Webhook을 통해 PR 이벤트를 수신하고, Redis Stream 기반 비동기 큐로 리뷰를 처리한 뒤 결과를 PR 코멘트로 게시합니다.

## 주요 기능

- **멀티 LLM 코드 리뷰** -- Claude, OpenAI, Gemini 3개 프로바이더를 동시 지원하며 자동 fallback 전환
- **GitHub App 통합** -- Webhook 기반 PR 이벤트 자동 감지 및 HMAC-SHA256 서명 검증
- **비동기 리뷰 큐** -- Redis Stream을 활용한 안정적인 리뷰 요청 큐잉 및 처리
- **Circuit Breaker** -- Resilience4j 기반 LLM 프로바이더 장애 격리 및 자동 복구
- **리포지토리별 설정** -- 리포지토리 단위 리뷰 규칙, 모델 선호도, 파일 제외 패턴 설정
- **리뷰 통계** -- 프로바이더별, 카테고리별 리뷰 통계 및 평균 레이턴시 조회
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
                    +---------+---------+
                    |                   |
                    v                   v
           GitHub PR Comment     MongoDB (저장)
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
| Logging | kotlin-logging (SLF4J) | 7.0.3 |
| Testing | JUnit 5 + MockK + Testcontainers + WireMock | - |
| Build | Gradle (Kotlin DSL) | 8.14 |
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
├── docker-compose.yml
└── review-bot/
    ├── .env.example
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

## 로컬 실행 방법

### Prerequisites

- JDK 21
- Docker & Docker Compose
- GitHub App 등록 (webhook 수신용)

### 1. 의존성 서비스 실행

```bash
docker compose up -d
```

### 2. 환경 변수 설정

```bash
cp review-bot/.env.example review-bot/.env
# .env 파일에 API 키 입력
```

### 3. 애플리케이션 실행

```bash
cd review-bot
./gradlew bootRun --args='--spring.profiles.active=local'
```

### 4. 상태 확인

```bash
curl http://localhost:8080/actuator/health
```

## License

MIT License
