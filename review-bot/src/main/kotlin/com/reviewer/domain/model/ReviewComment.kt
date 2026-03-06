package com.reviewer.domain.model

import org.springframework.data.annotation.CreatedDate
import org.springframework.data.annotation.Id
import org.springframework.data.mongodb.core.index.Indexed
import org.springframework.data.mongodb.core.mapping.Document
import java.time.Instant

@Document(collection = "review_comments")
data class ReviewComment(
    @Id val id: String? = null,
    @Indexed val reviewRequestId: String,
    val repositoryFullName: String,
    val pullRequestNumber: Int,
    val filePath: String,
    val line: Int?,
    val side: String = "RIGHT",
    val severity: Severity,
    val category: String,
    val title: String,
    val body: String,
    val suggestion: String? = null,
    val githubCommentId: Long? = null,
    val posted: Boolean = false,
    @CreatedDate val createdAt: Instant? = null,
)

enum class Severity {
    CRITICAL,
    WARNING,
    SUGGESTION,
    PRAISE,
}
