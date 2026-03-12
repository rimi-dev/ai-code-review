package com.reviewer.domain.service

import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.RepositorySettings
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.GitHubApiClient
import com.reviewer.infrastructure.llm.ReviewLlmClientFactory
import com.reviewer.infrastructure.llm.ReviewPromptBuilder
import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.Instant

class ReviewServiceTest {

    private val reviewRequestRepository: ReviewRequestRepository = mockk()
    private val repositoryRepository: RegisteredRepositoryRepository = mockk()
    private val gitHubApiClient: GitHubApiClient = mockk()
    private val llmClientFactory: ReviewLlmClientFactory = mockk()
    private val promptBuilder: ReviewPromptBuilder = mockk()
    private val diffService: DiffService = mockk()
    private val responseParser: ReviewResponseParser = mockk()

    private lateinit var reviewService: ReviewService

    @BeforeEach
    fun setUp() {
        reviewService = ReviewService(
            reviewRequestRepository = reviewRequestRepository,
            repositoryRepository = repositoryRepository,
            gitHubApiClient = gitHubApiClient,
            llmClientFactory = llmClientFactory,
            promptBuilder = promptBuilder,
            diffService = diffService,
            responseParser = responseParser,
        )
    }

    private fun createReviewRequest(
        id: String = "review-1",
        repoFullName: String = "owner/repo",
        prNumber: Int = 42,
        status: ReviewStatus = ReviewStatus.PENDING,
    ): ReviewRequest {
        return ReviewRequest(
            id = id,
            repositoryId = "repo-id-1",
            repositoryFullName = repoFullName,
            platformPrId = prNumber,
            title = "Test PR",
            author = "developer",
            headSha = "abc123",
            baseBranch = "main",
            headBranch = "feature-branch",
            status = status,
            createdAt = Instant.now(),
        )
    }

    private fun createRepository(
        fullName: String = "owner/repo",
        modelPreference: String = "auto",
    ): RegisteredRepository {
        return RegisteredRepository(
            id = "repo-id-1",
            fullName = fullName,
            owner = "owner",
            name = "repo",
            installationId = 12345L,
            isActive = true,
            modelPreference = modelPreference,
            settings = RepositorySettings(language = "en"),
        )
    }

