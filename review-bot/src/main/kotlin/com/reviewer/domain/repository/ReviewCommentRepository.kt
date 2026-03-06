package com.reviewer.domain.repository

import com.reviewer.domain.model.ReviewComment
import com.reviewer.domain.model.Severity
import kotlinx.coroutines.flow.Flow
import org.springframework.data.repository.kotlin.CoroutineCrudRepository

interface ReviewCommentRepository : CoroutineCrudRepository<ReviewComment, String> {
    fun findByReviewRequestIdOrderByCreatedAtAsc(reviewRequestId: String): Flow<ReviewComment>

    fun findByRepositoryFullNameAndPullRequestNumber(
        repositoryFullName: String,
        pullRequestNumber: Int,
    ): Flow<ReviewComment>

    suspend fun countByReviewRequestId(reviewRequestId: String): Long

    suspend fun countByReviewRequestIdAndSeverity(
        reviewRequestId: String,
        severity: Severity,
    ): Long
}
