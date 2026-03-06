package com.reviewer.api.dto.response

import com.reviewer.domain.model.ReviewComment
import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.model.Severity
import java.time.Instant

data class ReviewResponse(
    val id: String,
    val repositoryFullName: String,
    val pullRequestNumber: Int,
    val pullRequestTitle: String,
    val pullRequestUrl: String,
    val headSha: String,
    val baseBranch: String,
    val headBranch: String,
    val authorLogin: String,
    val status: ReviewStatus,
    val totalFiles: Int,
    val totalLines: Int,
    val reviewedFiles: Int,
    val commentCount: Int,
    val llmProvider: String?,
    val llmModel: String?,
    val llmTokensUsed: Int,
    val processingTimeMs: Long,
    val errorMessage: String?,
    val skipReason: String?,
    val createdAt: Instant?,
    val updatedAt: Instant?,
) {
    companion object {
        fun from(entity: ReviewRequest): ReviewResponse {
            return ReviewResponse(
                id = entity.id ?: "",
                repositoryFullName = entity.repositoryFullName,
                pullRequestNumber = entity.pullRequestNumber,
                pullRequestTitle = entity.pullRequestTitle,
                pullRequestUrl = entity.pullRequestUrl,
                headSha = entity.headSha,
                baseBranch = entity.baseBranch,
                headBranch = entity.headBranch,
                authorLogin = entity.authorLogin,
                status = entity.status,
                totalFiles = entity.totalFiles,
                totalLines = entity.totalLines,
                reviewedFiles = entity.reviewedFiles,
                commentCount = entity.commentCount,
                llmProvider = entity.llmProvider,
                llmModel = entity.llmModel,
                llmTokensUsed = entity.llmTokensUsed,
                processingTimeMs = entity.processingTimeMs,
                errorMessage = entity.errorMessage,
                skipReason = entity.skipReason,
                createdAt = entity.createdAt,
                updatedAt = entity.updatedAt,
            )
        }
    }
}

data class ReviewDetailResponse(
    val review: ReviewResponse,
    val comments: List<ReviewCommentResponse>,
)

data class ReviewCommentResponse(
    val id: String,
    val filePath: String,
    val line: Int?,
    val severity: Severity,
    val category: String,
    val title: String,
    val body: String,
    val suggestion: String?,
    val posted: Boolean,
    val createdAt: Instant?,
) {
    companion object {
        fun from(entity: ReviewComment): ReviewCommentResponse {
            return ReviewCommentResponse(
                id = entity.id ?: "",
                filePath = entity.filePath,
                line = entity.line,
                severity = entity.severity,
                category = entity.category,
                title = entity.title,
                body = entity.body,
                suggestion = entity.suggestion,
                posted = entity.posted,
                createdAt = entity.createdAt,
            )
        }
    }
}
