package com.reviewer.api.webhook

import com.reviewer.api.exception.ApiException
import com.reviewer.config.properties.GitHubProperties
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.WebhookSignatureVerifier
import com.reviewer.infrastructure.git.dto.GitHubWebhookPayload
import com.reviewer.infrastructure.queue.ReviewMessage
import com.reviewer.infrastructure.queue.ReviewQueueProducer
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import tools.jackson.databind.DeserializationFeature
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.json.JsonMapper
import tools.jackson.module.kotlin.readValue
import java.time.Instant

private val logger = KotlinLogging.logger {}

@Service
class WebhookService(
    private val signatureVerifier: WebhookSignatureVerifier,
    private val gitHubProperties: GitHubProperties,
    private val repositoryRepository: RegisteredRepositoryRepository,
    private val reviewRequestRepository: ReviewRequestRepository,
    private val queueProducer: ReviewQueueProducer,
) {
    private val objectMapper = JsonMapper.builder()
        .findAndAddModules()
        .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
        .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
        .build()

    suspend fun handleWebhook(event: String, signature: String, body: ByteArray) {
        // 1. 서명 검증
        if (!signatureVerifier.verify(body, signature, gitHubProperties.webhookSecret)) {
            throw ApiException(HttpStatus.UNAUTHORIZED, "Invalid webhook signature")
        }

        // 2. PR 이벤트만 처리
        if (event != "pull_request") {
            logger.debug { "Ignoring event: $event" }
            return
        }

        val payload: GitHubWebhookPayload = objectMapper.readValue(String(body))

        // 3. action 필터링
        if (payload.action !in listOf("opened", "synchronize", "reopened")) {
            logger.debug { "Ignoring PR action: ${payload.action}" }
            return
        }

        val pr = payload.pullRequest ?: return
        val repoFullName = payload.repository?.fullName ?: return
        val installationId = payload.installation?.id ?: return

        // 4. 봇 PR skip
        if (payload.sender?.type == "Bot") {
            logger.debug { "Skipping bot PR from ${payload.sender.login}" }
            return
        }

        // 5. 등록된 레포 확인
        val repository = repositoryRepository.findByFullName(repoFullName)
        if (repository == null || !repository.isActive) {
            logger.debug { "Repository not registered or inactive: $repoFullName" }
            return
        }

        // 6. Draft PR 확인
        if (pr.draft && !repository.settings.reviewOnDraft) {
            logger.debug { "Skipping draft PR #${pr.number}" }
            return
        }

        // 7. ReviewRequest 생성
        val reviewRequest = ReviewRequest(
            repositoryId = repository.id!!,
            repositoryFullName = repoFullName,
            platformPrId = pr.number,
            title = pr.title,
            author = pr.user.login,
            headSha = pr.head.sha,
            baseBranch = pr.base.ref,
            headBranch = pr.head.ref,
            status = ReviewStatus.PENDING,
            createdAt = Instant.now(),
        )

        val saved = reviewRequestRepository.save(reviewRequest)

        // 8. 큐 발행
        queueProducer.enqueue(
            ReviewMessage(
                reviewRequestId = saved.id!!,
                repositoryFullName = repoFullName,
                pullRequestNumber = pr.number,
            ),
        )

        logger.info { "Queued review for $repoFullName#${pr.number}" }
    }
}
