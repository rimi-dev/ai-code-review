package com.reviewer.api.webhook

import com.reviewer.api.exception.ApiException
import com.reviewer.config.properties.GitHubProperties
import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.RepositorySettings
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.WebhookSignatureVerifier
import com.reviewer.infrastructure.queue.ReviewMessage
import com.reviewer.infrastructure.queue.ReviewQueueProducer
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.http.HttpStatus
import tools.jackson.databind.DeserializationFeature
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.json.JsonMapper

class WebhookServiceTest {

    private val signatureVerifier: WebhookSignatureVerifier = mockk()
    private val gitHubProperties: GitHubProperties = GitHubProperties(webhookSecret = "test-secret")
    private val repositoryRepository: RegisteredRepositoryRepository = mockk()
    private val reviewRequestRepository: ReviewRequestRepository = mockk()
    private val queueProducer: ReviewQueueProducer = mockk()

    private lateinit var webhookService: WebhookService

    private val objectMapper = JsonMapper.builder()
        .findAndAddModules()
        .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
        .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
        .build()

    @BeforeEach
    fun setUp() {
        webhookService = WebhookService(
            signatureVerifier = signatureVerifier,
            gitHubProperties = gitHubProperties,
            repositoryRepository = repositoryRepository,
            reviewRequestRepository = reviewRequestRepository,
            queueProducer = queueProducer,
        )
    }

    private fun buildPrPayload(
        action: String = "opened",
        prNumber: Int = 42,
        repoFullName: String = "owner/repo",
        installationId: Long = 12345L,
        draft: Boolean = false,
        senderType: String = "User",
        senderLogin: String = "developer",
    ): String {
        return objectMapper.writeValueAsString(
            mapOf(
                "action" to action,
                "number" to prNumber,
                "pull_request" to mapOf(
                    "id" to 100L,
                    "number" to prNumber,
                    "title" to "Test PR",
                    "body" to "PR body",
                    "state" to "open",
                    "draft" to draft,
                    "head" to mapOf(
                        "ref" to "feature-branch",
                        "sha" to "abc123def456",
                    ),
                    "base" to mapOf(
                        "ref" to "main",
                        "sha" to "base789sha",
                    ),
                    "user" to mapOf(
                        "login" to senderLogin,
                        "id" to 1L,
                        "type" to senderType,
                    ),
                    "html_url" to "https://github.com/owner/repo/pull/$prNumber",
                    "diff_url" to "https://github.com/owner/repo/pull/$prNumber.diff",
                ),
                "repository" to mapOf(
                    "id" to 999L,
                    "full_name" to repoFullName,
                    "name" to "repo",
                    "owner" to mapOf(
                        "login" to "owner",
                        "id" to 2L,
                    ),
                ),
                "installation" to mapOf(
                    "id" to installationId,
                ),
                "sender" to mapOf(
                    "login" to senderLogin,
                    "id" to 1L,
                    "type" to senderType,
                ),
            ),
        )
    }

    private fun createRegisteredRepository(
        fullName: String = "owner/repo",
        isActive: Boolean = true,
        reviewOnDraft: Boolean = false,
    ): RegisteredRepository {
        return RegisteredRepository(
            id = "repo-id-1",
            fullName = fullName,
            owner = "owner",
            name = "repo",
            installationId = 12345L,
            isActive = isActive,
            settings = RepositorySettings(reviewOnDraft = reviewOnDraft),
        )
    }

