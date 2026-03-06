package com.reviewer.domain.service

import com.reviewer.config.properties.LlmProperties
import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.ReviewComment
import com.reviewer.domain.model.ReviewConfig
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.model.Severity
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewCommentRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.GitHubApiClient
import com.reviewer.infrastructure.git.dto.CreateReviewResponse
import com.reviewer.infrastructure.git.dto.PrFile
import com.reviewer.infrastructure.llm.ReviewLlmClientFactory
import com.reviewer.infrastructure.llm.ReviewPromptBuilder
import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import com.reviewer.infrastructure.metrics.ReviewMetrics
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test

class ReviewServiceTest {

    private val reviewRequestRepository: ReviewRequestRepository = mockk()
    private val reviewCommentRepository: ReviewCommentRepository = mockk()
    private val registeredRepositoryRepository: RegisteredRepositoryRepository = mockk()
    private val gitHubApiClient: GitHubApiClient = mockk()
    private val diffService: DiffService = mockk()
    private val reviewPromptBuilder: ReviewPromptBuilder = mockk()
    private val reviewLlmClientFactory: ReviewLlmClientFactory = mockk()
    private val reviewResponseParser: ReviewResponseParser = mockk()
    private val reviewMetrics: ReviewMetrics = mockk(relaxed = true)

    private val llmProperties = LlmProperties(
        maxTokens = 4096,
    )

    private lateinit var reviewService: ReviewService

    @BeforeEach
    fun setUp() {
        reviewService = ReviewService(
            reviewRequestRepository = reviewRequestRepository,
            reviewCommentRepository = reviewCommentRepository,
            registeredRepositoryRepository = registeredRepositoryRepository,
            gitHubApiClient = gitHubApiClient,
            diffService = diffService,
            reviewPromptBuilder = reviewPromptBuilder,
            reviewLlmClientFactory = reviewLlmClientFactory,
            reviewResponseParser = reviewResponseParser,
            reviewMetrics = reviewMetrics,
            llmProperties = llmProperties,
        )
    }

    private fun buildReviewRequest(
        id: String = "req-123",
        repoFullName: String = "owner/repo",
        prNumber: Int = 1,
        status: ReviewStatus = ReviewStatus.QUEUED,
    ) = ReviewRequest(
        id = id,
        repositoryFullName = repoFullName,
        pullRequestNumber = prNumber,
        pullRequestTitle = "Test PR",
        pullRequestUrl = "https://github.com/$repoFullName/pull/$prNumber",
        headSha = "abc123",
        baseBranch = "main",
        headBranch = "feature/test",
        authorLogin = "developer",
        installationId = 12345L,
        status = status,
    )

    private fun buildRegisteredRepo(
        fullName: String = "owner/repo",
        excludePatterns: List<String> = emptyList(),
    ) = RegisteredRepository(
        id = "repo-1",
        fullName = fullName,
        owner = fullName.split("/").first(),
        name = fullName.split("/").last(),
        installationId = 12345L,
        enabled = true,
        reviewConfig = ReviewConfig(
            excludePatterns = excludePatterns,
        ),
    )

    private fun buildPrFile(
        filename: String = "src/Main.kt",
        additions: Int = 10,
        deletions: Int = 5,
    ) = PrFile(
        sha = "file-sha",
        filename = filename,
        status = "modified",
        additions = additions,
        deletions = deletions,
        changes = additions + deletions,
    )

    private fun buildReviewComment(
        id: String? = "comment-1",
        filePath: String = "src/Main.kt",
        line: Int? = 10,
    ) = ReviewComment(
        id = id,
        reviewRequestId = "req-123",
        repositoryFullName = "owner/repo",
        pullRequestNumber = 1,
        filePath = filePath,
        line = line,
        severity = Severity.WARNING,
        category = "quality",
        title = "Test issue",
        body = "This is a test issue",
        suggestion = "Fix it",
    )

