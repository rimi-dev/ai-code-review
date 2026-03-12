package com.reviewer.domain.service

import com.reviewer.domain.model.ReviewCommentEmbed
import com.reviewer.domain.model.ReviewResult
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.model.TokenUsage
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.GitHubApiClient
import com.reviewer.infrastructure.git.dto.GitHubCreateReviewRequest
import com.reviewer.infrastructure.git.dto.GitHubReviewComment
import com.reviewer.infrastructure.llm.ReviewLlmClientFactory
import com.reviewer.infrastructure.llm.ReviewPromptBuilder
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.stereotype.Service
import java.time.Instant

private val logger = KotlinLogging.logger {}

@Service
class ReviewService(
    private val reviewRequestRepository: ReviewRequestRepository,
    private val repositoryRepository: RegisteredRepositoryRepository,
    private val gitHubApiClient: GitHubApiClient,
    private val llmClientFactory: ReviewLlmClientFactory,
    private val promptBuilder: ReviewPromptBuilder,
    private val diffService: DiffService,
    private val responseParser: ReviewResponseParser,
) {
    suspend fun processReview(reviewRequestId: String) {
        val reviewRequest = reviewRequestRepository.findById(reviewRequestId)
            ?: throw RuntimeException("ReviewRequest not found: $reviewRequestId")

        val repository = repositoryRepository.findByFullName(reviewRequest.repositoryFullName)
            ?: throw RuntimeException("Repository not found: ${reviewRequest.repositoryFullName}")

        val processing = reviewRequest.copy(status = ReviewStatus.REVIEWING, updatedAt = Instant.now())
        reviewRequestRepository.save(processing)

        val startTime = System.currentTimeMillis()

        try {
            val (owner, repo) = reviewRequest.repositoryFullName.split("/")

            // 1. PR diff 가져오기
            val rawDiff = gitHubApiClient.getPullRequestDiff(
                repository.installationId, owner, repo, reviewRequest.platformPrId,
            )

            // 2. Diff 파싱 + 필터링
            val fileDiffs = diffService.parseDiff(rawDiff)
            if (fileDiffs.isEmpty()) {
                val skipped = processing.copy(
                    status = ReviewStatus.COMPLETED,
                    updatedAt = Instant.now(),
                )
                reviewRequestRepository.save(skipped)
                logger.info { "No reviewable files for PR #${reviewRequest.platformPrId}" }
                return
            }

            // 3. 프롬프트 생성 + LLM 호출
            val systemPrompt = promptBuilder.buildSystemPrompt(
                language = repository.settings.language,
                customPrompt = repository.settings.customPrompt,
            )

            val allComments = mutableListOf<ReviewCommentEmbed>()
            var totalInputTokens = 0
            var totalOutputTokens = 0
            var usedProvider = ""
            var usedModel = ""
            var fallbackUsed = false

            for ((index, fileDiff) in fileDiffs.withIndex()) {
                val diffContext = diffService.buildDiffContext(fileDiff)
                val userPrompt = promptBuilder.buildChunkedUserPrompt(
                    prTitle = reviewRequest.title,
                    prBody = null,
                    file = fileDiff.filePath,
                    patch = diffContext,
                    chunkIndex = index + 1,
                    totalChunks = fileDiffs.size,
                )

                val llmResponse = llmClientFactory.generateReview(
                    systemPrompt = systemPrompt,
                    userPrompt = userPrompt,
                    preferredProvider = repository.modelPreference,
                )

                usedProvider = llmResponse.provider
                usedModel = llmResponse.model
                totalInputTokens += llmResponse.inputTokens
                totalOutputTokens += llmResponse.outputTokens
                if ("fallback" in llmResponse.provider) fallbackUsed = true

                val comments = responseParser.parse(llmResponse.content)
                allComments.addAll(comments)
            }

            // 4. GitHub에 코멘트 작성
            if (allComments.isNotEmpty()) {
                postReviewToGitHub(
                    repository, reviewRequest, allComments, owner, repo,
                )
            }

            // 5. ReviewResult 저장
            val latencyMs = System.currentTimeMillis() - startTime
            val reviewResult = ReviewResult(
                model = usedModel,
                provider = usedProvider,
                summary = buildSummary(allComments),
                comments = allComments,
                tokenUsage = TokenUsage(totalInputTokens, totalOutputTokens),
                latencyMs = latencyMs,
                fallbackUsed = fallbackUsed,
            )

            val completed = processing.copy(
                status = ReviewStatus.COMPLETED,
                reviews = processing.reviews + reviewResult,
                updatedAt = Instant.now(),
            )
            reviewRequestRepository.save(completed)

            logger.info {
                "Review completed for ${reviewRequest.repositoryFullName}#${reviewRequest.platformPrId}: " +
                    "${allComments.size} comments, ${latencyMs}ms, provider=$usedProvider"
            }
        } catch (e: Exception) {
            logger.error(e) { "Review failed for ${reviewRequest.repositoryFullName}#${reviewRequest.platformPrId}" }
            val failed = processing.copy(
                status = ReviewStatus.FAILED,
                updatedAt = Instant.now(),
            )
            reviewRequestRepository.save(failed)
            throw e
        }
    }

    private suspend fun postReviewToGitHub(
        repository: com.reviewer.domain.model.RegisteredRepository,
        reviewRequest: com.reviewer.domain.model.ReviewRequest,
        comments: List<ReviewCommentEmbed>,
        owner: String,
        repo: String,
    ) {
        val inlineComments = comments
            .filter { it.lineNumber > 0 }
            .map { comment ->
                GitHubReviewComment(
                    path = comment.filePath,
                    line = comment.lineNumber,
                    body = formatComment(comment),
                )
            }

        val summaryBody = buildSummary(comments)

        val review = GitHubCreateReviewRequest(
            body = summaryBody,
            event = "COMMENT",
            comments = inlineComments,
        )

        gitHubApiClient.createPullRequestReview(
            repository.installationId, owner, repo, reviewRequest.platformPrId, review,
        )
    }

    private fun buildSummary(comments: List<ReviewCommentEmbed>): String {
        val criticalCount = comments.count { it.severity == "CRITICAL" }
        val warningCount = comments.count { it.severity == "WARNING" }
        val suggestionCount = comments.count { it.severity == "SUGGESTION" }

        return buildString {
            appendLine("**AI Code Review**")
            appendLine()
            appendLine("### Summary")
            appendLine(
                "Found **${comments.size} issues** " +
                    "($criticalCount Critical, $warningCount Warning, $suggestionCount Suggestion)",
            )
            appendLine()
            if (comments.isNotEmpty()) {
                appendLine("### Issues")
                comments.take(10).forEach { comment ->
                    val icon = when (comment.severity) {
                        "CRITICAL" -> "[CRITICAL]"
                        "WARNING" -> "[WARNING]"
                        "PRAISE" -> "[PRAISE]"
                        else -> "[SUGGESTION]"
                    }
                    appendLine(
                        "$icon **[${comment.category.uppercase()}]** " +
                            "`${comment.filePath}:${comment.lineNumber}` - ${comment.content.lines().first()}",
                    )
                }
            }
        }
    }

    private fun formatComment(comment: ReviewCommentEmbed): String {
        val icon = when (comment.severity) {
            "CRITICAL" -> "[CRITICAL]"
            "WARNING" -> "[WARNING]"
            "PRAISE" -> "[PRAISE]"
            else -> "[SUGGESTION]"
        }
        return buildString {
            appendLine("$icon **[${comment.category.uppercase()}]** ${comment.content}")
            if (comment.suggestion != null) {
                appendLine()
                appendLine("```suggestion")
                appendLine(comment.suggestion)
                appendLine("```")
            }
        }
    }
}