    @Nested
    inner class NormalReviewProcess {

        @Test
        fun `should process review successfully with comments`() = runTest {
            val reviewRequest = createReviewRequest()
            val repository = createRepository()
            val fileDiff = DiffService.FileDiff(
                filePath = "src/App.kt",
                hunks = listOf(
                    DiffService.DiffHunk(
                        header = "@@ -1,3 +1,4 @@",
                        newStartLine = 1,
                        lines = listOf(
                            DiffService.DiffLine("added line", DiffService.LineType.ADDED, 1),
                        ),
                    ),
                ),
                additions = 1,
                deletions = 0,
            )
            val llmResponse = ReviewLlmResponse(
                content = """[{"file":"src/App.kt","line":1,"severity":"WARNING","category":"quality","title":"Issue","body":"Description"}]""",
                model = "claude-3-opus",
                provider = "claude",
                inputTokens = 100,
                outputTokens = 50,
                totalTokens = 150,
            )
            val parsedComments = listOf(
                com.reviewer.domain.model.ReviewCommentEmbed(
                    filePath = "src/App.kt",
                    lineNumber = 1,
                    category = "quality",
                    severity = "WARNING",
                    content = "Issue\n\nDescription",
                ),
            )

            coEvery { reviewRequestRepository.findById("review-1") } returns reviewRequest
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repository
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { gitHubApiClient.getPullRequestDiff(12345L, "owner", "repo", 42) } returns "raw diff"
            coEvery { diffService.parseDiff("raw diff") } returns listOf(fileDiff)
            coEvery { diffService.buildDiffContext(fileDiff) } returns "+added line"
            coEvery { promptBuilder.buildSystemPrompt(any(), any()) } returns "system prompt"
            coEvery { promptBuilder.buildChunkedUserPrompt(any(), any(), any(), any(), any(), any()) } returns "user prompt"
            coEvery { llmClientFactory.generateReview(any(), any(), any()) } returns llmResponse
            coEvery { responseParser.parse(llmResponse.content) } returns parsedComments
            coEvery { gitHubApiClient.createPullRequestReview(any(), any(), any(), any(), any()) } returns Unit

            reviewService.processReview("review-1")

            // Verify status transitions: PENDING -> REVIEWING -> COMPLETED
            val savedSlot = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedSlot)) }

            // First save: REVIEWING
            assertEquals(ReviewStatus.REVIEWING, savedSlot[0].status)
            // Last save: COMPLETED
            assertEquals(ReviewStatus.COMPLETED, savedSlot.last().status)

            // Verify GitHub review was posted
            coVerify(exactly = 1) { gitHubApiClient.createPullRequestReview(12345L, "owner", "repo", 42, any()) }
        }

        @Test
        fun `should not post GitHub review when no comments`() = runTest {
            val reviewRequest = createReviewRequest()
            val repository = createRepository()
            val fileDiff = DiffService.FileDiff(
                filePath = "src/App.kt",
                hunks = emptyList(),
                additions = 0,
                deletions = 0,
            )
            val llmResponse = ReviewLlmResponse(
                content = "[]",
                model = "claude-3-opus",
                provider = "claude",
                inputTokens = 100,
                outputTokens = 10,
                totalTokens = 110,
            )

            coEvery { reviewRequestRepository.findById("review-1") } returns reviewRequest
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repository
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { gitHubApiClient.getPullRequestDiff(12345L, "owner", "repo", 42) } returns "raw diff"
            coEvery { diffService.parseDiff("raw diff") } returns listOf(fileDiff)
            coEvery { diffService.buildDiffContext(fileDiff) } returns ""
            coEvery { promptBuilder.buildSystemPrompt(any(), any()) } returns "system prompt"
            coEvery { promptBuilder.buildChunkedUserPrompt(any(), any(), any(), any(), any(), any()) } returns "user prompt"
            coEvery { llmClientFactory.generateReview(any(), any(), any()) } returns llmResponse
            coEvery { responseParser.parse(llmResponse.content) } returns emptyList()

            reviewService.processReview("review-1")

            coVerify(exactly = 0) { gitHubApiClient.createPullRequestReview(any(), any(), any(), any(), any()) }
        }
    }

    @Nested
    inner class EmptyDiff {

        @Test
        fun `should mark as completed when no reviewable files`() = runTest {
            val reviewRequest = createReviewRequest()
            val repository = createRepository()

            coEvery { reviewRequestRepository.findById("review-1") } returns reviewRequest
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repository
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { gitHubApiClient.getPullRequestDiff(12345L, "owner", "repo", 42) } returns "empty diff"
            coEvery { diffService.parseDiff("empty diff") } returns emptyList()

            reviewService.processReview("review-1")

            val savedSlot = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedSlot)) }

            // Should transition to COMPLETED (skipped)
            assertEquals(ReviewStatus.COMPLETED, savedSlot.last().status)

            // Should NOT call LLM or GitHub
            coVerify(exactly = 0) { llmClientFactory.generateReview(any(), any(), any()) }
            coVerify(exactly = 0) { gitHubApiClient.createPullRequestReview(any(), any(), any(), any(), any()) }
        }
    }

    @Nested
    inner class LlmCallFailure {

        @Test
        fun `should mark as FAILED when LLM call fails`() = runTest {
            val reviewRequest = createReviewRequest()
            val repository = createRepository()
            val fileDiff = DiffService.FileDiff(
                filePath = "src/App.kt",
                hunks = listOf(
                    DiffService.DiffHunk(
                        header = "@@ -1,3 +1,4 @@",
                        newStartLine = 1,
                        lines = listOf(
                            DiffService.DiffLine("added line", DiffService.LineType.ADDED, 1),
                        ),
                    ),
                ),
                additions = 1,
                deletions = 0,
            )

            coEvery { reviewRequestRepository.findById("review-1") } returns reviewRequest
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repository
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { gitHubApiClient.getPullRequestDiff(12345L, "owner", "repo", 42) } returns "raw diff"
            coEvery { diffService.parseDiff("raw diff") } returns listOf(fileDiff)
            coEvery { diffService.buildDiffContext(fileDiff) } returns "+added line"
            coEvery { promptBuilder.buildSystemPrompt(any(), any()) } returns "system prompt"
            coEvery { promptBuilder.buildChunkedUserPrompt(any(), any(), any(), any(), any(), any()) } returns "user prompt"
            coEvery { llmClientFactory.generateReview(any(), any(), any()) } throws RuntimeException("LLM API Error")

            assertThrows<RuntimeException> {
                reviewService.processReview("review-1")
            }

            val savedSlot = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedSlot)) }

            // Last save should be FAILED
            assertEquals(ReviewStatus.FAILED, savedSlot.last().status)
        }

        @Test
        fun `should mark as FAILED when GitHub API fails`() = runTest {
            val reviewRequest = createReviewRequest()
            val repository = createRepository()
            val fileDiff = DiffService.FileDiff(
                filePath = "src/App.kt",
                hunks = listOf(
                    DiffService.DiffHunk(
                        header = "@@ -1,3 +1,4 @@",
                        newStartLine = 1,
                        lines = listOf(
                            DiffService.DiffLine("added", DiffService.LineType.ADDED, 1),
                        ),
                    ),
                ),
                additions = 1,
                deletions = 0,
            )
            val llmResponse = ReviewLlmResponse(
                content = "[]",
                model = "claude-3-opus",
                provider = "claude",
                inputTokens = 100,
                outputTokens = 50,
            )
            val parsedComments = listOf(
                com.reviewer.domain.model.ReviewCommentEmbed(
                    filePath = "src/App.kt",
                    lineNumber = 1,
                    category = "quality",
                    severity = "WARNING",
                    content = "Issue\n\nDescription",
                ),
            )

            coEvery { reviewRequestRepository.findById("review-1") } returns reviewRequest
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns repository
            coEvery { reviewRequestRepository.save(any()) } answers { firstArg() }
            coEvery { gitHubApiClient.getPullRequestDiff(12345L, "owner", "repo", 42) } returns "raw diff"
            coEvery { diffService.parseDiff("raw diff") } returns listOf(fileDiff)
            coEvery { diffService.buildDiffContext(fileDiff) } returns "+added"
            coEvery { promptBuilder.buildSystemPrompt(any(), any()) } returns "system prompt"
            coEvery { promptBuilder.buildChunkedUserPrompt(any(), any(), any(), any(), any(), any()) } returns "user prompt"
            coEvery { llmClientFactory.generateReview(any(), any(), any()) } returns llmResponse
            coEvery { responseParser.parse(llmResponse.content) } returns parsedComments
            coEvery {
                gitHubApiClient.createPullRequestReview(any(), any(), any(), any(), any())
            } throws RuntimeException("GitHub API Error")

            assertThrows<RuntimeException> {
                reviewService.processReview("review-1")
            }

            val savedSlot = mutableListOf<ReviewRequest>()
            coVerify(atLeast = 2) { reviewRequestRepository.save(capture(savedSlot)) }
            assertEquals(ReviewStatus.FAILED, savedSlot.last().status)
        }
    }

    @Nested
    inner class ReviewRequestNotFound {

        @Test
        fun `should throw when review request not found`() = runTest {
            coEvery { reviewRequestRepository.findById("nonexistent") } returns null

            assertThrows<RuntimeException> {
                reviewService.processReview("nonexistent")
            }
        }

        @Test
        fun `should throw when repository not found`() = runTest {
            val reviewRequest = createReviewRequest()

            coEvery { reviewRequestRepository.findById("review-1") } returns reviewRequest
            coEvery { repositoryRepository.findByFullName("owner/repo") } returns null

            assertThrows<RuntimeException> {
                reviewService.processReview("review-1")
            }
        }
    }
}