    @Nested
    inner class SuccessfulReviewFlow {

        @Test
        fun `should complete full review flow - fetch diff, parse, LLM, post comments`() = runTest {
            val reviewRequest = buildReviewRequest()
            val registeredRepo = buildRegisteredRepo()
            val prFiles = listOf(buildPrFile("src/Main.kt"), buildPrFile("src/Service.kt"))
            val filteredFiles = prFiles
            val rawDiff = "diff --git a/src/Main.kt b/src/Main.kt\n..."
            val filteredDiff = rawDiff
            val parsedDiff = DiffService.ParsedDiff(
                files = listOf(
                    DiffService.DiffFile("src/Main.kt", emptyList(), 10, 5),
                    DiffService.DiffFile("src/Service.kt", emptyList(), 8, 3),
                ),
                totalLines = 26,
                truncated = false,
            )
            val llmResponse = ReviewLlmResponse(
                content = "[{\"file\":\"src/Main.kt\",\"line\":10,\"severity\":\"WARNING\",\"category\":\"quality\",\"title\":\"Test\",\"body\":\"Issue\"}]",
                model = "vllm-model",
                provider = "vllm",
                inputTokens = 1000,
                outputTokens = 200,
                totalTokens = 1200,
            )
            val reviewComments = listOf(buildReviewComment())
            val savedComment = buildReviewComment(id = "comment-saved-1")

            // Stub all calls in the flow
            coEvery { reviewRequestRepository.findById("req-123") } returns reviewRequest
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { gitHubApiClient.getPrFiles("owner", "repo", 1, 12345L) } returns prFiles
            coEvery { diffService.filterFiles(prFiles, emptyList()) } returns filteredFiles
            coEvery { gitHubApiClient.getPrDiff("owner", "repo", 1, 12345L) } returns rawDiff
            coEvery { diffService.buildFilteredDiff(rawDiff, setOf("src/Main.kt", "src/Service.kt")) } returns filteredDiff
            coEvery { diffService.parseDiff(filteredDiff) } returns parsedDiff
            coEvery { reviewPromptBuilder.buildSystemPrompt("en", null) } returns "system prompt"
            coEvery { reviewPromptBuilder.buildUserPrompt("Test PR", null, filteredFiles, filteredDiff) } returns "user prompt"
            coEvery { reviewLlmClientFactory.generateReview("system prompt", "user prompt", 4096) } returns llmResponse
            coEvery {
                reviewResponseParser.parse(
                    llmResponse = llmResponse.content,
                    reviewRequestId = "req-123",
                    repositoryFullName = "owner/repo",
                    pullRequestNumber = 1,
                )
            } returns reviewComments
            coEvery { reviewCommentRepository.save(any()) } returns savedComment
            coEvery { gitHubApiClient.createPrReview(any(), any(), any(), any(), any()) } returns CreateReviewResponse(
                id = 1L,
                body = "review",
                state = "COMMENTED",
            )

            reviewService.processReview("req-123")

            // Verify the review request transitions: QUEUED -> PROCESSING -> COMPLETED
            val savedRequestSlots = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedRequestSlots)) }

            // First save should be PROCESSING
            assertEquals(ReviewStatus.PROCESSING, savedRequestSlots[0].status)

            // Last save should be COMPLETED
            val completedRequest = savedRequestSlots.last()
            assertEquals(ReviewStatus.COMPLETED, completedRequest.status)
            assertEquals(2, completedRequest.totalFiles)
            assertEquals(26, completedRequest.totalLines)
            assertEquals("vllm", completedRequest.llmProvider)
            assertEquals(1200, completedRequest.llmTokensUsed)

            // Verify metrics
            coVerify(exactly = 1) { reviewMetrics.incrementReviewCompleted() }
            coVerify(exactly = 1) { reviewMetrics.recordLlmCallTime(any()) }
            coVerify(exactly = 1) { reviewMetrics.recordProcessingTime(any()) }
        }
    }

    @Nested
    inner class LlmFailure {

        @Test
        fun `should mark review as FAILED when LLM throws exception`() = runTest {
            val reviewRequest = buildReviewRequest()
            val registeredRepo = buildRegisteredRepo()
            val prFiles = listOf(buildPrFile())
            val filteredFiles = prFiles
            val rawDiff = "diff --git a/src/Main.kt b/src/Main.kt\n..."
            val parsedDiff = DiffService.ParsedDiff(
                files = listOf(DiffService.DiffFile("src/Main.kt", emptyList(), 10, 5)),
                totalLines = 15,
            )

            coEvery { reviewRequestRepository.findById("req-123") } returns reviewRequest
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { gitHubApiClient.getPrFiles("owner", "repo", 1, 12345L) } returns prFiles
            coEvery { diffService.filterFiles(prFiles, emptyList()) } returns filteredFiles
            coEvery { gitHubApiClient.getPrDiff("owner", "repo", 1, 12345L) } returns rawDiff
            coEvery { diffService.buildFilteredDiff(rawDiff, setOf("src/Main.kt")) } returns rawDiff
            coEvery { diffService.parseDiff(rawDiff) } returns parsedDiff
            coEvery { reviewPromptBuilder.buildSystemPrompt(any(), any()) } returns "system prompt"
            coEvery { reviewPromptBuilder.buildUserPrompt(any(), any(), any(), any()) } returns "user prompt"
            coEvery { reviewLlmClientFactory.generateReview(any(), any(), any()) } throws RuntimeException("LLM service unavailable")

            reviewService.processReview("req-123")

            val savedRequests = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedRequests)) }

            val failedRequest = savedRequests.last()
            assertEquals(ReviewStatus.FAILED, failedRequest.status)
            assertEquals("LLM service unavailable", failedRequest.errorMessage)

            coVerify(exactly = 1) { reviewMetrics.incrementReviewFailed() }
        }
    }

    @Nested
    inner class EmptyDiff {

        @Test
        fun `should mark review as SKIPPED when no reviewable files after filtering`() = runTest {
            val reviewRequest = buildReviewRequest()
            val registeredRepo = buildRegisteredRepo(
                excludePatterns = listOf("*.kt"),
            )
            val prFiles = listOf(buildPrFile("src/Main.kt"))

            coEvery { reviewRequestRepository.findById("req-123") } returns reviewRequest
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { gitHubApiClient.getPrFiles("owner", "repo", 1, 12345L) } returns prFiles
            coEvery { diffService.filterFiles(prFiles, listOf("*.kt")) } returns emptyList()

            reviewService.processReview("req-123")

            val savedRequests = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedRequests)) }

            val skippedRequest = savedRequests.last()
            assertEquals(ReviewStatus.SKIPPED, skippedRequest.status)
            assertEquals("No reviewable files after filtering", skippedRequest.skipReason)

            coVerify(exactly = 1) { reviewMetrics.incrementReviewSkipped() }

            // Should NOT call LLM or GitHub review APIs
            coVerify(exactly = 0) { reviewLlmClientFactory.generateReview(any(), any(), any()) }
            coVerify(exactly = 0) { gitHubApiClient.getPrDiff(any(), any(), any(), any()) }
        }
    }

    @Nested
    inner class FallbackBehavior {

        @Test
        fun `should use fallback provider response when vLLM fails and Claude succeeds`() = runTest {
            val reviewRequest = buildReviewRequest()
            val registeredRepo = buildRegisteredRepo()
            val prFiles = listOf(buildPrFile())
            val filteredFiles = prFiles
            val rawDiff = "diff --git a/src/Main.kt b/src/Main.kt\n..."
            val parsedDiff = DiffService.ParsedDiff(
                files = listOf(DiffService.DiffFile("src/Main.kt", emptyList(), 10, 5)),
                totalLines = 15,
            )
            // The factory handles fallback internally, so from ReviewService's perspective
            // it just gets a response with provider="claude"
            val claudeResponse = ReviewLlmResponse(
                content = "[]",
                model = "claude-sonnet-4-20250514",
                provider = "claude",
                inputTokens = 500,
                outputTokens = 50,
                totalTokens = 550,
            )

            coEvery { reviewRequestRepository.findById("req-123") } returns reviewRequest
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { gitHubApiClient.getPrFiles("owner", "repo", 1, 12345L) } returns prFiles
            coEvery { diffService.filterFiles(prFiles, emptyList()) } returns filteredFiles
            coEvery { gitHubApiClient.getPrDiff("owner", "repo", 1, 12345L) } returns rawDiff
            coEvery { diffService.buildFilteredDiff(rawDiff, setOf("src/Main.kt")) } returns rawDiff
            coEvery { diffService.parseDiff(rawDiff) } returns parsedDiff
            coEvery { reviewPromptBuilder.buildSystemPrompt(any(), any()) } returns "system prompt"
            coEvery { reviewPromptBuilder.buildUserPrompt(any(), any(), any(), any()) } returns "user prompt"
            coEvery { reviewLlmClientFactory.generateReview(any(), any(), any()) } returns claudeResponse
            coEvery {
                reviewResponseParser.parse(
                    llmResponse = claudeResponse.content,
                    reviewRequestId = "req-123",
                    repositoryFullName = "owner/repo",
                    pullRequestNumber = 1,
                )
            } returns emptyList()

            reviewService.processReview("req-123")

            val savedRequests = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedRequests)) }

            val completedRequest = savedRequests.last()
            assertEquals(ReviewStatus.COMPLETED, completedRequest.status)
            assertEquals("claude", completedRequest.llmProvider)
            assertEquals("claude-sonnet-4-20250514", completedRequest.llmModel)
            assertEquals(550, completedRequest.llmTokensUsed)
        }
    }

    @Nested
    inner class MetricsRecording {

        @Test
        fun `should record all metrics during successful review`() = runTest {
            val reviewRequest = buildReviewRequest()
            val registeredRepo = buildRegisteredRepo()
            val prFiles = listOf(buildPrFile())
            val rawDiff = "diff --git a/src/Main.kt b/src/Main.kt\n..."
            val parsedDiff = DiffService.ParsedDiff(
                files = listOf(DiffService.DiffFile("src/Main.kt", emptyList(), 10, 5)),
                totalLines = 15,
            )
            val llmResponse = ReviewLlmResponse(
                content = "[]",
                model = "vllm-model",
                provider = "vllm",
                totalTokens = 100,
            )

            coEvery { reviewRequestRepository.findById("req-123") } returns reviewRequest
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { gitHubApiClient.getPrFiles("owner", "repo", 1, 12345L) } returns prFiles
            coEvery { diffService.filterFiles(prFiles, emptyList()) } returns prFiles
            coEvery { gitHubApiClient.getPrDiff("owner", "repo", 1, 12345L) } returns rawDiff
            coEvery { diffService.buildFilteredDiff(rawDiff, setOf("src/Main.kt")) } returns rawDiff
            coEvery { diffService.parseDiff(rawDiff) } returns parsedDiff
            coEvery { reviewPromptBuilder.buildSystemPrompt(any(), any()) } returns "sys"
            coEvery { reviewPromptBuilder.buildUserPrompt(any(), any(), any(), any()) } returns "usr"
            coEvery { reviewLlmClientFactory.generateReview(any(), any(), any()) } returns llmResponse
            coEvery {
                reviewResponseParser.parse(any(), any(), any(), any())
            } returns emptyList()

            reviewService.processReview("req-123")

            coVerify(exactly = 1) { reviewMetrics.recordLlmCallTime(any()) }
            coVerify(exactly = 1) { reviewMetrics.incrementReviewCompleted() }
            coVerify(exactly = 1) { reviewMetrics.recordProcessingTime(any()) }
        }

        @Test
        fun `should record comments posted metric when comments exist`() = runTest {
            val reviewRequest = buildReviewRequest()
            val registeredRepo = buildRegisteredRepo()
            val prFiles = listOf(buildPrFile())
            val rawDiff = "diff --git a/src/Main.kt b/src/Main.kt\n..."
            val parsedDiff = DiffService.ParsedDiff(
                files = listOf(DiffService.DiffFile("src/Main.kt", emptyList(), 10, 5)),
                totalLines = 15,
            )
            val llmResponse = ReviewLlmResponse(
                content = "response with comments",
                model = "vllm-model",
                provider = "vllm",
                totalTokens = 200,
            )
            val comments = listOf(
                buildReviewComment(id = null, filePath = "src/Main.kt", line = 10),
                buildReviewComment(id = null, filePath = "src/Main.kt", line = 20),
            )
            val savedComments = listOf(
                buildReviewComment(id = "c-1", filePath = "src/Main.kt", line = 10),
                buildReviewComment(id = "c-2", filePath = "src/Main.kt", line = 20),
            )

            coEvery { reviewRequestRepository.findById("req-123") } returns reviewRequest
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { gitHubApiClient.getPrFiles("owner", "repo", 1, 12345L) } returns prFiles
            coEvery { diffService.filterFiles(prFiles, emptyList()) } returns prFiles
            coEvery { gitHubApiClient.getPrDiff("owner", "repo", 1, 12345L) } returns rawDiff
            coEvery { diffService.buildFilteredDiff(rawDiff, setOf("src/Main.kt")) } returns rawDiff
            coEvery { diffService.parseDiff(rawDiff) } returns parsedDiff
            coEvery { reviewPromptBuilder.buildSystemPrompt(any(), any()) } returns "sys"
            coEvery { reviewPromptBuilder.buildUserPrompt(any(), any(), any(), any()) } returns "usr"
            coEvery { reviewLlmClientFactory.generateReview(any(), any(), any()) } returns llmResponse
            coEvery { reviewResponseParser.parse(any(), any(), any(), any()) } returns comments
            coEvery { reviewCommentRepository.save(any()) } returnsMany savedComments
            coEvery { gitHubApiClient.createPrReview(any(), any(), any(), any(), any()) } returns CreateReviewResponse(
                id = 1L,
                state = "COMMENTED",
            )

            reviewService.processReview("req-123")

            coVerify(exactly = 1) { reviewMetrics.incrementCommentsPosted(2) }
            coVerify(exactly = 1) { reviewMetrics.incrementReviewCompleted() }
        }
    }

    @Nested
    inner class ReviewNotFound {

        @Test
        fun `should throw exception when review request is not found`() = runTest {
            coEvery { reviewRequestRepository.findById("nonexistent") } returns null

            try {
                reviewService.processReview("nonexistent")
                throw AssertionError("Expected ApiException to be thrown")
            } catch (e: Exception) {
                assertEquals("Review request not found: nonexistent", e.message)
            }
        }
    }

    @Nested
    inner class GitHubPostFailure {

        @Test
        fun `should complete review even if GitHub posting fails`() = runTest {
            val reviewRequest = buildReviewRequest()
            val registeredRepo = buildRegisteredRepo()
            val prFiles = listOf(buildPrFile())
            val rawDiff = "diff --git a/src/Main.kt b/src/Main.kt\n..."
            val parsedDiff = DiffService.ParsedDiff(
                files = listOf(DiffService.DiffFile("src/Main.kt", emptyList(), 10, 5)),
                totalLines = 15,
            )
            val llmResponse = ReviewLlmResponse(
                content = "response",
                model = "vllm-model",
                provider = "vllm",
                totalTokens = 100,
            )
            val comment = buildReviewComment(id = null)
            val savedComment = buildReviewComment(id = "c-1")

            coEvery { reviewRequestRepository.findById("req-123") } returns reviewRequest
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { registeredRepositoryRepository.findByFullName("owner/repo") } returns registeredRepo
            coEvery { gitHubApiClient.getPrFiles("owner", "repo", 1, 12345L) } returns prFiles
            coEvery { diffService.filterFiles(prFiles, emptyList()) } returns prFiles
            coEvery { gitHubApiClient.getPrDiff("owner", "repo", 1, 12345L) } returns rawDiff
            coEvery { diffService.buildFilteredDiff(rawDiff, setOf("src/Main.kt")) } returns rawDiff
            coEvery { diffService.parseDiff(rawDiff) } returns parsedDiff
            coEvery { reviewPromptBuilder.buildSystemPrompt(any(), any()) } returns "sys"
            coEvery { reviewPromptBuilder.buildUserPrompt(any(), any(), any(), any()) } returns "usr"
            coEvery { reviewLlmClientFactory.generateReview(any(), any(), any()) } returns llmResponse
            coEvery { reviewResponseParser.parse(any(), any(), any(), any()) } returns listOf(comment)
            coEvery { reviewCommentRepository.save(any()) } returns savedComment
            coEvery { gitHubApiClient.createPrReview(any(), any(), any(), any(), any()) } throws RuntimeException("GitHub API error")

            reviewService.processReview("req-123")

            // Even though GitHub posting fails, the review should still be COMPLETED
            val savedRequests = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedRequests)) }

            val completedRequest = savedRequests.last()
            assertEquals(ReviewStatus.COMPLETED, completedRequest.status)
            coVerify(exactly = 1) { reviewMetrics.incrementReviewCompleted() }
        }
    }
}
