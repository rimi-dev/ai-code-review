package com.reviewer.domain.service

import com.reviewer.api.exception.ApiException
import com.reviewer.config.properties.LlmProperties
import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import com.reviewer.domain.repository.ReviewCommentRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.git.GitHubApiClient
import com.reviewer.infrastructure.git.dto.CreateReviewCommentItem
import com.reviewer.infrastructure.git.dto.CreateReviewRequest
import com.reviewer.infrastructure.llm.ReviewLlmClientFactory
import com.reviewer.infrastructure.llm.ReviewPromptBuilder
import com.reviewer.infrastructure.metrics.ReviewMetrics
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import kotlin.system.measureTimeMillis

private val logger = KotlinLogging.logger {}

@Service
class ReviewService(
    private val reviewRequestRepository: ReviewRequestRepository,
    private val reviewCommentRepository: ReviewCommentRepository,
    private val registeredRepositoryRepository: RegisteredRepositoryRepository,
    private val gitHubApiClient: GitHubApiClient,
    private val diffService: DiffService,
    private val reviewPromptBuilder: ReviewPromptBuilder,
    private val reviewLlmClientFactory: ReviewLlmClientFactory,
    private val reviewResponseParser: ReviewResponseParser,
    private val reviewMetrics: ReviewMetrics,
    private val llmProperties: LlmProperties,
) {

    suspend fun processReview(reviewRequestId: String) {
        val reviewRequest = reviewRequestRepository.findById(reviewRequestId)
            ?: throw ApiException(
                status = HttpStatus.NOT_FOUND,
                message = "Review request not found: $reviewRequestId",
                errorCode = "review_not_found",
            )

        // Mark as processing
        val processingRequest = reviewRequest.copy(status = ReviewStatus.PROCESSING)
        reviewRequestRepository.save(processingRequest)

        val startTime = System.currentTimeMillis()

        try {
            val registeredRepo = registeredRepositoryRepository.findByFullName(reviewRequest.repositoryFullName)
            val reviewConfig = registeredRepo?.reviewConfig

            val (owner, repo) = reviewRequest.repositoryFullName.split("/", limit = 2)

            // 1. Fetch PR files
            val prFiles = gitHubApiClient.getPrFiles(
                owner = owner,
                repo = repo,
                prNumber = reviewRequest.pullRequestNumber,
                installationId = reviewRequest.installationId,
            )

            // 2. Filter files
            val filteredFiles = diffService.filterFiles(
                files = prFiles,
                excludePatterns = reviewConfig?.excludePatterns ?: emptyList(),
            )

            if (filteredFiles.isEmpty()) {
                val skippedRequest = processingRequest.copy(
                    status = ReviewStatus.SKIPPED,
                    skipReason = "No reviewable files after filtering",
                    processingTimeMs = System.currentTimeMillis() - startTime,
                )
                reviewRequestRepository.save(skippedRequest)
                reviewMetrics.incrementReviewSkipped()
                logger.info { "Review skipped (no reviewable files): $reviewRequestId" }
                return
            }

            // 3. Fetch diff
            val rawDiff = gitHubApiClient.getPrDiff(
                owner = owner,
                repo = repo,
                prNumber = reviewRequest.pullRequestNumber,
                installationId = reviewRequest.installationId,
            )

            // 4. Build filtered diff
            val allowedFiles = filteredFiles.map { it.filename }.toSet()
            val filteredDiff = diffService.buildFilteredDiff(rawDiff, allowedFiles)
            val parsedDiff = diffService.parseDiff(filteredDiff)

            // 5. Build prompts
            val systemPrompt = reviewPromptBuilder.buildSystemPrompt(
                language = reviewConfig?.language ?: "en",
                customPrompt = reviewConfig?.customPrompt,
            )
            val userPrompt = reviewPromptBuilder.buildUserPrompt(
                prTitle = reviewRequest.pullRequestTitle,
                prBody = null,
                files = filteredFiles,
                diffContent = filteredDiff,
            )

            // 6. Call LLM
            var llmCallDuration: Long
            val llmResponse = run {
                var result: com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
                llmCallDuration = measureTimeMillis {
                    result = reviewLlmClientFactory.generateReview(
                        systemPrompt = systemPrompt,
                        userPrompt = userPrompt,
                        maxTokens = llmProperties.maxTokens,
                    )
                }
                reviewMetrics.recordLlmCallTime(llmCallDuration)
                result
            }

            // 7. Parse response into comments
            val reviewComments = reviewResponseParser.parse(
                llmResponse = llmResponse.content,
                reviewRequestId = reviewRequestId,
                repositoryFullName = reviewRequest.repositoryFullName,
                pullRequestNumber = reviewRequest.pullRequestNumber,
            )

            // 8. Save comments
            val savedComments = reviewComments.map { comment ->
                reviewCommentRepository.save(comment)
            }

            // 9. Post review to GitHub
            if (savedComments.isNotEmpty()) {
                val githubComments = savedComments.mapNotNull { comment ->
                    if (comment.line != null) {
                        CreateReviewCommentItem(
                            path = comment.filePath,
                            line = comment.line,
                            side = comment.side,
                            body = formatCommentBody(comment.severity.name, comment.title, comment.body, comment.suggestion),
                        )
                    } else {
                        null
                    }
                }

                val reviewBody = buildReviewSummary(savedComments.size, parsedDiff.files.size, parsedDiff.truncated)

                try {
                    gitHubApiClient.createPrReview(
                        owner = owner,
                        repo = repo,
                        prNumber = reviewRequest.pullRequestNumber,
                        installationId = reviewRequest.installationId,
                        reviewRequest = CreateReviewRequest(
                            commitId = reviewRequest.headSha,
                            body = reviewBody,
                            event = "COMMENT",
                            comments = githubComments,
                        ),
                    )
                    reviewMetrics.incrementCommentsPosted(githubComments.size)

                    // Mark comments as posted
                    savedComments.forEach { comment ->
                        reviewCommentRepository.save(comment.copy(posted = true))
                    }
                } catch (e: Exception) {
                    logger.error(e) { "Failed to post review to GitHub for $reviewRequestId" }
                    // Continue - review was processed, just couldn't post
                }
            }

            // 10. Update review request as completed
            val processingTimeMs = System.currentTimeMillis() - startTime
            val completedRequest = processingRequest.copy(
                status = ReviewStatus.COMPLETED,
                totalFiles = filteredFiles.size,
                totalLines = parsedDiff.totalLines,
                reviewedFiles = parsedDiff.files.size,
                commentCount = savedComments.size,
                llmProvider = llmResponse.provider,
                llmModel = llmResponse.model,
                llmTokensUsed = llmResponse.totalTokens,
                processingTimeMs = processingTimeMs,
            )
            reviewRequestRepository.save(completedRequest)

            reviewMetrics.incrementReviewCompleted()
            reviewMetrics.recordProcessingTime(processingTimeMs)

            logger.info {
                "Review completed: id=$reviewRequestId, files=${filteredFiles.size}, " +
                    "comments=${savedComments.size}, tokens=${llmResponse.totalTokens}, " +
                    "duration=${processingTimeMs}ms, provider=${llmResponse.provider}"
            }
        } catch (e: Exception) {
            val processingTimeMs = System.currentTimeMillis() - startTime

            logger.error(e) { "Review failed: id=$reviewRequestId, error=${e.message}" }

            val failedRequest = processingRequest.copy(
                status = ReviewStatus.FAILED,
                errorMessage = e.message,
                processingTimeMs = processingTimeMs,
            )
            reviewRequestRepository.save(failedRequest)

            reviewMetrics.incrementReviewFailed()
        }
    }

    private fun formatCommentBody(
        severity: String,
        title: String,
        body: String,
        suggestion: String?,
    ): String {
        val severityEmoji = when (severity) {
            "CRITICAL" -> "\uD83D\uDED1"
            "WARNING" -> "\u26A0\uFE0F"
            "SUGGESTION" -> "\uD83D\uDCA1"
            "PRAISE" -> "\uD83C\uDF1F"
            else -> "\uD83D\uDD0D"
        }

        val sb = StringBuilder()
        sb.appendLine("$severityEmoji **[$severity]** $title")
        sb.appendLine()
        sb.appendLine(body)

        if (!suggestion.isNullOrBlank()) {
            sb.appendLine()
            sb.appendLine("**Suggested fix:**")
            sb.appendLine("```suggestion")
            sb.appendLine(suggestion)
            sb.appendLine("```")
        }

        return sb.toString()
    }

    private fun buildReviewSummary(
        commentCount: Int,
        fileCount: Int,
        truncated: Boolean,
    ): String {
        val sb = StringBuilder()
        sb.appendLine("## AI Code Review Summary")
        sb.appendLine()
        sb.appendLine("Reviewed **$fileCount** files and found **$commentCount** comments.")

        if (truncated) {
            sb.appendLine()
            sb.appendLine("> **Note**: The diff was truncated due to size limits. Some files may not have been reviewed.")
        }

        sb.appendLine()
        sb.appendLine("---")
        sb.appendLine("*Powered by AI Code Review Bot*")

        return sb.toString()
    }
}
