package com.reviewer.domain.model

import org.springframework.data.annotation.Id
import org.springframework.data.mongodb.core.mapping.Document
import java.time.Instant

@Document(collection = "pull_requests")
data class ReviewRequest(
    @Id val id: String? = null,
    val repositoryId: String,
    val repositoryFullName: String,
    val platformPrId: Int,
    val title: String,
    val author: String,
    val headSha: String,
    val baseBranch: String,
    val headBranch: String,
    val status: ReviewStatus = ReviewStatus.PENDING,
    val reviews: List<ReviewResult> = emptyList(),
    val createdAt: Instant? = null,
    val updatedAt: Instant? = null,
)

enum class ReviewStatus {
    PENDING, REVIEWING, COMPLETED, FAILED
}

data class ReviewResult(
    val model: String,
    val provider: String,
    val summary: String? = null,
    val comments: List<ReviewCommentEmbed> = emptyList(),
    val tokenUsage: TokenUsage? = null,
    val latencyMs: Long = 0,
    val fallbackUsed: Boolean = false,
    val createdAt: Instant = Instant.now(),
)

data class ReviewCommentEmbed(
    val filePath: String,
    val lineNumber: Int,
    val category: String,
    val severity: String,
    val content: String,
    val suggestion: String? = null,
)

data class TokenUsage(
    val inputTokens: Int,
    val outputTokens: Int,
)
