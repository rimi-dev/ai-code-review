package com.reviewer.domain.repository

import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import kotlinx.coroutines.flow.Flow
import org.springframework.data.domain.Pageable
import org.springframework.data.repository.kotlin.CoroutineCrudRepository
import java.time.Instant

interface ReviewRequestRepository : CoroutineCrudRepository<ReviewRequest, String> {
    fun findByRepositoryFullNameOrderByCreatedAtDesc(
        repositoryFullName: String,
        pageable: Pageable,
    ): Flow<ReviewRequest>

    fun findByStatusOrderByCreatedAtDesc(
        status: ReviewStatus,
        pageable: Pageable,
    ): Flow<ReviewRequest>

    suspend fun findByRepositoryFullNameAndPullRequestNumber(
        repositoryFullName: String,
        pullRequestNumber: Int,
    ): ReviewRequest?

    fun findByRepositoryFullNameAndCreatedAtBetweenOrderByCreatedAtDesc(
        repositoryFullName: String,
        start: Instant,
        end: Instant,
    ): Flow<ReviewRequest>

    suspend fun countByRepositoryFullNameAndStatus(
        repositoryFullName: String,
        status: ReviewStatus,
    ): Long

    suspend fun countByRepositoryFullNameAndCreatedAtBetween(
        repositoryFullName: String,
        start: Instant,
        end: Instant,
    ): Long

    suspend fun countByStatus(status: ReviewStatus): Long
}
