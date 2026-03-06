package com.reviewer.api.webhook

import com.reviewer.api.exception.ApiException
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.WebhookSignatureVerifier
import com.reviewer.infrastructure.git.dto.WebhookPayload
import com.reviewer.infrastructure.metrics.ReviewMetrics
import com.reviewer.infrastructure.queue.ReviewMessage
import com.reviewer.infrastructure.queue.ReviewQueueProducer
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service

private val logger = KotlinLogging.logger {}

@Service
class WebhookService(
    private val webhookSignatureVerifier: WebhookSignatureVerifier,
    private val registeredRepositoryRepository: RegisteredRepositoryRepository,
    private val reviewRequestRepository: ReviewRequestRepository,
    private val reviewQueueProducer: ReviewQueueProducer,
    private val reviewMetrics: ReviewMetrics,
) {

    companion object {
        private val REVIEWABLE_ACTIONS = setOf("opened", "synchronize", "reopened")
    }

    suspend fun handleWebhook(
        eventType: String,
        signature: String?,
        payload: ByteArray,
        parsedPayload: WebhookPayload,
    ) {
        reviewMetrics.incrementWebhookReceived()

        // 1. Verify signature
        if (!webhookSignatureVerifier.verify(payload, signature)) {
            throw ApiException(
                status = HttpStatus.UNAUTHORIZED,
                message = "Invalid webhook signature",
                errorCode = "invalid_signature",
            )
        }

        // 2. Only process pull_request events
        if (eventType != "pull_request") {
            logger.debug { "Ignoring non-PR event: $eventType" }
            return
        }

        val pr = parsedPayload.pullRequest ?: run {
            logger.warn { "Pull request payload is null for event: $eventType" }
            return
        }

        val repoFullName = parsedPayload.repository?.fullName ?: run {
            logger.warn { "Repository full name is null in webhook payload" }
            return
        }

        val installationId = parsedPayload.installation?.id ?: run {
            logger.warn { "Installation ID is null in webhook payload" }
            return
        }

        // 3. Check if action is reviewable
        if (parsedPayload.action !in REVIEWABLE_ACTIONS) {
            logger.debug { "Ignoring PR action: ${parsedPayload.action} for $repoFullName#${pr.number}" }
            return
        }

        // 4. Check if repository is registered and enabled
        val registeredRepo = registeredRepositoryRepository.findByFullName(repoFullName)
        if (registeredRepo == null || !registeredRepo.enabled) {
            logger.debug { "Repository not registered or disabled: $repoFullName" }
            return
        }

        // 5. Skip draft PRs if configured
        if (pr.draft && !registeredRepo.reviewConfig.reviewOnDraft) {
            logger.debug { "Skipping draft PR: $repoFullName#${pr.number}" }
            return
        }

        logger.info { "Processing PR webhook: $repoFullName#${pr.number} (${parsedPayload.action})" }

        // 6. Create review request
        val reviewRequest = ReviewRequest(
            repositoryFullName = repoFullName,
            pullRequestNumber = pr.number,
            pullRequestTitle = pr.title,
            pullRequestUrl = pr.htmlUrl,
            headSha = pr.head.sha,
            baseBranch = pr.base.ref,
            headBranch = pr.head.ref,
            authorLogin = pr.user.login,
            installationId = installationId,
            status = ReviewStatus.QUEUED,
        )

        val savedRequest = reviewRequestRepository.save(reviewRequest)
        reviewMetrics.incrementReviewRequests()

        // 7. Enqueue for processing
        reviewQueueProducer.enqueue(
            ReviewMessage(
                reviewRequestId = savedRequest.id ?: throw IllegalStateException("Saved review request has no ID"),
                repositoryFullName = repoFullName,
                pullRequestNumber = pr.number,
                installationId = installationId,
            ),
        )

        logger.info {
            "Review request queued: id=${savedRequest.id}, " +
                "repo=$repoFullName, PR=#${pr.number}"
        }
    }
}
