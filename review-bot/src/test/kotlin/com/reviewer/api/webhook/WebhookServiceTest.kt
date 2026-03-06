package com.reviewer.api.webhook

import com.reviewer.api.exception.ApiException
import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.ReviewConfig
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.WebhookSignatureVerifier
import com.reviewer.infrastructure.git.dto.BranchRef
import com.reviewer.infrastructure.git.dto.InstallationPayload
import com.reviewer.infrastructure.git.dto.OwnerPayload
import com.reviewer.infrastructure.git.dto.PullRequestPayload
import com.reviewer.infrastructure.git.dto.RepositoryPayload
import com.reviewer.infrastructure.git.dto.SenderPayload
import com.reviewer.infrastructure.git.dto.WebhookPayload
import com.reviewer.infrastructure.metrics.ReviewMetrics
import com.reviewer.infrastructure.queue.ReviewMessage
import com.reviewer.infrastructure.queue.ReviewQueueProducer
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.runs
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class WebhookServiceTest {

    private val webhookSignatureVerifier: WebhookSignatureVerifier = mockk()
    private val registeredRepositoryRepository: RegisteredRepositoryRepository = mockk()
    private val reviewRequestRepository: ReviewRequestRepository = mockk()
    private val reviewQueueProducer: ReviewQueueProducer = mockk()
    private val reviewMetrics: ReviewMetrics = mockk(relaxed = true)

    private lateinit var webhookService: WebhookService

    @BeforeEach
    fun setUp() {
        webhookService = WebhookService(
            webhookSignatureVerifier = webhookSignatureVerifier,
            registeredRepositoryRepository = registeredRepositoryRepository,
            reviewRequestRepository = reviewRequestRepository,
            reviewQueueProducer = reviewQueueProducer,
            reviewMetrics = reviewMetrics,
        )
    }

    private fun buildPayload(
        action: String = "opened",
        prNumber: Int = 1,
        repoFullName: String = "owner/repo",
        installationId: Long = 12345L,
        draft: Boolean = false,
        authorLogin: String = "developer",
        headSha: String = "abc123def456",
        baseBranch: String = "main",
        headBranch: String = "feature/test",
    ) = WebhookPayload(
        action = action,
        number = prNumber,
        pullRequest = PullRequestPayload(
            id = 100L,
            number = prNumber,
            title = "Test PR",
            body = "Test body",
            state = "open",
            draft = draft,
            htmlUrl = "https://github.com/$repoFullName/pull/$prNumber",
            diffUrl = "https://github.com/$repoFullName/pull/$prNumber.diff",
            head = BranchRef(ref = headBranch, sha = headSha),
            base = BranchRef(ref = baseBranch, sha = "base123"),
            user = SenderPayload(login = authorLogin, id = 1L),
        ),
        repository = RepositoryPayload(
            id = 200L,
            fullName = repoFullName,
            name = repoFullName.split("/").last(),
            owner = OwnerPayload(login = repoFullName.split("/").first()),
        ),
        installation = InstallationPayload(id = installationId),
        sender = SenderPayload(login = authorLogin, id = 1L),
    )

    private fun buildRegisteredRepo(
        fullName: String = "owner/repo",
        enabled: Boolean = true,
        reviewOnDraft: Boolean = false,
    ) = RegisteredRepository(
        id = "repo-id-1",
        fullName = fullName,
        owner = fullName.split("/").first(),
        name = fullName.split("/").last(),
        installationId = 12345L,
        enabled = enabled,
        reviewConfig = ReviewConfig(reviewOnDraft = reviewOnDraft),
    )

    private fun stubValidSignature() {
        every { webhookSignatureVerifier.verify(any(), any()) } returns true
    }

    private fun stubInvalidSignature() {
        every { webhookSignatureVerifier.verify(any(), any()) } returns false
    }

    @Nested
    inner class ValidPrOpenedEvent {

        @Test
        fun `should create ReviewRequest and enqueue for PR opened event`() = runTest {
            stubValidSignature()
            val payload = buildPayload(action = "opened")
            val registeredRepo = buildRegisteredRepo()
            val savedRequest = ReviewRequest(
                id = "review-req-1",
                repositoryFullName = "owner/repo",
                pullRequestNumber = 1,
                pullRequestTitle = "Test PR",
                pullRequestUrl = "https://github.com/owner/repo/pull/1",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature/test",
                authorLogin = "developer",
                installationId = 12345L,
                status = ReviewStatus.QUEUED,
            )

            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { reviewRequestRepository.save(any()) } returns savedRequest
            coEvery { reviewQueueProducer.enqueue(any()) } just runs

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            val requestSlot = slot<ReviewRequest>()
            coVerify(exactly = 1) { reviewRequestRepository.save(capture(requestSlot)) }

            val captured = requestSlot.captured
            assertEquals("owner/repo", captured.repositoryFullName)
            assertEquals(1, captured.pullRequestNumber)
            assertEquals("Test PR", captured.pullRequestTitle)
            assertEquals("abc123def456", captured.headSha)
            assertEquals(ReviewStatus.QUEUED, captured.status)

            val messageSlot = slot<ReviewMessage>()
            coVerify(exactly = 1) { reviewQueueProducer.enqueue(capture(messageSlot)) }

            val capturedMessage = messageSlot.captured
            assertEquals("review-req-1", capturedMessage.reviewRequestId)
            assertEquals("owner/repo", capturedMessage.repositoryFullName)
            assertEquals(1, capturedMessage.pullRequestNumber)
            assertEquals(12345L, capturedMessage.installationId)
        }

        @Test
        fun `should create ReviewRequest for PR synchronize event`() = runTest {
            stubValidSignature()
            val payload = buildPayload(action = "synchronize")
            val registeredRepo = buildRegisteredRepo()
            val savedRequest = ReviewRequest(
                id = "review-req-2",
                repositoryFullName = "owner/repo",
                pullRequestNumber = 1,
                pullRequestTitle = "Test PR",
                pullRequestUrl = "https://github.com/owner/repo/pull/1",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature/test",
                authorLogin = "developer",
                installationId = 12345L,
                status = ReviewStatus.QUEUED,
            )

            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { reviewRequestRepository.save(any()) } returns savedRequest
            coEvery { reviewQueueProducer.enqueue(any()) } just runs

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 1) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 1) { reviewQueueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class IgnoredEvents {

        @Test
        fun `should ignore non-PR events like issues`() = runTest {
            stubValidSignature()
            val payload = buildPayload()

            webhookService.handleWebhook(
                eventType = "issues",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { reviewQueueProducer.enqueue(any()) }
        }

        @Test
        fun `should ignore push events`() = runTest {
            stubValidSignature()
            val payload = buildPayload()

            webhookService.handleWebhook(
                eventType = "push",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { reviewQueueProducer.enqueue(any()) }
        }

        @Test
        fun `should ignore non-reviewable PR actions like closed`() = runTest {
            stubValidSignature()
            val payload = buildPayload(action = "closed")
            val registeredRepo = buildRegisteredRepo()

            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { reviewQueueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class SkippedPr {

        @Test
        fun `should skip draft PR when reviewOnDraft is false`() = runTest {
            stubValidSignature()
            val payload = buildPayload(draft = true)
            val registeredRepo = buildRegisteredRepo(reviewOnDraft = false)

            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { reviewQueueProducer.enqueue(any()) }
        }

        @Test
        fun `should process draft PR when reviewOnDraft is true`() = runTest {
            stubValidSignature()
            val payload = buildPayload(draft = true)
            val registeredRepo = buildRegisteredRepo(reviewOnDraft = true)
            val savedRequest = ReviewRequest(
                id = "review-req-draft",
                repositoryFullName = "owner/repo",
                pullRequestNumber = 1,
                pullRequestTitle = "Test PR",
                pullRequestUrl = "https://github.com/owner/repo/pull/1",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature/test",
                authorLogin = "developer",
                installationId = 12345L,
                status = ReviewStatus.QUEUED,
            )

            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { reviewRequestRepository.save(any()) } returns savedRequest
            coEvery { reviewQueueProducer.enqueue(any()) } just runs

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 1) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 1) { reviewQueueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class UnregisteredRepo {

        @Test
        fun `should skip when repository is not registered`() = runTest {
            stubValidSignature()
            val payload = buildPayload(repoFullName = "unknown/repo")

            coEvery { registeredRepositoryRepository.findByFullName("unknown/repo") } returns null

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { reviewQueueProducer.enqueue(any()) }
        }

        @Test
        fun `should skip when repository is disabled`() = runTest {
            stubValidSignature()
            val payload = buildPayload()
            val registeredRepo = buildRegisteredRepo(enabled = false)

            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { reviewQueueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class InvalidSignatureHandling {

        @Test
        fun `should throw ApiException for invalid signature`() = runTest {
            stubInvalidSignature()
            val payload = buildPayload()

            val exception = assertThrows<ApiException> {
                webhookService.handleWebhook(
                    eventType = "pull_request",
                    signature = "sha256=invalid",
                    payload = ByteArray(0),
                    parsedPayload = payload,
                )
            }

            assertEquals("Invalid webhook signature", exception.message)
            assertEquals("invalid_signature", exception.errorCode)

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { reviewQueueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class MetricsTracking {

        @Test
        fun `should increment webhook received metric`() = runTest {
            stubValidSignature()
            val payload = buildPayload()
            val registeredRepo = buildRegisteredRepo()
            val savedRequest = ReviewRequest(
                id = "review-req-metrics",
                repositoryFullName = "owner/repo",
                pullRequestNumber = 1,
                pullRequestTitle = "Test PR",
                pullRequestUrl = "https://github.com/owner/repo/pull/1",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature/test",
                authorLogin = "developer",
                installationId = 12345L,
                status = ReviewStatus.QUEUED,
            )

            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { reviewRequestRepository.save(any()) } returns savedRequest
            coEvery { reviewQueueProducer.enqueue(any()) } just runs

            webhookService.handleWebhook(
                eventType = "pull_request",
                signature = "sha256=valid",
                payload = ByteArray(0),
                parsedPayload = payload,
            )

            coVerify(exactly = 1) { reviewMetrics.incrementWebhookReceived() }
            coVerify(exactly = 1) { reviewMetrics.incrementReviewRequests() }
        }
    }
}