    @Nested
    inner class PrOpenedEvent {

        @Test
        fun `should process PR opened event successfully`() = runTest {
            val payload = buildPrPayload(action = "opened")
            val body = payload.toByteArray()
            val repo = createRegisteredRepository()
            val savedReview = ReviewRequest(
                id = "review-1",
                repositoryId = "repo-id-1",
                repositoryFullName = "owner/repo",
                platformPrId = 42,
                title = "Test PR",
                author = "developer",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature-branch",
                status = ReviewStatus.PENDING,
            )

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repo
            coEvery { reviewRequestRepository.save(any()) } returns savedReview
            coEvery { queueProducer.enqueue(any()) } returns Unit

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 1) { repositoryRepository.findByFullName("owner/repo") }
            coVerify(exactly = 1) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 1) {
                queueProducer.enqueue(
                    match<ReviewMessage> {
                        it.reviewRequestId == "review-1" &&
                            it.repositoryFullName == "owner/repo" &&
                            it.pullRequestNumber == 42
                    },
                )
            }
        }

        @Test
        fun `should process PR synchronize event`() = runTest {
            val payload = buildPrPayload(action = "synchronize")
            val body = payload.toByteArray()
            val repo = createRegisteredRepository()
            val savedReview = ReviewRequest(
                id = "review-2",
                repositoryId = "repo-id-1",
                repositoryFullName = "owner/repo",
                platformPrId = 42,
                title = "Test PR",
                author = "developer",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature-branch",
                status = ReviewStatus.PENDING,
            )

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repo
            coEvery { reviewRequestRepository.save(any()) } returns savedReview
            coEvery { queueProducer.enqueue(any()) } returns Unit

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 1) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 1) { queueProducer.enqueue(any()) }
        }

        @Test
        fun `should process PR reopened event`() = runTest {
            val payload = buildPrPayload(action = "reopened")
            val body = payload.toByteArray()
            val repo = createRegisteredRepository()
            val savedReview = ReviewRequest(
                id = "review-3",
                repositoryId = "repo-id-1",
                repositoryFullName = "owner/repo",
                platformPrId = 42,
                title = "Test PR",
                author = "developer",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature-branch",
                status = ReviewStatus.PENDING,
            )

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repo
            coEvery { reviewRequestRepository.save(any()) } returns savedReview
            coEvery { queueProducer.enqueue(any()) } returns Unit

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 1) { queueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class UnsupportedActions {

        @Test
        fun `should ignore PR closed action`() = runTest {
            val payload = buildPrPayload(action = "closed")
            val body = payload.toByteArray()

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 0) { repositoryRepository.findByFullName(any()) }
            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { queueProducer.enqueue(any()) }
        }

        @Test
        fun `should ignore PR labeled action`() = runTest {
            val payload = buildPrPayload(action = "labeled")
            val body = payload.toByteArray()

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 0) { repositoryRepository.findByFullName(any()) }
        }

        @Test
        fun `should ignore non-pull_request event`() = runTest {
            val body = """{"action":"completed"}""".toByteArray()

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true

            webhookService.handleWebhook("push", "valid-sig", body)

            coVerify(exactly = 0) { repositoryRepository.findByFullName(any()) }
            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
        }
    }

    @Nested
    inner class DraftPrHandling {

        @Test
        fun `should ignore draft PR when reviewOnDraft is false`() = runTest {
            val payload = buildPrPayload(action = "opened", draft = true)
            val body = payload.toByteArray()
            val repo = createRegisteredRepository(reviewOnDraft = false)

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repo

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { queueProducer.enqueue(any()) }
        }

        @Test
        fun `should process draft PR when reviewOnDraft is true`() = runTest {
            val payload = buildPrPayload(action = "opened", draft = true)
            val body = payload.toByteArray()
            val repo = createRegisteredRepository(reviewOnDraft = true)
            val savedReview = ReviewRequest(
                id = "review-draft",
                repositoryId = "repo-id-1",
                repositoryFullName = "owner/repo",
                platformPrId = 42,
                title = "Test PR",
                author = "developer",
                headSha = "abc123def456",
                baseBranch = "main",
                headBranch = "feature-branch",
                status = ReviewStatus.PENDING,
            )

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repo
            coEvery { reviewRequestRepository.save(any()) } returns savedReview
            coEvery { queueProducer.enqueue(any()) } returns Unit

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 1) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 1) { queueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class InactiveRepository {

        @Test
        fun `should ignore webhook for unregistered repository`() = runTest {
            val payload = buildPrPayload(action = "opened")
            val body = payload.toByteArray()

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns null

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { queueProducer.enqueue(any()) }
        }

        @Test
        fun `should ignore webhook for inactive repository`() = runTest {
            val payload = buildPrPayload(action = "opened")
            val body = payload.toByteArray()
            val inactiveRepo = createRegisteredRepository(isActive = false)

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns inactiveRepo

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { queueProducer.enqueue(any()) }
        }
    }

    @Nested
    inner class SignatureVerification {

        @Test
        fun `should throw ApiException for invalid signature`() = runTest {
            val body = """{"action":"opened"}""".toByteArray()

            every { signatureVerifier.verify(body, "invalid-sig", "test-secret") } returns false

            val exception = assertThrows<ApiException> {
                webhookService.handleWebhook("pull_request", "invalid-sig", body)
            }

            assertEquals(HttpStatus.UNAUTHORIZED, exception.status)
        }
    }

    @Nested
    inner class BotPrHandling {

        @Test
        fun `should skip PR from bot sender`() = runTest {
            val payload = buildPrPayload(action = "opened", senderType = "Bot", senderLogin = "dependabot[bot]")
            val body = payload.toByteArray()
            val repo = createRegisteredRepository()

            every { signatureVerifier.verify(body, "valid-sig", "test-secret") } returns true
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repo

            webhookService.handleWebhook("pull_request", "valid-sig", body)

            coVerify(exactly = 0) { reviewRequestRepository.save(any()) }
            coVerify(exactly = 0) { queueProducer.enqueue(any()) }
        }
    }
}
