package com.reviewer.domain.model

import org.springframework.data.annotation.CreatedDate
import org.springframework.data.annotation.Id
import org.springframework.data.annotation.LastModifiedDate
import org.springframework.data.mongodb.core.index.CompoundIndex
import org.springframework.data.mongodb.core.index.Indexed
import org.springframework.data.mongodb.core.mapping.Document
import java.time.Instant

@Document(collection = "review_requests")
@CompoundIndex(def = "{'repositoryFullName': 1, 'pullRequestNumber': 1}")
data class ReviewRequest(
    @Id val id: String? = null,
    @Indexed val repositoryFullName: String,
    val pullRequestNumber: Int,
    val pullRequestTitle: String,
    val pullRequestUrl: String,
    val headSha: String,
    val baseBranch: String,
    val headBranch: String,
    val authorLogin: String,
    val installationId: Long,
    @Indexed val status: ReviewStatus = ReviewStatus.QUEUED,
    val totalFiles: Int = 0,
    val totalLines: Int = 0,
    val reviewedFiles: Int = 0,
    val commentCount: Int = 0,
    val llmProvider: String? = null,
    val llmModel: String? = null,
    val llmTokensUsed: Int = 0,
    val processingTimeMs: Long = 0,
    val errorMessage: String? = null,
    val skipReason: String? = null,
    @CreatedDate val createdAt: Instant? = null,
    @LastModifiedDate val updatedAt: Instant? = null,
)

enum class ReviewStatus {
    QUEUED,
    PROCESSING,
    COMPLETED,
    FAILED,
    SKIPPED,
}
